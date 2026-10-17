"""Build the full plan artifact and the CZML packets of one representative sample."""

from __future__ import annotations

from typing import Any

import numpy as np

from landfall.config import COMMODITIES, HOURS, SAR_HORIZON_H, SUPPLY_WINDOW_H, hour_to_time, iso
from landfall.export.czml import along_path, document, mover
from landfall.logistics.demand import COMMODITY_IDS, N_WINDOWS

H = HOURS + 1
UNITS = {c["id"]: c["unit"] for c in COMMODITIES}
KG = np.array([c["kg_per_unit"] for c in COMMODITIES])
EVAC_MIN_VPH = 40.0


def _t(h: float) -> str:
    return iso(hour_to_time(float(np.clip(h, 0, HOURS))))


def _path_from_source(pred_row: np.ndarray, target: int) -> list[int]:
    out = [target]
    cur = target
    while pred_row[cur] >= 0 and len(out) < 5000:
        cur = int(pred_row[cur])
        out.append(cur)
    return out[::-1]


def scenario_plan(ctx: Any, imp: Any, plan: str, res: Any, bs: Any, blocked_h: np.ndarray, deb: Any,
                  tasks: list[Any], routes: list[Any], free_beds: np.ndarray, sol: Any,
                  trees: list[tuple[np.ndarray, np.ndarray]], reach: np.ndarray, metrics: dict[str, float],
                  blocked_links: set[str]) -> dict[str, Any]:
    """Return the plan dict (ScenarioPlan fields without metadata) and the CZML packets."""
    from landfall.config import ZONES
    from landfall.logistics.plan import bg_evac_frac, flood_frac

    net = ctx.net
    at_risk_left = ctx.bg_pop * flood_frac(imp) * (1 - bg_evac_frac(ctx, res))
    zones = []
    for k, z in enumerate(ZONES):
        rel = res.release_h.get(z)
        ts = imp.zone_ts_h[k]
        clr = res.clearance_h[k]
        margin = float(ts - clr) if np.isfinite(ts) and np.isfinite(clr) else None
        zones.append({
            "zone": z, "release_time": _t(rel) if rel is not None else None,
            "clearance_time": _t(clr) if np.isfinite(clr) else None,
            "ts_arrival": _t(ts) if np.isfinite(ts) else None, "margin_h": margin,
            "population": float(ctx.bg_pop[ctx.bg_zone == z].sum()), "evacuees": float(res.persons[k]),
            "not_cleared": float(at_risk_left[ctx.bg_zone == z].sum()),
        })
    evac_edges = []
    seen: set[tuple[int, int]] = set()
    peak = res.edge_vph.max(axis=1)
    for i in np.argsort(-peak):
        if peak[i] < EVAC_MIN_VPH or len(evac_edges) >= 2500:
            break
        key = (int(net.eu[i]), int(net.ev[i]))
        if key in seen:
            continue
        seen.add(key)
        nz = np.nonzero(res.edge_vph[i] > 1.0)[0]
        h0, h1 = int(nz[0]), int(nz[-1]) + 1
        e = net.rg.edges[int(i)]
        evac_edges.append({"edge_id": e["edge_id"], "path": e["coords"], "capacity_vph": float(net.cap_vph[i]),
                           "h0": h0, "vph": [round(float(v), 1) for v in res.edge_vph[i, h0:h1]]})
    shelters = [{"id": s["id"], "open": bool(ctx.plans[plan]["open"][k]), "capacity": int(s["capacity"]),
                 "occupancy": [int(v) for v in (res.shelter_occ[k] * ctx.plans[plan]["open"][k])]}
                for k, s in enumerate(ctx.shelters)]
    hospitals = [{"id": h["id"], "beds_total": int(h["beds"]), "beds_available": [int(v) for v in free_beds[k]],
                  "grid_out_h": imp.hospital_grid_out_h[k]} for k, h in enumerate(ctx.hospitals)]
    stage = ctx.plans[plan]["stage"]
    depots = [{"id": d["id"], "staged": {c: float(stage[i, j]) for j, c in enumerate(COMMODITY_IDS)}}
              for i, d in enumerate(ctx.depots)]
    sites = ctx.shelters + ctx.hospitals
    kinds = ["shelter"] * len(ctx.shelters) + ["hospital"] * len(ctx.hospitals)
    ship = sol.ship[0]
    shipments, czml = [], [document()]
    n_truck = 0
    path_cache: dict[tuple[int, int, int], list[tuple[float, float]]] = {}
    for d in range(ship.shape[0]):
        for j in range(ship.shape[1]):
            for w in range(ship.shape[3]):
                q = ship[d, j, :, w]
                if q.sum() <= 1e-3:
                    continue
                kg = float((q * KG).sum())
                if kg < 50:
                    continue
                n_truck += 1
                truck = f"tr{n_truck:03d}"
                dist, pred = trees[w]
                key = (d, j, w)
                if key not in path_cache:
                    nodes = _path_from_source(pred[d], ctx.site_nodes[j])
                    pts = net.path_coords(nodes)
                    if ctx.depots[d]["kind"] == "state":
                        pts = [(float(ctx.depots[d]["lon"]), float(ctx.depots[d]["lat"]))] + pts
                    path_cache[key] = pts
                pts = path_cache[key]
                dep_h = w * SUPPLY_WINDOW_H + 1.0 + 0.4 * d + 0.1 * (n_truck % 5)
                arr_h = dep_h + float(dist[d, ctx.site_nodes[j]])
                for c, cid in enumerate(COMMODITY_IDS):
                    if q[c] <= 1e-3:
                        continue
                    shipments.append({
                        "id": f"sp{len(shipments) + 1:04d}", "truck_id": truck, "depot_id": ctx.depots[d]["id"],
                        "site_id": sites[j]["id"], "site_kind": kinds[j], "commodity": cid,
                        "qty": round(float(q[c]), 1), "unit": UNITS[cid], "depart_t": _t(dep_h), "arrive_t": _t(arr_h),
                        "path": pts,
                    })
                if arr_h <= HOURS:
                    pkt = mover(f"truck:{truck}", "truck", f"{truck} {ctx.depots[d]['id']} > {sites[j]['id']}",
                                along_path(pts, dep_h, arr_h), label=truck)
                    if pkt:
                        czml.append(pkt)
    unmet = []
    um = sol.unmet[0]
    for j in range(um.shape[0]):
        for c in range(um.shape[1]):
            for w in range(um.shape[2]):
                if um[j, c, w] > 0.5:
                    unmet.append({"site_id": sites[j]["id"], "window_start": _t(w * SUPPLY_WINDOW_H),
                                  "commodity": COMMODITY_IDS[c], "qty": round(float(um[j, c, w]), 1),
                                  "unit": UNITS[COMMODITY_IDS[c]]})
    sar_tasks = [{
        "id": t.id, "lon": t.lon, "lat": t.lat, "persons": int(t.persons), "priority": int(t.priority),
        "asset_type": t.asset_type, "on_barrier_island": t.island is not None, "island": t.island,
        "created_t": _t(t.created_h), "served_t": iso(hour_to_time(t.served_h)) if t.served_h is not None else None,
        "asset_id": t.asset_id, "hospital_id": t.hospital_id,
    } for t in tasks]
    sar_assets = []
    for r in routes:
        wps = [{"t": _t(float(w["t_h"])), "lon": float(w["lon"]), "lat": float(w["lat"]), "task_id": w["task_id"]}
               for w in r.waypoints]
        sar_assets.append({"id": r.id, "kind": r.kind, "name": r.name, "endurance_h": r.endurance_h, "waypoints": wps})
        samples = [(float(w["t_h"]), float(w["lon"]), float(w["lat"])) for w in r.waypoints if float(w["t_h"]) <= HOURS]
        if len(samples) >= 1:
            pkt = mover(f"asset:{r.id}", r.kind, r.name, samples, label=r.name)
            if pkt:
                czml.append(pkt)
    rescued = np.zeros(H)
    for t in tasks:
        if t.served_h is not None and t.served_h <= HOURS:
            rescued[int(np.ceil(t.served_h))] += t.persons if int(np.ceil(t.served_h)) < H else 0
    rescued_cum = np.cumsum(rescued)
    ttr = np.array([t.served_h - t.created_h for t in tasks if t.served_h is not None])
    hist = []
    if len(ttr):
        edges = np.arange(0, max(6, int(np.ceil(ttr.max() / 6.0)) * 6) + 6, 6)
        cnt, _ = np.histogram(ttr, bins=edges)
        hist = [{"bin_h": float(edges[i]), "count": float(cnt[i])} for i in range(len(cnt))]
    road_status = []
    for i in np.where(bs.blocked)[0]:
        e = net.rg.edges[int(i)]
        ro = deb.reopen_h[i]
        road_status.append({
            "edge_id": e["edge_id"], "path": e["coords"], "blocked_t": _t(blocked_h[i]),
            "reopen_t": _t(ro) if np.isfinite(ro) and ro <= HOURS else None,
            "cause": str(bs.cause[i]) or "tree", "is_critical": bool(e["is_critical"]),
            "critical_name": e["critical_name"],
        })
    crews = []
    for c in deb.crews:
        wps = [{"t": _t(float(w["t_h"])), "lon": float(w["lon"]), "lat": float(w["lat"]), "edge_id": w["edge_id"]}
               for w in c["waypoints"] if float(w["t_h"]) <= HOURS]
        crews.append({"id": c["id"], "kind": c["kind"], "waypoints": wps})
        samples = [(float(w["t_h"]), float(w["lon"]), float(w["lat"])) for w in c["waypoints"] if float(w["t_h"]) <= HOURS]
        pkt = mover(f"crew:{c['id']}", "crew", f"Crew {c['id']}", samples)
        if pkt:
            czml.append(pkt)
    kpis = {
        "persons_at_risk": metrics["persons_at_risk"], "persons_not_cleared": metrics["persons_not_cleared"],
        "unmet_supply_kg": metrics["unmet_supply_kg"], "expected_rescues": metrics["expected_rescues"],
        "clearance_margin_h": metrics["clearance_margin_h"],
    }
    end_h = (imp.landfall_h + 6 + SAR_HORIZON_H)
    plan_dict = {
        "scenario_id": int(imp.scenario_id), "advisory_time": iso(ctx.advisory), "kpis": kpis, "zones": zones,
        "evac_edges": evac_edges, "shelters": shelters, "hospitals": hospitals, "depots": depots,
        "shipments": shipments, "unmet": unmet, "sar_tasks": sar_tasks, "sar_assets": sar_assets,
        "rescued_by_hour": [int(v) for v in rescued_cum], "time_to_rescue_hist": hist,
        "median_time_to_rescue_h": float(np.median(ttr)) if len(ttr) else None,
        "unmet_tasks_72h": int(sum(1 for t in tasks if t.served_h is None or t.served_h > end_h)),
        "road_status": road_status, "debris_crews": crews,
    }
    _ = (reach, N_WINDOWS, blocked_links)
    return {"plan": plan_dict, "czml": czml}
