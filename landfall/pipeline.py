"""Run the stages of LANDFALL and write every artifact that the UI needs to out/.

Stage 1 runs for every advisory. Stage 2 and Stage 3 run for the plan advisories.
Run `python -m landfall.pipeline --help` for the options.
"""

from __future__ import annotations

import argparse
import json
import pickle
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from landfall import config as C
from landfall.config import advkey, iso
from landfall.export import geojson as gj
from landfall.impact import damage, roads, surge, wind
from landfall.ingest import atcf, census, geo, osm, static_sites
from landfall.log import get_logger, metadata, stage
from landfall.predict import reduce as red
from landfall.predict.features import ensure_fixes_cache, log_mode, online_state
from landfall.predict.model import Predictor
from landfall.predict.sample import (
    Rollout,
    category,
    cone,
    county_landfall,
    ensemble,
    hourly,
    landfall_summary,
)
from landfall.schemas import (
    Aggregate,
    Comparison,
    Ensemble,
    FirstStage,
    Infrastructure,
    Landfall,
    Meta,
    ScenarioPlan,
    Scenarios,
    Truth,
    WindRings,
    write_geojson,
    write_model,
)

log = get_logger()
H = C.HOURS + 1


@dataclass
class Stage1Result:
    """The Stage 1 output of one advisory."""

    advisory: datetime
    ro: Rollout
    scenarios: list[dict[str, Any]]
    ofcl_category: str | None


# ------------------------------------------------------------------ helpers
def _fix(t: pd.Timestamp, lat: float, lon: float, v: float, p: float | None = None) -> dict[str, Any]:
    return {"t": iso(t.to_pydatetime()), "lat": float(lat), "lon": float(lon), "vmax_kt": float(v),
            "pmin_mb": None if p is None or not np.isfinite(p) else float(p)}


def carq_frame(fixes: pd.DataFrame) -> pd.DataFrame:
    """Return the CARQ fixes of the storm."""
    return fixes[(fixes["storm_id"] == C.STORM_ID) & (fixes["source"] == "carq")].sort_values("time")


def ofcl_track(adeck: pd.DataFrame, adv: datetime) -> pd.DataFrame:
    """Return the OFCL forecast issued at an advisory time."""
    return atcf.ofcl(adeck, pd.Timestamp(adv))


