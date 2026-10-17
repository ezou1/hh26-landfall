"""Run Stage 3: the first-stage decisions and the logistics Monte Carlo for one advisory.

The first stage has 3 parts:

- A greedy coordinate search sets the release time of each zone.
- A flood rule selects the shelters to open.
- A two-stage HiGHS LP sets the supply staging.

Each scenario then runs M draws of behaviour, road blockage, and rescue requests.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse.csgraph import dijkstra

from landfall.config import (
    CACHE,
    COMMODITIES,
    EVAC_COMPLIANCE,
    EVAC_COMPLIANCE_RANGE,
    EXITS,
    HOURS,
    INJURY_ADMIT_FRACTION,
    M_DRAWS,
    PERSONS_PER_HOUSEHOLD,
    RELEASE_BIN_H,
    SAR_HORIZON_H,
    SAR_START_AFTER_LANDFALL_H,
    SEED,
    SUPPLY_WINDOW_H,
    T0,
    TRUCK_CAPACITY_KG,
    VEHICLES_PER_HOUSEHOLD,
    W1_NOT_CLEARED,
    W2_UNMET_SUPPLY,
    W3_RESCUE,
    W4_UNNECESSARY,
    W5_TRANSPORT,
    ZONES,
    hour_to_time,
    iso,
    time_to_hour,
)
from landfall.impact.damage import BlockGroupExposure, injuries, p_major_damage, rescue_requests
from landfall.impact.roads import EdgeHazard, sample_blocked
from landfall.logistics import debris as debris_mod
from landfall.logistics import evacuation as ev
from landfall.logistics import sar as sar_mod
from landfall.logistics.demand import COMMODITY_IDS, N_WINDOWS, site_demand
from landfall.logistics.medevac import hospital_beds
from landfall.logistics.network import Net
from landfall.logistics.supply import SupplyScenario, solve

H = HOURS + 1
ORLANDO_EXTRA_H = 3.5
SAR_TIME_LIMIT_S = 1.5
KG = np.array([c["kg_per_unit"] for c in COMMODITIES])
UNITS = {c["id"]: c["unit"] for c in COMMODITIES}


@dataclass
class ScenarioImpact:
    """The Stage 2 output of one scenario that Stage 3 needs."""

    scenario_id: int
    probability: float
    landfall_h: float
    zone_ts_h: np.ndarray  # (Z,)
    county_ts_h: float
    exposure: BlockGroupExposure
    hazard: EdgeHazard
    depth: np.ndarray  # grid (ny, nx)
    t_clear: np.ndarray  # grid: first hour after the TS wind ends
    site_depth: dict[str, float]
    hospital_grid_out_h: list[int | None]
    track: list[dict[str, Any]]


@dataclass
class PlanContext:
    """Everything that a Stage 3 worker needs. The pipeline pickles it to a cache file."""

    advisory: datetime
    net: Net
    evac_inputs: ev.EvacInputs
    bg_pop: np.ndarray
    bg_zone: np.ndarray
    bg_cells: list[np.ndarray]
    grid_lon: np.ndarray
    grid_lat: np.ndarray
    shelters: list[dict[str, Any]]
    hospitals: list[dict[str, Any]]
    depots: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    weights: debris_mod.EdgeWeights
    impacts: list[ScenarioImpact]
    depot_nodes: list[int]
    depot_extra_h: list[float]
    site_nodes: list[int]
    hospital_nodes: list[int]
    critical_edges: dict[str, np.ndarray]
    assignments: dict[frozenset[str], ev.Assignment] = field(default_factory=dict)
    plans: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> first stage


def ctx_path(advisory: datetime) -> Path:
    """Return the cache file of the plan context."""
    return CACHE / f"plan_ctx_{advisory.strftime('%Y%m%d%H')}.pkl"


_CTX: dict[str, PlanContext] = {}


def load_ctx(path: str) -> PlanContext:
    """Load a plan context once per worker process."""
    if path not in _CTX:
        with open(path, "rb") as fh:
            _CTX[path] = pickle.load(fh)
    return _CTX[path]


# ------------------------------------------------------------------ helpers
def ordered_set(release: dict[str, float | None]) -> frozenset[str]:
    """Return the set of zones with a release time."""
    return frozenset(z for z, r in release.items() if r is not None)


def assignment(ctx: PlanContext, release: dict[str, float | None]) -> ev.Assignment:
    """Return the cached route assignment of a release plan."""
    key = ordered_set(release)
    if key not in ctx.assignments:
        ctx.assignments[key] = ev.assign(ctx.net, ctx.evac_inputs, set(key))
    return ctx.assignments[key]


def bg_evac_frac(ctx: PlanContext, res: ev.EvacResult) -> np.ndarray:
    """Return the cleared fraction of each block group from the zone results."""
    zf = {z: res.evac_frac[k] for k, z in enumerate(ZONES)}
    return np.array([zf.get(z, 0.0) for z in ctx.bg_zone])


def flood_frac(imp: ScenarioImpact) -> np.ndarray:
    """Return the flooded area fraction of each block group."""
    return np.clip(imp.exposure.p_deep + imp.exposure.p_shallow, 0.0, 1.0)


def evac_terms(ctx: PlanContext, imp: ScenarioImpact, res: ev.EvacResult) -> dict[str, float]:
    """Return the evacuation terms of the objective for one scenario."""
    frac = bg_evac_frac(ctx, res)
    rescue = rescue_requests(ctx.bg_pop, imp.exposure.p_deep, frac).sum()
    ff = flood_frac(imp)
    zone_noflood = np.zeros(len(ZONES))
    for k, z in enumerate(ZONES):
        m = ctx.bg_zone == z
        pop = ctx.bg_pop[m].sum()
        zone_noflood[k] = (ctx.bg_pop[m] * (ff[m] < 0.01)).sum() / pop if pop > 0 else 0.0
    cleared_total = res.cleared[:, -1]
    unnecessary = float((cleared_total * zone_noflood).sum())
    # Persons at risk: persons in flooded areas. Not cleared: these persons that are still
    # in the area when the TS wind arrives (they did not leave, or they did not clear in time).
    at_risk = float((ctx.bg_pop * ff).sum())
    not_cleared = float((ctx.bg_pop * ff * (1 - frac)).sum())
    return {"persons_not_cleared": not_cleared, "rescue_demand": float(rescue),
            "persons_evacuated_unnecessarily": unnecessary, "persons_at_risk": at_risk,
            "persons_evacuated": float(cleared_total.sum())}


def release_objective(ctx: PlanContext, release: dict[str, float | None]) -> float:
    """Return the expected evacuation objective of a release plan over all scenarios."""
    asg = assignment(ctx, release)
    total = 0.0
    for imp in ctx.impacts:
        res = ev.simulate(ctx.net, ctx.evac_inputs, asg, release, EVAC_COMPLIANCE, imp.zone_ts_h)
        t = evac_terms(ctx, imp, res)
        total += imp.probability * (W1_NOT_CLEARED * t["persons_not_cleared"] + W3_RESCUE * t["rescue_demand"]
                                    + W4_UNNECESSARY * t["persons_evacuated_unnecessarily"])
    return total


def baseline_release(ctx: PlanContext, ofcl_category: str | None) -> dict[str, float | None]:
    """Return the baseline release plan: zone A at a Cat 1 forecast, B at Cat 2, and so on.

    The baseline issues the orders 12 h after the advisory, rounded to the 6-h bin.
    """
    cat = {"TS": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}.get(ofcl_category or "TS", 0)
    t = time_to_hour(ctx.advisory) + 12
    t = math.ceil(t / RELEASE_BIN_H) * RELEASE_BIN_H
    return {z: (float(t) if k < cat else None) for k, z in enumerate(ZONES)}


def optimize_release(ctx: PlanContext, start: dict[str, float | None], passes: int = 2) -> tuple[dict[str, float | None], float]:
    """Improve a release plan with a greedy coordinate search over 6-h bins."""
    adv_h = time_to_hour(ctx.advisory)
    first = math.ceil(adv_h / RELEASE_BIN_H) * RELEASE_BIN_H
    cands: list[float | None] = [None] + [float(first + RELEASE_BIN_H * k) for k in range(8) if first + RELEASE_BIN_H * k <= HOURS]
    best = dict(start)
    best_obj = release_objective(ctx, best)
    for _ in range(passes):
        improved = False
        for z in ZONES:
            for c in cands:
                trial = dict(best)
                trial[z] = c
                if trial == best:
                    continue
                obj = release_objective(ctx, trial)
                if obj < best_obj - 1e-6:
                    best, best_obj, improved = trial, obj, True
        if not improved:
            break
    return best, best_obj


# ------------------------------------------------------------------ road times
def closed_mask(imp_blocked: np.ndarray, blocked_h: np.ndarray, reopen_h: np.ndarray, h: float) -> np.ndarray:
    """Return the closed edges at hour h."""
    return debris_mod.closed_at(imp_blocked, blocked_h, reopen_h, h)


def depot_times(ctx: PlanContext, closed: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Return (travel hours, predecessors) from each depot node to every node."""
    m = ctx.net.matrix(ctx.net.tt_h, closed)
    dist, pred = dijkstra(m, directed=True, indices=ctx.depot_nodes, return_predecessors=True)
    dist = dist + np.array(ctx.depot_extra_h)[:, None]
    return dist, pred


