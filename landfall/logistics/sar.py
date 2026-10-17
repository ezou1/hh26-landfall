"""Make rescue tasks and route the SAR assets with an OR-Tools VRP with time windows.

Each block group sends rescue requests from the damage model. A task holds up to the
capacity of its asset type. It is at a random flooded cell of the block group.
The asset type of a task is:

- "helo" if the task is on a barrier island with all links blocked.
- "helo" if it has priority 1 and a ground ETA of more than 45 min.
- "boat" if the depth is more than 1 m.
- "high_water_truck" if the depth is 0.3 m to 1 m.

The routing starts at landfall + 6 h.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from landfall.config import (
    HELO_GROUND_ETA_LIMIT_MIN,
    ISLANDS,
    SAR_HORIZON_H,
    SAR_MAX_TASKS,
    SAR_SERVICE_MIN,
)
from landfall.geoutil import haversine_km

DETOUR_WATER = 1.3
PENALTY = {1: 2_000_000, 2: 600_000, 3: 200_000}


@dataclass
class Task:
    """One rescue task."""

    id: str
    lon: float
    lat: float
    persons: int
    priority: int
    depth_m: float
    asset_type: str
    island: str | None
    created_h: float
    node: int = -1
    served_h: float | None = None
    asset_id: str | None = None
    hospital_id: str | None = None
    medevac_persons: int = 0


@dataclass
class AssetRoute:
    """The timed waypoints of one asset."""

    id: str
    kind: str
    name: str
    endurance_h: float
    waypoints: list[dict[str, object]] = field(default_factory=list)


def island_of(lon: float, lat: float) -> str | None:
    """Return the barrier island that contains a point, or None."""
    for name, info in ISLANDS.items():
        w, s, e, n = info["bbox"]
        if w <= lon <= e and s <= lat <= n:
            return name
    return None


def make_tasks(rng: np.random.Generator, rescue_persons: np.ndarray, bg_cells: list[np.ndarray],
               grid_lon: np.ndarray, grid_lat: np.ndarray, depth: np.ndarray, t_clear_h: np.ndarray,
               earliest_h: float) -> list[Task]:
    """Sample rescue tasks from the expected rescue requests of each block group."""
    raw: list[tuple[float, float, int, float, float]] = []
    for b, mean in enumerate(rescue_persons):
        if mean <= 0.05:
            continue
        n = rng.poisson(mean)
        cells = bg_cells[b]
        if n <= 0 or len(cells) == 0:
            continue
        wet = cells[depth.ravel()[cells] > 0.3]
        pool = wet if len(wet) else cells
        while n > 0:
            persons = int(min(n, rng.integers(2, 9)))
            n -= persons
            cell = int(pool[rng.integers(0, len(pool))])
            r, c = divmod(cell, len(grid_lon))
            lon = float(grid_lon[c] + rng.uniform(-0.002, 0.002))
            lat = float(grid_lat[r] + rng.uniform(-0.002, 0.002))
            created = max(earliest_h, float(t_clear_h[r, c]) + 1.0) + float(rng.uniform(0, 3))
            raw.append((lon, lat, persons, float(depth[r, c]), created))
    # Merge tasks if there are too many for the VRP: keep the location, add the persons.
    if len(raw) > SAR_MAX_TASKS:
        order = rng.permutation(len(raw))
        keep = [raw[i] for i in order[:SAR_MAX_TASKS]]
        extra = sum(raw[i][2] for i in order[SAR_MAX_TASKS:])
        scale = 1.0 + extra / max(1, sum(k[2] for k in keep))
        raw = [(a, b, max(1, int(round(p * scale))), d, t) for a, b, p, d, t in keep]
    tasks = []
    for i, (lon, lat, persons, d, created) in enumerate(raw):
        u = rng.random()
        p1 = 0.10 + (0.20 if d > 2.0 else 0.0)
        prio = 1 if u < p1 else (2 if u < p1 + 0.45 else 3)
        kind = "boat" if d > 1.0 else "high_water_truck"
        tasks.append(Task(f"t{i:04d}", lon, lat, persons, prio, d, kind, island_of(lon, lat), created))
    return tasks


def solve_vrptw(time_min: np.ndarray, starts: list[int], ends: list[int],
                vehicle_windows: list[tuple[int, int]], task_nodes: list[int],
                task_windows: list[tuple[int, int]], service_min: list[int], penalties: list[int],
                soft_late: list[tuple[int, int]] | None = None,
                time_limit_s: float = 2.0) -> list[list[tuple[int, int]]]:
    """Solve a VRP with time windows and optional tasks.

    Returns, for each vehicle, the list of (node, arrival minute) of the visited task nodes.
    """
    n_nodes = time_min.shape[0]
    n_veh = len(starts)
    mgr = pywrapcp.RoutingIndexManager(n_nodes, n_veh, starts, ends)
    routing = pywrapcp.RoutingModel(mgr)
    service = np.zeros(n_nodes, dtype=np.int64)
    for node, s in zip(task_nodes, service_min, strict=True):
        service[node] = s
    tm = time_min.astype(np.int64)

    def transit(i: int, j: int) -> int:
        a, b = mgr.IndexToNode(i), mgr.IndexToNode(j)
        return int(tm[a, b] + service[a])

    cb = routing.RegisterTransitCallback(transit)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    horizon = int(max(w[1] for w in vehicle_windows) + 60)
    routing.AddDimension(cb, horizon, horizon, False, "Time")
    td = routing.GetDimensionOrDie("Time")
    for node, (a, b), pen in zip(task_nodes, task_windows, penalties, strict=True):
        idx = mgr.NodeToIndex(node)
        td.CumulVar(idx).SetRange(int(a), int(max(a, b)))
        routing.AddDisjunction([idx], int(pen))
    for v, (a, b) in enumerate(vehicle_windows):
        td.CumulVar(routing.Start(v)).SetRange(int(a), int(a))
        td.CumulVar(routing.End(v)).SetRange(int(a), int(b))
    if soft_late:
        for node, late in soft_late:
            td.SetCumulVarSoftUpperBound(mgr.NodeToIndex(node), int(late), 20)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    sol = routing.SolveWithParameters(params)
    out: list[list[tuple[int, int]]] = [[] for _ in range(n_veh)]
    if sol is None:
        return out
    for v in range(n_veh):
        idx = sol.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            out[v].append((node, int(sol.Value(td.CumulVar(idx)))))
            idx = sol.Value(routing.NextVar(idx))
    return out


@dataclass
class SarInputs:
    """The assets and the travel tools for one SAR solve."""

    assets: list[dict[str, object]]
    start_h: float
    truck_time_h: callable  # (lon_lat_list) -> matrix of hours on the blocked road graph
    helipads: list[tuple[str, float, float]]  # hospital id, lat, lon


def assign_helo(tasks: list[Task], blocked_links: set[str], ground_eta_min: np.ndarray) -> None:
    """Set the asset type to "helo" for island tasks that are cut off and for slow priority-1 tasks."""
    for t, eta in zip(tasks, ground_eta_min, strict=True):
        cut_off = t.island is not None and all(lk in blocked_links for lk in ISLANDS[t.island]["links"])
        if cut_off or (t.priority == 1 and eta > HELO_GROUND_ETA_LIMIT_MIN):
            t.asset_type = "helo"


def route_class(kind: str, tasks: list[Task], assets: list[dict[str, object]], start_h: float,
                time_h: np.ndarray, helipad_extra_min: np.ndarray | None, time_limit_s: float) -> list[AssetRoute]:
    """Route one asset class. time_h is the matrix over [bases..., tasks...] in hours."""
    nb = len(assets)
    routes = [AssetRoute(str(a["id"]), kind, str(a["name"]), float(a["endurance_h"])) for a in assets]
    if not tasks:
        for r, a in zip(routes, assets, strict=True):
            r.waypoints = [{"t_h": start_h, "lon": a["base_lon"], "lat": a["base_lat"], "task_id": None}]
        return routes
    horizon_min = int(SAR_HORIZON_H * 60)
    t0 = start_h
    if kind == "helo":
        # Each helicopter flies sorties of one endurance, with 1 h on the ground between them.
        veh_assets, windows = [], []
        for i, a in enumerate(assets):
            end = float(a["endurance_h"])
            k = 0
            while k * (end + 1.0) < SAR_HORIZON_H:
                s = int(k * (end + 1.0) * 60)
                windows.append((s, min(horizon_min, s + int(end * 60))))
                veh_assets.append(i)
                k += 1
    else:
        veh_assets = list(range(nb))
        windows = [(0, horizon_min) for _ in range(nb)]
    n_tasks = len(tasks)
    tm = np.round(np.nan_to_num(time_h * 60.0, nan=1e6, posinf=1e6)).astype(np.int64)
    tm = np.minimum(tm, 10**6)
    starts = [veh_assets[v] for v in range(len(veh_assets))]
    task_nodes = list(range(nb, nb + n_tasks))
    tw = [(max(0, int((t.created_h - t0) * 60)), horizon_min) for t in tasks]
    service = []
    for i in range(n_tasks):
        s = SAR_SERVICE_MIN[kind]
        if kind == "helo" and helipad_extra_min is not None:
            s += int(helipad_extra_min[i])
        service.append(int(s))
    pens = [PENALTY[t.priority] for t in tasks]
    soft = [(nb + i, tw[i][0] + 120) for i in range(n_tasks) if tasks[i].priority == 1]
    sol = solve_vrptw(tm, starts, starts, windows, task_nodes, tw, service, pens, soft, time_limit_s)
    for v, visits in enumerate(sol):
        a = assets[veh_assets[v]]
        r = routes[veh_assets[v]]
        if not r.waypoints:
            r.waypoints.append({"t_h": t0, "lon": a["base_lon"], "lat": a["base_lat"], "task_id": None})
        if not visits:
            continue
        r.waypoints.append({"t_h": t0 + windows[v][0] / 60.0, "lon": a["base_lon"], "lat": a["base_lat"], "task_id": None})
        last_node, last_t = veh_assets[v], windows[v][0]
        for node, arr in visits:
            t = tasks[node - nb]
            t.served_h = t0 + arr / 60.0
            t.asset_id = str(a["id"])
            r.waypoints.append({"t_h": t.served_h, "lon": t.lon, "lat": t.lat, "task_id": t.id})
            r.waypoints.append({"t_h": t.served_h + service[node - nb] / 60.0, "lon": t.lon, "lat": t.lat,
                                "task_id": t.id})
            last_node, last_t = node, arr + service[node - nb]
        back = last_t + int(tm[last_node, veh_assets[v]])
        r.waypoints.append({"t_h": t0 + back / 60.0, "lon": a["base_lon"], "lat": a["base_lat"], "task_id": None})
    for r, a in zip(routes, assets, strict=True):
        if not r.waypoints:
            r.waypoints = [{"t_h": t0, "lon": a["base_lon"], "lat": a["base_lat"], "task_id": None}]
    return routes


def straight_time_h(lonlat: list[tuple[float, float]], speed_kmh: float, detour: float = 1.0) -> np.ndarray:
    """Return a straight-line travel-time matrix in hours."""
    a = np.array(lonlat)
    d = haversine_km(a[:, 1][:, None], a[:, 0][:, None], a[:, 1][None, :], a[:, 0][None, :])
    return d * detour / speed_kmh


def run_sar(tasks: list[Task], assets: list[dict[str, object]], start_h: float,
            road_time_h: callable, blocked_links: set[str], helipads: list[tuple[str, float, float]],
            time_limit_s: float = 2.0) -> list[AssetRoute]:
    """Assign asset types, route every asset class, and return the asset routes."""
    by_kind: dict[str, list[dict[str, object]]] = {"helo": [], "boat": [], "high_water_truck": []}
    for a in assets:
        by_kind[str(a["kind"])].append(a)
    # Ground ETA in minutes: the nearest boat by water, or the nearest truck by road.
    eta = np.full(len(tasks), np.inf)
    if tasks:
        boat_pts = [(float(a["base_lon"]), float(a["base_lat"])) for a in by_kind["boat"]]
        truck_pts = [(float(a["base_lon"]), float(a["base_lat"])) for a in by_kind["high_water_truck"]]
        t_pts = [(t.lon, t.lat) for t in tasks]
        if boat_pts:
            m = straight_time_h(boat_pts + t_pts, float(by_kind["boat"][0]["speed_kmh"]), DETOUR_WATER)
            eta_b = m[: len(boat_pts), len(boat_pts):].min(axis=0) * 60
        else:
            eta_b = np.full(len(tasks), np.inf)
        if truck_pts:
            m = road_time_h(truck_pts + t_pts)
            eta_t = m[: len(truck_pts), len(truck_pts):].min(axis=0) * 60
        else:
            eta_t = np.full(len(tasks), np.inf)
        eta = np.where([t.asset_type == "boat" for t in tasks], eta_b, eta_t)
        # A truck task that no truck can reach goes to a boat.
        for i, t in enumerate(tasks):
            if t.asset_type == "high_water_truck" and not np.isfinite(eta_t[i]):
                t.asset_type = "boat"
                eta[i] = eta_b[i]
    assign_helo(tasks, blocked_links, eta)
    routes: list[AssetRoute] = []
    for kind in ("helo", "boat", "high_water_truck"):
        ks = [t for t in tasks if t.asset_type == kind]
        al = by_kind[kind]
        if not al:
            continue
        pts = [(float(a["base_lon"]), float(a["base_lat"])) for a in al] + [(t.lon, t.lat) for t in ks]
        extra = None
        if kind == "helo":
            m = straight_time_h(pts, float(al[0]["speed_kmh"]))
            if helipads and ks:
                hp = np.array([[h[2], h[1]] for h in helipads])
                dk = haversine_km(np.array([t.lat for t in ks])[:, None], np.array([t.lon for t in ks])[:, None],
                                  hp[:, 1][None, :], hp[:, 0][None, :]).min(axis=1)
                extra = 2 * dk / float(al[0]["speed_kmh"]) * 60
        elif kind == "boat":
            m = straight_time_h(pts, float(al[0]["speed_kmh"]), DETOUR_WATER)
        else:
            m = road_time_h(pts)
        routes += route_class(kind, ks, al, start_h, m, extra, time_limit_s)
    return routes