def ofcl_6h(of: pd.DataFrame, n_steps: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Return the OFCL track on the 6-h grid of the ensemble (NaN after the last tau)."""
    if of.empty:
        return None
    taus = of["tau"].to_numpy(float)
    grid = np.arange(n_steps + 1) * C.STEP_H
    out = []
    for col in ("lat", "lon", "vmax_kt"):
        y = np.interp(grid, taus, of[col].to_numpy(float))
        y[grid > taus.max()] = np.nan
        out.append(y)
    return out[0], out[1], out[2]


def scenario_track(adv: datetime, carq: pd.DataFrame, lat6: np.ndarray, lon6: np.ndarray,
                   v6: np.ndarray) -> list[dict[str, Any]]:
    """Return an hourly track from T0 to T_END: observed CARQ before the advisory, forecast after."""
    from landfall.predict.features import chalk_module

    rz = chalk_module("resolvers")
    adv_h = C.time_to_hour(adv)
    obs = carq[carq["time"] <= pd.Timestamp(adv)]
    oh = np.array([C.time_to_hour(t.to_pydatetime()) for t in obs["time"]])
    fla, flo, fv = hourly(lat6, lon6, v6)
    out = []
    for h in range(H):
        if h <= adv_h:
            if len(oh) == 0 or h < oh.min():
                continue
            la = float(np.interp(h, oh, obs["lat"]))
            lo = float(np.interp(h, oh, obs["lon"]))
            v = float(np.interp(h, oh, obs["vmax_kt"]))
        else:
            k = int(round(h - adv_h))
            if k >= len(fla) or np.isnan(fla[k]):
                break
            la, lo, v = float(fla[k]), float(flo[k]), float(fv[k])
        out.append({"t": iso(C.hour_to_time(h)), "lat": round(la, 4), "lon": round(lo, 4), "vmax_kt": round(v, 1),
                    "pmin_mb": round(float(rz.pressure_from_wind(v)), 1), "rmax_km": float(wind.rmax_km(v))})
    return out


def track_arrays(track: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return hourly arrays over the whole clock (NaN where the track has no point)."""
    lat = np.full(H, np.nan)
    lon = np.full(H, np.nan)
    v = np.full(H, np.nan)
    for p in track:
        h = int(round(C.time_to_hour(datetime.fromisoformat(p["t"].replace("Z", "+00:00")))))
        if 0 <= h < H:
            lat[h], lon[h], v[h] = p["lat"], p["lon"], p["vmax_kt"]
    return lat, lon, v


def landfall_of_track(track: list[dict[str, Any]]) -> tuple[str | None, float | None, float | None, str | None]:
    """Return the county landfall time, point, and category of an hourly track."""
    if not track:
        return None, None, None, None
    la = np.array([p["lat"] for p in track])
    lo = np.array([p["lon"] for p in track])
    i = county_landfall(la, lo)
    if i is None:
        return None, None, None, None
    return track[i]["t"], float(lo[i]), float(la[i]), category(float(track[i]["vmax_kt"]))


# ------------------------------------------------------------------ Stage 1
def run_stage1(adv: datetime, pred: Predictor, fixes: pd.DataFrame, adeck: pd.DataFrame, n: int, k: int,
               index: int) -> Stage1Result:
    """Run the ensemble, the cone, the landfall summary, and the scenario reduction for one advisory."""
    key = advkey(adv)
    folder = C.OUT / "stage1" / key
    folder.mkdir(parents=True, exist_ok=True)
    seed = C.SEED * 1000 + index
    t_start = time.perf_counter()
    with stage("stage1.ensemble", advisory=key, members=n) as info:
        ro = ensemble(pred, fixes, adv, n, seed)
        info["seconds_rollout"] = round(time.perf_counter() - t_start, 2)
    secs = time.perf_counter() - t_start
    np.savez_compressed(folder / "tracks.npz", lat=ro.lat, lon=ro.lon, vmax=ro.v, pmin=ro.p, seed=seed)
    carq = carq_frame(fixes)
    of = ofcl_track(adeck, adv)
    rng = np.random.default_rng(seed)
    sub = rng.choice(n, size=min(C.N_SUBSAMPLE_UI, n), replace=False)
    members = []
    for m in sub:
        ok = ~np.isnan(ro.lat[m])
        members.append([(round(float(ro.lon[m, j]), 3), round(float(ro.lat[m, j]), 3), round(float(ro.v[m, j]), 1))
                        for j in np.where(ok)[0]])
    alive = (~np.isnan(ro.lat)).sum(axis=0)
    mean = [(round(float(np.nanmean(ro.lon[:, j])), 3), round(float(np.nanmean(ro.lat[:, j])), 3),
             round(float(np.nanmean(ro.v[:, j])), 1)) for j in range(ro.lat.shape[1]) if alive[j] >= n // 10]
    times = [iso(adv + timedelta(hours=C.STEP_H * j)) for j in range(ro.lat.shape[1])]
    obs = carq[carq["time"] <= pd.Timestamp(adv)]
    meta = metadata()
    write_model(folder / "ensemble.json", Ensemble(
        metadata=meta, advisory_time=iso(adv), n_members=n, times=times, members=members, mean=mean,
        ofcl=[_fix(r.time, r.lat, r.lon, r.vmax_kt, r.pmin_mb) for r in of.itertuples()],
        observed=[_fix(r.time, r.lat, r.lon, r.vmax_kt, r.pmin_mb) for r in obs.itertuples()],
        seconds=round(secs, 2),
    ))
    write_geojson(folder / "cone.geojson", cone(ro), meta)
    with stage("stage1.landfall", advisory=key) as info:
        lf = landfall_summary(ro, adv)
        info["p_landfall_county"] = round(lf["p_landfall_county"], 3)
    write_model(folder / "landfall.json", Landfall(metadata=meta, advisory_time=iso(adv), **lf))
    with stage("stage1.reduce", advisory=key, k=k):
        o6 = ofcl_6h(of, ro.lat.shape[1] - 1)
        rd = red.reduce_tracks(ro.lat, ro.lon, ro.v, o6, seed, k=k)
    scen = []
    ofcl_cat = None
    for si, (med, prob) in enumerate(zip(rd.medoids, rd.probability, strict=True)):
        is_ofcl = o6 is not None and si == 0
        if is_ofcl:
            la6, lo6, v6 = o6
        else:
            la6, lo6, v6 = ro.lat[med], ro.lon[med], ro.v[med]
        track = scenario_track(adv, carq, la6, lo6, v6)
        lt, llon, llat, cat = landfall_of_track([p for p in track if p["t"] > iso(adv)])
        if is_ofcl:
            fut = [p["vmax_kt"] for p in track if p["t"] > iso(adv)]
            ofcl_cat = cat or (category(max(fut)) if fut else None)
        scen.append({"id": si, "label": "OFCL" if is_ofcl else f"S{si:02d}", "probability": float(prob),
                     "is_ofcl": bool(is_ofcl), "is_worst": False, "landfall_time": lt, "landfall_lon": llon,
                     "landfall_lat": llat, "category": cat, "track": track})
    write_model(folder / "scenarios.json", Scenarios(metadata=meta, advisory_time=iso(adv), scenarios=scen))
    log.info("stage1 done", advisory=key, seconds=round(secs, 1), p_landfall=round(lf["p_landfall_county"], 3),
             landfall_p50=lf["landfall_time_p50"])
    return Stage1Result(adv, ro, scen, ofcl_cat)


def stage1_job(adv_iso: str, n: int, k: int, index: int) -> Stage1Result:
    """Run Stage 1 for one advisory in a worker (the Stage 1 sampler of the compute fan-out)."""
    import os

    import torch

    torch.set_num_threads(max(1, (os.cpu_count() or 4) // 4))
    adv = datetime.fromisoformat(adv_iso.replace("Z", "+00:00"))
    return run_stage1(adv, Predictor.load(), ensure_fixes_cache(), atcf.load(), n, k, index)


# ------------------------------------------------------------------ context
@dataclass
class Static:
    """The static data of the county."""

    grid: geo.CountyGrid
    rg: osm.RoadGraph
    bgs: Any
    zones: Any
    bg_index: np.ndarray
    bg_zone: np.ndarray


def load_static() -> Static:
    """Load the grid, the road graph, the block groups, and the zones."""
    grid = geo.county_grid()
    rg = osm.build_routing_graph()
    bgs = census.load()
    zones = static_sites.ensure_zones()
    bg_index = damage.block_group_index(grid, bgs)
    bg_zone = static_sites.zone_of_points(zones, bgs["lon"].to_numpy(), bgs["lat"].to_numpy())
    return Static(grid, rg, bgs, zones, bg_index, bg_zone)


def write_static(st: Static) -> None:
    """Write the static site files, the zones, and the display road network to out/."""
    folder = C.OUT / "static"
    folder.mkdir(parents=True, exist_ok=True)
    zones = json.loads(static_sites.ZONES_FILE.read_text())
    pop = {z: float(st.bgs["population"][st.bg_zone == z].sum()) for z in C.ZONES}
    for f in zones["features"]:
        f["properties"]["population"] = pop.get(f["properties"]["zone"], 0.0)
    write_geojson(folder / "zones.geojson", zones, metadata())
    sh = static_sites.shelters()
    (folder / "shelters.json").write_text(json.dumps([
        {"id": r.id, "name": r.name, "lat": r.lat, "lon": r.lon, "capacity": int(r.capacity),
         "is_special_needs": bool(r.is_special_needs)} for r in sh.itertuples()]))
    ho = static_sites.hospitals()
    (folder / "hospitals.json").write_text(json.dumps([
        {"id": r.id, "name": r.name, "lat": r.lat, "lon": r.lon, "beds": int(r.beds),
         "has_helipad": bool(r.has_helipad), "trauma_level": int(r.trauma_level)} for r in ho.itertuples()]))
    de = static_sites.depots()
    (folder / "depots.json").write_text(json.dumps([
        {"id": r.id, "name": r.name, "kind": r.kind, "lat": r.lat, "lon": r.lon, "trucks": int(r.trucks),
         "inventory": {c: float(getattr(r, c)) for c in ("water", "food", "med_kits", "fuel", "generators")}}
        for r in de.itertuples()]))
    a = static_sites.assets()
    (folder / "assets.json").write_text(json.dumps([
        {"id": r.id, "kind": r.kind, "name": r.name, "base_lat": r.base_lat, "base_lon": r.base_lon,
         "speed_kmh": float(r.speed_kmh), "capacity_persons": int(r.capacity_persons),
         "endurance_h": float(r.endurance_h)} for r in a.itertuples()]))
    write_geojson(C.OUT / "roads.geojson", gj.roads(st.rg.edges), metadata())


def write_truth(fixes: pd.DataFrame) -> None:
    """Write the HURDAT2 truth track and the CARQ fixes."""
    h = fixes[(fixes["storm_id"] == C.STORM_ID) & (fixes["source"] == "hurdat2")].sort_values("time")
    c = carq_frame(fixes)
    write_model(C.OUT / "truth.json", Truth(
        metadata=metadata(),
        track=[_fix(r.time, r.lat, r.lon, r.vmax_kt, r.pmin_mb) for r in h.itertuples()],
        carq=[_fix(r.time, r.lat, r.lon, r.vmax_kt, r.pmin_mb) for r in c.itertuples()],
    ))


def write_meta(advisories: list[datetime], plan_advs: list[datetime]) -> None:
    """Write out/meta.json."""
    write_model(C.OUT / "meta.json", Meta(
        metadata=metadata(), storm_id=C.STORM_ID, storm_name=C.STORM_NAME, t0=iso(C.T0), t_end=iso(C.T_END),
        hours=C.HOURS, county={"name": C.COUNTY_NAME, "fips": C.COUNTY_FIPS, "bbox": C.BBOX},
        advisories=[iso(a) for a in sorted(advisories)], plan_advisories=[iso(a) for a in sorted(plan_advs)],
        default_plan_advisory=iso(C.DEFAULT_PLAN_ADVISORY if (C.DEFAULT_PLAN_ADVISORY in plan_advs or not plan_advs) else plan_advs[0]),
        truth_landfall=C.TRUTH_LANDFALL, home_camera=C.HOME_CAMERA, assumptions=C.ASSUMPTIONS,
        commodities=C.COMMODITIES, chalk_mode=C.CHALK_MODE,
    ))


# ------------------------------------------------------------------ Stage 2
def calibrate_surge(st: Static, fixes: pd.DataFrame) -> float:
    """Calibrate the surge constant on the HURDAT2 truth track of Ian."""
    h = fixes[(fixes["storm_id"] == C.STORM_ID) & (fixes["source"] == "hurdat2")].sort_values("time")
    hh = np.array([C.time_to_hour(t.to_pydatetime()) for t in h["time"]])
    grid_h = np.arange(H, dtype=float)
    lat = np.interp(grid_h, hh, h["lat"])
    lon = np.interp(grid_h, hh, h["lon"])
    v = np.interp(grid_h, hh, h["vmax_kt"])
    coeff = surge.calibrate(st.grid, lat, lon, v)
    log.info("surge calibration", **json.loads(surge.CALIBRATION_FILE.read_text()))
    return coeff


def run_stage2(adv: datetime, s1: Stage1Result, st: Static, hospitals: pd.DataFrame,
               shelters: pd.DataFrame) -> list[Any]:
    """Compute wind, surge, damage exposure, and road hazard for every scenario of an advisory."""
    from landfall.logistics.plan import ScenarioImpact

    key = advkey(adv)
    meta = metadata()
    impacts = []
    zone_masks = {z: st.bg_zone == z for z in C.ZONES}
    for sc in s1.scenarios:
        folder = C.OUT / "impact" / key / f"s{sc['id']}"
        folder.mkdir(parents=True, exist_ok=True)
        lat, lon, v = track_arrays(sc["track"])
        wf = wind.wind_field(lat, lon, v, st.grid.lat, st.grid.lon)
        sf = surge.surge_field(st.grid, lat, lon, v)
        rings = wind.rings(lat, lon, v)
        write_model(folder / "wind.json", WindRings(metadata=meta, times=[iso(C.hour_to_time(h)) for h in range(H)],
                                                    rings=rings))
        write_geojson(folder / "gust.geojson", gj.bands(st.grid, wf.peak_gust_kt, [34, 50, 64, 96], "band_kt"), meta)
        peak_t = iso(C.hour_to_time(sf.peak_hour)) if sf.peak_hour is not None else None
        write_geojson(folder / "surge.geojson", gj.bands(st.grid, sf.depth_m, [0.3, 1.0, 2.0, 3.0], "band_m",
                                                         mask=st.grid.land, extra={"peak_time": peak_t}), meta)
        np.savez_compressed(folder / "grids.npz", gust_kt=wf.peak_gust_kt, depth_m=sf.depth_m,
                            t_ts=wf.t_ts_arrival, hours_34=wf.hours_34)
        exp = damage.exposure(st.grid, st.bg_index, st.bgs, wf.peak_gust_kt, sf.depth_m, wf.t_ts_arrival)
        hz = roads.edge_hazard(st.rg, st.grid, wf.peak_gust_kt, sf.coast_m, sf.depth_m, wf.t_peak, sf.peak_hour)
        zone_ts = np.array([np.nanmin(exp.t_ts[zone_masks[z]]) if np.isfinite(exp.t_ts[zone_masks[z]]).any()
                            else np.nan for z in C.ZONES])
        county_ts = float(np.nanmin(wf.t_ts_arrival)) if np.isfinite(wf.t_ts_arrival).any() else np.nan
        if sc["landfall_time"]:
            lf_h = C.time_to_hour(datetime.fromisoformat(sc["landfall_time"].replace("Z", "+00:00")))
        else:
            lf_h = float(np.argmax(wf.hourly_max_kt)) if wf.hourly_max_kt.max() > 0 else C.time_to_hour(adv) + 48
        t_clear = np.where(np.isfinite(wf.t_ts_arrival), wf.t_ts_arrival + wf.hours_34, lf_h)

        def site_val(field: np.ndarray, la: float, lo: float) -> float:
            return surge.sample_point(st.grid, field, la, lo, radius_cells=0)

        site_depth = {r.id: site_val(sf.depth_m, r.lat, r.lon) for r in shelters.itertuples()}
        grid_out = []
        for r in hospitals.itertuples():
            g = site_val(wf.peak_gust_kt, r.lat, r.lon) if static_sites.in_bbox(r.lon, r.lat) else 0.0
            grid_out.append(int(lf_h) if g * C.KT_TO_MPH > C.GRID_OUTAGE_GUST_MPH else None)
        impacts.append(ScenarioImpact(
            scenario_id=sc["id"], probability=sc["probability"], landfall_h=float(lf_h), zone_ts_h=zone_ts,
            county_ts_h=county_ts, exposure=exp, hazard=hz, depth=sf.depth_m,
            t_clear=np.nan_to_num(t_clear, nan=lf_h), site_depth=site_depth, hospital_grid_out_h=grid_out,
            track=sc["track"],
        ))
    log.info("stage2 done", advisory=key, scenarios=len(impacts))
    return impacts


# ------------------------------------------------------------------ Stage 3
def build_plan_context(adv: datetime, st: Static, impacts: list[Any]) -> Any:
    """Build and cache the Stage 3 context of one advisory."""
    from landfall.logistics import debris as debris_mod
    from landfall.logistics import evacuation as ev
    from landfall.logistics.network import build_net
    from landfall.logistics.plan import PlanContext, ctx_path

    net = build_net(st.rg)
    sh = static_sites.shelters()
    ho = static_sites.hospitals()
    de = static_sites.depots()
    aset = static_sites.assets()
    bg_node = np.array([net.node(lo, la) for lo, la in zip(st.bgs["lon"], st.bgs["lat"], strict=True)])
    exit_nodes = {name: net.index[node] for name, node in st.rg.exit_nodes.items()}
    shelter_nodes = [net.node(r.lon, r.lat) for r in sh.itertuples()]
    hospital_nodes = [net.node(r.lon, r.lat) if static_sites.in_bbox(r.lon, r.lat) else exit_nodes["I-75 S"]
                      for r in ho.itertuples()]
    depot_nodes, depot_extra = [], []
    for r in de.itertuples():
        if static_sites.in_bbox(r.lon, r.lat):
            depot_nodes.append(net.node(r.lon, r.lat))
            depot_extra.append(0.0)
        else:
            depot_nodes.append(exit_nodes["I-75 N"])
            depot_extra.append(3.5)
    pop = st.bgs["population"].to_numpy(float)
    inp = ev.EvacInputs(pop, st.bg_zone, bg_node, exit_nodes, list(sh["id"]), shelter_nodes,
                        sh["capacity"].to_numpy(float))
    wfile = C.CACHE / "edge_weights.pkl"
    if wfile.exists():
        weights = pickle.loads(wfile.read_bytes())
    else:
        with stage("stage3.edge_weights"):
            weights = debris_mod.edge_weights(net, bg_node, pop, hospital_nodes, shelter_nodes, seed=C.SEED)
        wfile.write_bytes(pickle.dumps(weights))
    flat = st.bg_index.ravel()
    bg_cells = [np.where(flat == i)[0] for i in range(len(st.bgs))]
    for i in range(len(st.bgs)):
        if len(bg_cells[i]) == 0:
            r = int(np.clip(np.searchsorted(st.grid.lat, st.bgs["lat"].iloc[i]), 0, len(st.grid.lat) - 1))
            c = int(np.clip(np.searchsorted(st.grid.lon, st.bgs["lon"].iloc[i]), 0, len(st.grid.lon) - 1))
            bg_cells[i] = np.array([r * len(st.grid.lon) + c])
    crit: dict[str, list[int]] = {}
    for i, e in enumerate(st.rg.edges):
        if e["critical_name"]:
            crit.setdefault(e["critical_name"], []).append(i)
    depots = [{"id": r.id, "name": r.name, "kind": r.kind, "lat": r.lat, "lon": r.lon, "trucks": int(r.trucks),
               "inventory": {c: float(getattr(r, c)) for c in ("water", "food", "med_kits", "fuel", "generators")}}
              for r in de.itertuples()]
    ctx = PlanContext(
        advisory=adv, net=net, evac_inputs=inp, bg_pop=pop, bg_zone=st.bg_zone, bg_cells=bg_cells,
        grid_lon=st.grid.lon, grid_lat=st.grid.lat, shelters=sh.to_dict("records"),
        hospitals=ho.to_dict("records"), depots=depots, assets=aset.to_dict("records"), weights=weights,
        impacts=impacts, depot_nodes=depot_nodes, depot_extra_h=depot_extra,
        site_nodes=shelter_nodes + hospital_nodes, hospital_nodes=hospital_nodes,
        critical_edges={k: np.array(v) for k, v in crit.items()},
    )
    _ = ctx_path
    return ctx


def stage3(adv: datetime, s1: Stage1Result, st: Static, impacts: list[Any], m_draws: int) -> dict[str, Any]:
    """Solve the first stage, run the logistics Monte Carlo, and write out/plan/<advisory>/."""
    from landfall.logistics import aggregate as agg
    from landfall.logistics import infrastructure as infra
    from landfall.logistics.plan import ctx_path, first_stage, solve_sample
    from landfall.predict.features import chalk_module

    key = advkey(adv)
    folder = C.OUT / "plan" / key
    folder.mkdir(parents=True, exist_ok=True)
    with stage("stage3.context", advisory=key):
        ctx = build_plan_context(adv, st, impacts)
    with stage("stage3.first_stage", advisory=key):
        ctx.plans = first_stage(ctx, s1.ofcl_category)
    path = ctx_path(adv)
    path.write_bytes(pickle.dumps(ctx))
    jobs = []
    for plan in ("optimized", "baseline"):
        for si in range(len(impacts)):
            for m in range(m_draws):
                jobs.append((str(path), plan, si, m, plan == "optimized" and m == 0))
    compute = chalk_module("compute")
    t_mc = time.perf_counter()
    with stage("stage3.monte_carlo", advisory=key, samples=len(jobs)):
        results = compute.fan_out("solve_sample", solve_sample, jobs)
    mc_seconds = time.perf_counter() - t_mc
    meta = metadata()
    out: dict[str, Any] = {}
    for plan in ("optimized", "baseline"):
        rows = [r["metrics"] for r, j in zip(results, jobs, strict=True) if j[1] == plan]
        stats = agg.aggregate(rows)
        per = agg.per_scenario(rows)
        worst = int(max(per, key=lambda r: r["objective"])["scenario_id"])
        fs = ctx.plans[plan]
        rel = {z: (iso(C.hour_to_time(h)) if h is not None else None) for z, h in fs["release"].items()}
        write_model(folder / ("aggregate.json" if plan == "optimized" else "baseline.json"), Aggregate(
            metadata=meta, plan=plan, metrics=stats, worst_case=worst, per_scenario=per, release_time=rel))
        out[plan] = {"stats": stats, "worst": worst, "rows": rows}
        if plan == "optimized":
            stage_rows = []
            for i, d in enumerate(ctx.depots):
                for j, c in enumerate(["water", "food", "med_kits", "fuel", "generators"]):
                    if fs["stage"][i, j] > 0.5:
                        stage_rows.append({"depot_id": d["id"], "commodity": c, "qty": round(float(fs["stage"][i, j]), 1)})
            write_model(folder / "first_stage.json", FirstStage(
                metadata=meta, release_time=rel,
                open_shelters=[s["id"] for k, s in enumerate(ctx.shelters) if fs["open"][k]],
                staging=stage_rows, objective=float(fs["release_objective"] + fs["supply_objective"]),
                method="greedy release search + two-stage HiGHS LP for supply"))
    # Representative plans of the optimized first stage.
    for r in results:
        if "plan" not in r:
            continue
        sid = int(r["metrics"]["scenario_id"])
        p = r["plan"]
        write_model(folder / f"s{sid}.json", ScenarioPlan(metadata=meta, **p["plan"]))
        (folder / f"s{sid}.czml").write_text(json.dumps(p["czml"], separators=(",", ":")))
    # Comparison table.
    rows_c = []
    for mkey, better in (("persons_not_cleared", "lower"), ("persons_at_risk", "lower"), ("unmet_supply_kg", "lower"),
                         ("expected_rescues", "lower"), ("unmet_tasks_72h", "lower"),
                         ("persons_evacuated_unnecessarily", "lower"), ("clearance_margin_h", "higher"),
                         ("objective", "lower")):
        rows_c.append({"metric": mkey, "label_key": f"metric.{mkey}",
                       "optimized": out["optimized"]["stats"][mkey]["expected"],
                       "baseline": out["baseline"]["stats"][mkey]["expected"], "better": better})
    write_model(folder / "comparison.json", Comparison(metadata=meta, rows=rows_c))
    # Infrastructure insight over all samples of the optimized plan.
    opt = [(r, j) for r, j in zip(results, jobs, strict=True) if j[1] == "optimized"]
    blocked = np.sum([r["blocked"] for r, _ in opt], axis=0)
    late = np.sum([r["late"] for r, _ in opt], axis=0)
    full = np.sum([r["full"] for r, _ in opt], axis=0)
    n_s = len(opt)
    write_model(folder / "infrastructure.json", Infrastructure(
        metadata=meta, harden=infra.harden_list(ctx.net, blocked, n_s, ctx.weights),
        zones_flagged=infra.zone_flags(late, n_s),
        shelters_flagged=infra.shelter_flags([s["id"] for s in ctx.shelters], full, n_s)))
    # Mark the worst scenario in the scenario file of this advisory.
    s_file = C.OUT / "stage1" / key / "scenarios.json"
    sj = json.loads(s_file.read_text())
    for s in sj["scenarios"]:
        s["is_worst"] = s["id"] == out["optimized"]["worst"]
    write_model(s_file, Scenarios.model_validate(sj))
    secs = [r["metrics"]["seconds"] for r in results]
    log.info("stage3 done", advisory=key, samples=len(jobs), mc_seconds=round(mc_seconds, 1),
             max_sample_s=round(max(secs), 1), mean_sample_s=round(float(np.mean(secs)), 2),
             not_cleared_opt=round(out["optimized"]["stats"]["persons_not_cleared"]["expected"]),
             not_cleared_base=round(out["baseline"]["stats"]["persons_not_cleared"]["expected"]))
    return out


# ------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> None:
    """Run the pipeline from the command line."""
    ap = argparse.ArgumentParser(description="Run the LANDFALL pipeline and write out/.")
    ap.add_argument("--n", type=int, default=C.N_MEMBERS, help="ensemble members")
    ap.add_argument("--k", type=int, default=C.K_SCENARIOS, help="reduced scenarios")
    ap.add_argument("--m", type=int, default=C.M_DRAWS, help="logistics draws per scenario")
    ap.add_argument("--advisory", action="append", help="limit Stage 1 to these advisories (YYYYMMDDHH)")
    ap.add_argument("--plans", default=",".join(advkey(a) for a in C.PLAN_ADVISORIES),
                    help="plan advisories (YYYYMMDDHH, comma separated; empty for none)")
    ap.add_argument("--skip-verify", action="store_true")
    ap.add_argument("--clean", action="store_true", help="remove out/ first")
    args = ap.parse_args(argv)
    if args.clean and C.OUT.exists():
        shutil.rmtree(C.OUT)
    C.OUT.mkdir(exist_ok=True)
    log_mode()
    t_all = time.perf_counter()
    fixes = ensure_fixes_cache()
    st = load_static()
    write_static(st)
    write_truth(fixes)
    advs = C.advisory_times()
    if args.advisory:
        advs = [a for a in advs if advkey(a) in args.advisory]
    plan_keys = [p for p in args.plans.split(",") if p]
    plan_advs = [a for a in C.PLAN_ADVISORIES if advkey(a) in plan_keys]
    for a in plan_advs:
        if a not in advs:
            advs.append(a)
    advs = sorted(advs)
    _ = online_state
    from landfall.predict.features import chalk_module

    compute = chalk_module("compute")
    index = {a: i for i, a in enumerate(C.advisory_times() + [p for p in C.PLAN_ADVISORIES if p not in C.advisory_times()])}
    with stage("stage1.all", advisories=len(advs)):
        res1 = compute.fan_out("stage1_sampler", stage1_job,
                               [(iso(a), args.n, args.k, index.get(a, 0)) for a in advs], n_jobs=4)
    s1: dict[datetime, Stage1Result] = {r.advisory: r for r in res1}
    if not args.skip_verify:
        from landfall.predict.verify import verify

        with stage("verify"):
            verify()
    if plan_advs:
        calibrate_surge(st, fixes)
    done_plans = []
    for a in plan_advs:
        with stage("stage2", advisory=advkey(a)):
            impacts = run_stage2(a, s1[a], st, static_sites.hospitals(), static_sites.shelters())
        stage3(a, s1[a], st, impacts, args.m)
        done_plans.append(a)
    existing = sorted({datetime.strptime(p.name, "%Y%m%d%H").replace(tzinfo=C.T0.tzinfo)
                       for p in (C.OUT / "stage1").iterdir() if p.is_dir()})
    plans_existing = sorted({datetime.strptime(p.name, "%Y%m%d%H").replace(tzinfo=C.T0.tzinfo)
                             for p in (C.OUT / "plan").iterdir() if (p / "aggregate.json").exists()}) \
        if (C.OUT / "plan").exists() else done_plans
    write_meta(existing, plans_existing or done_plans)
    log.info("pipeline done", seconds=round(time.perf_counter() - t_all, 1), advisories=len(advs),
             plans=len(done_plans))


if __name__ == "__main__":
    main()