def supply_reach(ctx: PlanContext, imp: ScenarioImpact, blocked: np.ndarray | None, blocked_h: np.ndarray | None,
                 reopen_h: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, list[tuple[np.ndarray, np.ndarray]]]:
    """Return reach (D, J, W), travel hours (D, J, W), and the trees of each window."""
    d_n, j_n = len(ctx.depots), len(ctx.site_nodes)
    reach = np.zeros((d_n, j_n, N_WINDOWS), bool)
    travel = np.zeros((d_n, j_n, N_WINDOWS))
    trees = []
    no_trucks = (imp.county_ts_h, imp.landfall_h + SAR_START_AFTER_LANDFALL_H)
    cache: dict[bytes, tuple[np.ndarray, np.ndarray]] = {}
    for w in range(N_WINDOWS):
        h0 = w * SUPPLY_WINDOW_H
        closed = None
        if blocked is not None and h0 >= imp.landfall_h:
            closed = closed_mask(blocked, blocked_h, reopen_h, h0)
        key = b"none" if closed is None else np.packbits(closed).tobytes()
        if key not in cache:
            cache[key] = depot_times(ctx, closed)
        dist, pred = cache[key]
        trees.append((dist, pred))
        t = dist[:, ctx.site_nodes]
        travel[:, :, w] = np.where(np.isfinite(t), t, 0.0)
        storm = (h0 + SUPPLY_WINDOW_H > no_trucks[0]) and (h0 < no_trucks[1]) if np.isfinite(no_trucks[0]) else False
        reach[:, :, w] = np.isfinite(t) & (not storm) & (h0 >= time_to_hour(ctx.advisory))
    return reach, travel, trees


def site_people(ctx: PlanContext, res: ev.EvacResult, open_mask: np.ndarray, imp: ScenarioImpact,
                injuries_total: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return shelter occupancy (S, H), hospital patients (Hs, H), and hospital injuries (Hs, H)."""
    occ = res.shelter_occ * open_mask[:, None]
    total = np.array([float(h["beds"]) for h in ctx.hospitals])
    share = total / total.sum()
    inj_h = injury_curve(imp.landfall_h, injuries_total * INJURY_ADMIT_FRACTION)
    inj = share[:, None] * inj_h[None, :]
    base = total * (1 - 0.25)
    patients = np.minimum(total[:, None], base[:, None] + np.cumsum(inj, axis=1))
    return occ, patients, inj


def injury_curve(landfall_h: float, total: float) -> np.ndarray:
    """Return the hourly injuries: a triangle from 3 h before landfall to 24 h after."""
    t = np.arange(H, dtype=float)
    a, peak, b = landfall_h - 3, landfall_h + 3, landfall_h + 24
    w = np.where(t < peak, (t - a) / (peak - a), (b - t) / (b - peak))
    w = np.clip(w, 0, None)
    return total * w / w.sum() if w.sum() > 0 else np.zeros(H)


def county_injuries(ctx: PlanContext, imp: ScenarioImpact, frac: np.ndarray) -> float:
    """Return the expected injuries in the county."""
    pm = p_major_damage(imp.exposure.gust_kt, imp.exposure.depth_m)
    return float(injuries(ctx.bg_pop, pm, frac).sum())


# ------------------------------------------------------------------ first stage
def first_stage(ctx: PlanContext, ofcl_category: str | None) -> dict[str, dict[str, Any]]:
    """Solve the optimized and the baseline first-stage decisions."""
    from landfall.log import get_logger

    log = get_logger()
    base_rel = baseline_release(ctx, ofcl_category)
    opt_rel, opt_obj = optimize_release(ctx, base_rel)
    base_obj = release_objective(ctx, base_rel)
    log.info("release search", baseline=base_rel, optimized=opt_rel, baseline_obj=round(base_obj), optimized_obj=round(opt_obj))
    # Shelters: open a shelter if its chance of flooding is less than 20%.
    p_flood = np.array([sum(imp.probability * (imp.site_depth[s["id"]] > 0.3) for imp in ctx.impacts)
                        for s in ctx.shelters])
    open_opt = p_flood < 0.2
    open_base = np.ones(len(ctx.shelters), bool)
    plans = {}
    for name, rel, open_mask in (("optimized", opt_rel, open_opt), ("baseline", base_rel, open_base)):
        asg = assignment(ctx, rel)
        scen = []
        for imp in ctx.impacts:
            res = ev.simulate(ctx.net, ctx.evac_inputs, asg, rel, EVAC_COMPLIANCE, imp.zone_ts_h)
            frac = bg_evac_frac(ctx, res)
            occ, patients, inj = site_people(ctx, res, open_mask, imp, county_injuries(ctx, imp, frac))
            dem = site_demand([s["id"] for s in ctx.shelters], occ, [h["id"] for h in ctx.hospitals], patients,
                              inj, imp.hospital_grid_out_h)
            planning_blocked, plan_bh, plan_reopen = planning_roads(ctx, imp)
            reach, travel, _ = supply_reach(ctx, imp, planning_blocked, plan_bh, plan_reopen)
            scen.append(SupplyScenario(imp.probability, dem.demand, reach, travel, site_dist_km(ctx)))
        inv = np.array([[float(d["inventory"][c]) for c in COMMODITY_IDS] for d in ctx.depots])
        trucks = np.array([float(d["trucks"]) for d in ctx.depots])
        kinds = [str(d["kind"]) for d in ctx.depots]
        if name == "optimized":
            sol = solve(scen, inv, trucks, KG, kinds)
            stage = sol.stage
        else:
            stage = baseline_stage(ctx, scen, inv)
            sol = solve(scen, inv, trucks, KG, kinds, fixed_stage=stage)
        plans[name] = {"release": rel, "open": open_mask, "stage": stage, "supply_objective": sol.objective,
                       "release_objective": opt_obj if name == "optimized" else base_obj}
        log.info("first stage", plan=name, supply_objective=round(sol.objective), status=sol.status)
    return plans


def planning_roads(ctx: PlanContext, imp: ScenarioImpact) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return one planning sample of the road state and its reopen hours (sample-average approximation)."""
    rng = np.random.default_rng([SEED, imp.scenario_id, 99])
    bs = sample_blocked(imp.hazard, rng)
    blocked = bs.blocked
    bh = np.minimum(bs.blocked_h, imp.landfall_h)
    repair = np.array([bs.cause[i] == "bridge" or (bool(e["is_critical"]) and bs.cause[i] == "flood")
                       for i, e in enumerate(ctx.net.rg.edges)]) & blocked
    bases = [(float(d["lon"]), float(d["lat"])) for d in ctx.depots if d["kind"] == "county"]
    deb = debris_mod.schedule(ctx.net, blocked, bh, repair, imp.landfall_h + SAR_START_AFTER_LANDFALL_H,
                              ctx.weights, bases)
    return blocked, bh, deb.reopen_h


def baseline_stage(ctx: PlanContext, scen: list[SupplyScenario], inv: np.ndarray) -> np.ndarray:
    """Return the baseline staging: the expected demand, split by population over the county depots."""
    total = sum(s.probability * s.demand.sum(axis=(0, 2)) for s in scen)  # (C,)
    county = [i for i, d in enumerate(ctx.depots) if d["kind"] != "state"]
    dep_ll = np.array([[float(ctx.depots[i]["lon"]), float(ctx.depots[i]["lat"])] for i in county])
    pop_share = np.zeros(len(county))
    from landfall.geoutil import haversine_km

    bg_lon = np.array([ctx.net.rg.node_xy[int(ctx.net.node_ids[n])][0] for n in ctx.evac_inputs.bg_node])
    bg_lat = np.array([ctx.net.rg.node_xy[int(ctx.net.node_ids[n])][1] for n in ctx.evac_inputs.bg_node])
    d = haversine_km(bg_lat[:, None], bg_lon[:, None], dep_ll[:, 1][None, :], dep_ll[:, 0][None, :])
    near = np.argmin(d, axis=1)
    for k in range(len(county)):
        pop_share[k] = ctx.bg_pop[near == k].sum()
    pop_share /= pop_share.sum()
    stage = np.zeros_like(inv)
    for k, i in enumerate(county):
        stage[i] = np.minimum(inv[i], total * pop_share[k])
    rest = np.maximum(0.0, total - stage.sum(axis=0))
    state = [i for i, d in enumerate(ctx.depots) if d["kind"] == "state"]
    if state:
        stage[state[0]] = np.minimum(inv[state[0]], rest)
    return stage


def site_dist_km(ctx: PlanContext) -> np.ndarray:
    """Return the straight-line distance in km from each depot to each site (for the cost)."""
    from landfall.geoutil import haversine_km

    sites = ctx.shelters + ctx.hospitals
    return np.array([[float(haversine_km(d["lat"], d["lon"], s["lat"], s["lon"])) for s in sites] for d in ctx.depots])


# ------------------------------------------------------------------ one sample
def solve_sample(ctx_file: str, plan: str, s_index: int, draw: int, write_full: bool) -> dict[str, Any]:
    """Run one logistics sample: evacuation, blockage, debris, SAR, medevac, and supply."""
    import time

    t_start = time.perf_counter()
    ctx = load_ctx(ctx_file)
    fs = ctx.plans[plan]
    imp = ctx.impacts[s_index]
    rng = np.random.default_rng([SEED, s_index, draw, 0 if plan == "optimized" else 1])
    comp = float(rng.uniform(*EVAC_COMPLIANCE_RANGE))
    rel = fs["release"]
    asg = assignment(ctx, rel)
    res = ev.simulate(ctx.net, ctx.evac_inputs, asg, rel, comp, imp.zone_ts_h)
    terms = evac_terms(ctx, imp, res)
    frac = bg_evac_frac(ctx, res)
    # Road blockage and debris clearing.
    bs = sample_blocked(imp.hazard, rng)
    repair = np.zeros(len(bs.blocked), bool)
    for i in np.where(bs.blocked)[0]:
        e = ctx.net.rg.edges[i]
        if bs.cause[i] == "bridge" or (e["is_critical"] and bs.cause[i] == "flood"):
            repair[i] = True
    start_h = imp.landfall_h + SAR_START_AFTER_LANDFALL_H
    blocked_h = np.minimum(bs.blocked_h, imp.landfall_h)
    crew_bases = [(float(d["lon"]), float(d["lat"])) for d in ctx.depots if d["kind"] == "county"]
    deb = debris_mod.schedule(ctx.net, bs.blocked, blocked_h, repair, start_h, ctx.weights, crew_bases)
    # SAR tasks and routing.
    rescue = rescue_requests(ctx.bg_pop, imp.exposure.p_deep, frac)
    tasks = sar_mod.make_tasks(rng, rescue, ctx.bg_cells, ctx.grid_lon, ctx.grid_lat, imp.depth, imp.t_clear, start_h)
    closed_sar = closed_mask(bs.blocked, blocked_h, deb.reopen_h, start_h + 12)
    blocked_links = {name for name, idx in ctx.critical_edges.items() if len(idx) and closed_sar[idx].any()}
    truck_cost = ctx.net.length_m / 1000.0 / 40.0
    mat = ctx.net.matrix(truck_cost, closed_sar)

    def road_time(points: list[tuple[float, float]]) -> np.ndarray:
        nodes = [ctx.net.node(lon, lat) for lon, lat in points]
        uniq = sorted(set(nodes))
        dist = dijkstra(mat, directed=True, indices=uniq)
        pos = {n: i for i, n in enumerate(uniq)}
        rows = np.array([pos[n] for n in nodes])
        out = dist[rows][:, nodes]
        return out + 0.1  # 6 min to reach the point from the road

    helipads = [(str(h["id"]), float(h["lat"]), float(h["lon"])) for h in ctx.hospitals if h["has_helipad"]]
    routes = sar_mod.run_sar(tasks, ctx.assets, start_h, road_time, blocked_links, helipads, SAR_TIME_LIMIT_S)
    injuries_total = county_injuries(ctx, imp, frac)
    free_beds, patients_sar = hospital_beds(ctx.hospitals, tasks,
                                            injury_curve(imp.landfall_h, injuries_total * INJURY_ADMIT_FRACTION), rng)
    # Supply recourse with the fixed staging.
    occ, patients, inj = site_people(ctx, res, fs["open"], imp, injuries_total)
    patients = np.maximum(patients, patients_sar)
    dem = site_demand([s["id"] for s in ctx.shelters], occ, [h["id"] for h in ctx.hospitals], patients, inj,
                      imp.hospital_grid_out_h)
    reach, travel, trees = supply_reach(ctx, imp, bs.blocked, blocked_h, deb.reopen_h)
    inv = np.array([[float(d["inventory"][c]) for c in COMMODITY_IDS] for d in ctx.depots])
    trucks = np.array([float(d["trucks"]) for d in ctx.depots])
    sol = solve([SupplyScenario(1.0, dem.demand, reach, travel, site_dist_km(ctx))], inv, trucks, KG,
                [str(d["kind"]) for d in ctx.depots], fixed_stage=fs["stage"])
    unmet_kg = float((sol.unmet[0] * KG[None, :, None]).sum())
    transport = float((sol.ship[0] * KG[None, None, :, None] * site_dist_km(ctx)[:, :, None, None]).sum() / 1000.0)
    # SAR metrics.
    served = [t for t in tasks if t.served_h is not None]
    ttr = np.array([t.served_h - t.created_h for t in served])
    horizon_end = start_h + SAR_HORIZON_H
    rescued_72 = sum(t.persons for t in served if t.served_h <= horizon_end)
    unmet_tasks = sum(1 for t in tasks if t.served_h is None or t.served_h > horizon_end)
    margins = [imp.zone_ts_h[k] - res.clearance_h[k] for k in range(len(ZONES))
               if np.isfinite(imp.zone_ts_h[k]) and res.persons[k] > 0]
    margin = float(min(margins)) if margins and all(np.isfinite(margins)) else (-24.0 if margins else 0.0)
    rescue_demand = float(rescue.sum())
    objective = (W1_NOT_CLEARED * terms["persons_not_cleared"] + W2_UNMET_SUPPLY * unmet_kg
                 + W3_RESCUE * rescue_demand + W4_UNNECESSARY * terms["persons_evacuated_unnecessarily"]
                 + W5_TRANSPORT * transport)
    late = np.array([np.isfinite(imp.zone_ts_h[k]) and res.persons[k] > 0 and
                     (not np.isfinite(res.clearance_h[k]) or res.clearance_h[k] > imp.zone_ts_h[k])
                     for k in range(len(ZONES))])
    full = (res.shelter_occ.max(axis=1) >= 0.98 * ctx.evac_inputs.shelter_cap) & fs["open"]
    metrics = {
        "scenario_id": float(imp.scenario_id), "draw": float(draw), "probability": imp.probability,
        "weight": imp.probability / M_DRAWS,
        "persons_at_risk": terms["persons_at_risk"], "persons_not_cleared": terms["persons_not_cleared"],
        "persons_evacuated": terms["persons_evacuated"],
        "persons_evacuated_unnecessarily": terms["persons_evacuated_unnecessarily"],
        "unmet_supply_kg": unmet_kg, "expected_rescues": rescue_demand,
        "persons_rescued_72h": float(rescued_72), "unmet_tasks_72h": float(unmet_tasks),
        "median_time_to_rescue_h": float(np.median(ttr)) if len(ttr) else float("nan"),
        "clearance_margin_h": margin, "objective": objective, "blocked_edges": float(bs.blocked.sum()),
        "transport_cost": transport, "compliance": comp, "helo_tasks": float(sum(t.asset_type == "helo" for t in tasks)),
        "helo_island_tasks_served": float(sum(t.asset_type == "helo" and t.island is not None and t.served_h is not None for t in tasks)),
        "critical_blocked": float(len(blocked_links)), "seconds": 0.0,
    }
    out: dict[str, Any] = {"metrics": metrics, "blocked": bs.blocked, "late": late, "full": full}
    if write_full:
        from landfall.logistics.plan_export import scenario_plan

        out["plan"] = scenario_plan(ctx, imp, plan, res, bs, blocked_h, deb, tasks, routes, free_beds, sol, trees,
                                    reach, metrics, blocked_links)
    metrics["seconds"] = time.perf_counter() - t_start
    return out


def persons_per_vehicle() -> float:
    """Return the persons in each evacuation vehicle."""
    return PERSONS_PER_HOUSEHOLD / VEHICLES_PER_HOUSEHOLD


def window_time(w: int) -> str:
    """Return the start time of a supply window."""
    return iso(hour_to_time(w * SUPPLY_WINDOW_H))


def exits_list() -> list[str]:
    """Return the names of the county exits."""
    return list(EXITS)


def truck_trips(kg_total: float) -> int:
    """Return the number of trucks for a load."""
    return max(1, math.ceil(kg_total / TRUCK_CAPACITY_KG))


_ = T0
