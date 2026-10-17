"""Test the sampler, the wind profile, the evacuation, the supply LP, and the SAR VRP."""

from __future__ import annotations

import numpy as np
import pytest

from landfall.impact.wind import holland, holland_gradient, rmax_km

# ------------------------------------------------------------------ sampler


def _toy_predictor():
    import torch

    from landfall.predict.features import state_columns
    from landfall.predict.model import Predictor, StepMLP

    torch.manual_seed(0)
    n_in = len(state_columns()) + 2
    net = StepMLP(n_in)
    rng = np.random.default_rng(0)
    res = rng.normal(0, 0.2, size=(50, 20, 3)).astype(np.float32)
    return Predictor(net, np.zeros(n_in, np.float32), np.ones(n_in, np.float32),
                     np.array([0.3, -0.2, 0.0], np.float32), np.array([0.1, 0.1, 2.0], np.float32),
                     residuals=res, residual_lat=np.full((50, 20), 22.0, np.float32))


def _history():
    from landfall.predict.sample import History

    lat = np.array([[18.0, 18.5, 19.0, 19.5, 20.0]])
    lon = np.array([[-80.0, -80.3, -80.6, -80.9, -81.2]])
    v = np.array([[60.0, 65, 70, 75, 80]])
    p = np.array([[990.0, 985, 980, 975, 970]])
    return History(lat, lon, v, p, np.array([462000.0]), np.array([461900.0]))


def test_sampler_is_deterministic_with_a_seed() -> None:
    from landfall.predict.sample import rollout

    pred = _toy_predictor()
    h = _history().repeat(64)
    a = rollout(pred, h, 8, rng=np.random.default_rng(42))
    b = rollout(pred, h, 8, rng=np.random.default_rng(42))
    c = rollout(pred, h, 8, rng=np.random.default_rng(43))
    assert np.array_equal(np.nan_to_num(a.lat), np.nan_to_num(b.lat))
    assert np.array_equal(np.nan_to_num(a.v), np.nan_to_num(b.v))
    assert not np.array_equal(np.nan_to_num(a.lat), np.nan_to_num(c.lat))
    assert np.nanstd(a.lat[:, -1]) > np.nanstd(a.lat[:, 1])  # spread grows with lead time


def test_vmax_is_clipped() -> None:
    from landfall.predict.sample import rollout

    pred = _toy_predictor()
    pred.y_mean = np.array([0.0, 0.0, 60.0], np.float32)  # a huge intensification each step
    ro = rollout(pred, _history().repeat(4), 6, rng=np.random.default_rng(0))
    assert np.nanmax(ro.v) <= 165.0 and np.nanmin(ro.v) >= 15.0


# ------------------------------------------------------------------ wind


@pytest.mark.parametrize("vmax", [50.0, 90.0, 130.0])
def test_wind_profile_at_rmax_equals_vmax(vmax: float) -> None:
    rm = float(rmax_km(vmax))
    assert holland(np.array([rm]), vmax, rm)[0] == pytest.approx(vmax, rel=1e-9)
    assert holland_gradient(np.array([rm]), vmax, rm, 26.0)[0] == pytest.approx(vmax, rel=1e-9)
    r = np.array([rm * 0.5, rm * 2, rm * 4])
    assert np.all(holland(r, vmax, rm) < vmax)
    assert np.all(holland_gradient(r[1:], vmax, rm, 26.0) < holland(r[1:], vmax, rm))


def test_rmax_rule() -> None:
    assert float(rmax_km(96)) == 35.0 and float(rmax_km(95)) == 50.0


# ------------------------------------------------------------------ evacuation


def _toy_net(lanes: float = 1.0):
    import networkx as nx

    from landfall.ingest.osm import RoadGraph
    from landfall.logistics.network import build_net

    xy = {0: (-81.90, 26.50), 1: (-81.85, 26.50), 2: (-81.80, 26.50)}
    edges = []
    for u, v in ((0, 1), (1, 2), (1, 0), (2, 1)):
        edges.append({"u": u, "v": v, "k": 0, "edge_id": f"{u}-{v}-0", "name": "Toy", "ref": "", "highway": "primary",
                      "lanes": lanes, "speed_kph": 50.0, "length_m": 5000.0, "tt_h": 0.1, "bridge": False,
                      "is_critical": False, "critical_name": None, "coords": [xy[u], xy[v]],
                      "mid": ((xy[u][0] + xy[v][0]) / 2, 26.5), "display": True})
    rg = RoadGraph(nx.MultiDiGraph(), xy, edges, {"I-75 N": 2})
    return build_net(rg)


def _evac(lanes: float, ts_h: float, persons: float = 10000.0):
    from landfall.logistics import evacuation as ev

    net = _toy_net(lanes)
    inp = ev.EvacInputs(np.array([persons]), np.array(["A"], dtype=object), np.array([0]), {"I-75 N": 2},
                        [], [], np.zeros(0))
    asg = ev.assign(net, inp, {"A"}, compliance=1.0)
    ts = np.array([ts_h, np.nan, np.nan, np.nan, np.nan])
    return ev.simulate(net, inp, asg, {"A": 0.0, "B": None, "C": None, "D": None, "E": None}, 1.0, ts), asg


def test_evacuation_clearance_on_three_node_graph() -> None:
    res, asg = _evac(lanes=4.0, ts_h=48.0)
    assert asg.share[0].max() == pytest.approx(1.0)  # every vehicle uses the two edges to the exit
    assert asg.travel_h[0] == pytest.approx(0.2, abs=0.05)
    # Uncongested: the clearance follows the 12-h departure curve.
    assert 10 <= res.clearance_h[0] <= 13
    assert res.not_cleared[0] == pytest.approx(0.0, abs=1.0)


def test_evacuation_capacity_delays_clearance() -> None:
    fast, _ = _evac(lanes=4.0, ts_h=48.0)
    slow, _ = _evac(lanes=0.5, ts_h=8.0, persons=30000.0)  # 630 veh/h for 16250 vehicles
    assert slow.clearance_h[0] > fast.clearance_h[0] + 2
    assert slow.not_cleared[0] > 1000
    assert slow.edge_ratio_max.max() > 1.0


# ------------------------------------------------------------------ supply LP


def test_supply_lp_feasible_on_toy_instance() -> None:
    from landfall.logistics.supply import SupplyScenario, solve

    kg = np.array([1.0, 0.5])
    inv = np.array([[1000.0, 1000.0], [200.0, 0.0]])  # depot x commodity
    trucks = np.array([2.0, 1.0])
    demand = np.zeros((2, 2, 3))
    demand[0, 0, 1] = 300  # site 0 needs 300 units of commodity 0 in window 1
    demand[1, 1, 2] = 100
    reach = np.ones((2, 2, 3), bool)
    reach[:, :, 1] = False  # the storm closes the roads in window 1
    travel = np.full((2, 2, 3), 1.0)
    dist = np.array([[10.0, 20.0], [5.0, 30.0]])
    sc = SupplyScenario(1.0, demand, reach, travel, dist)
    sol = solve([sc], inv, trucks, kg, ["county", "retail"])
    assert sol.status.lower().startswith("optimization terminated")
    assert sol.unmet[0].sum() == pytest.approx(0.0, abs=1e-6)  # the window-0 delivery covers window 1
    assert sol.ship[0][:, :, :, 1].sum() == pytest.approx(0.0)
    assert np.all(sol.stage <= inv + 1e-9)
    # Fixed staging that is too small gives unmet demand.
    fixed = solve([sc], inv, trucks, kg, ["county", "retail"], fixed_stage=np.zeros_like(inv))
    assert fixed.unmet[0].sum() == pytest.approx(400.0)


# ------------------------------------------------------------------ SAR


def test_sar_assignment_five_tasks_two_assets() -> None:
    from landfall.logistics.sar import Task, run_sar, straight_time_h

    assets = [
        {"id": "b01", "kind": "boat", "name": "Boat 1", "base_lat": 26.50, "base_lon": -81.95, "speed_kmh": 30.0,
         "capacity_persons": 8, "endurance_h": 10.0},
        {"id": "b02", "kind": "boat", "name": "Boat 2", "base_lat": 26.60, "base_lon": -81.90, "speed_kmh": 30.0,
         "capacity_persons": 8, "endurance_h": 10.0},
    ]
    tasks = [Task(f"t{i}", -81.95 + 0.01 * i, 26.52 + 0.01 * i, 4, 1 + i % 3, 1.5, "boat", None, 10.0 + i)
             for i in range(5)]

    def road(points: list[tuple[float, float]]) -> np.ndarray:
        return straight_time_h(points, 40.0)

    routes = run_sar(tasks, assets, 10.0, road, set(), [], time_limit_s=1.0)
    assert all(t.served_h is not None for t in tasks)
    assert {t.asset_id for t in tasks} <= {"b01", "b02"}
    assert all(t.served_h >= t.created_h - 1e-6 for t in tasks)
    visited = [w["task_id"] for r in routes for w in r.waypoints if w["task_id"]]
    assert sorted(set(visited)) == sorted(t.id for t in tasks)


def test_island_task_goes_to_helo_when_links_blocked() -> None:
    from landfall.logistics.sar import Task, assign_helo

    t = Task("t0", -82.10, 26.45, 3, 2, 1.5, "boat", "Sanibel", 10.0)
    assign_helo([t], {"Sanibel Causeway"}, np.array([10.0]))
    assert t.asset_type == "helo"
    t2 = Task("t1", -81.90, 26.60, 3, 1, 1.5, "boat", None, 10.0)
    assign_helo([t2], set(), np.array([60.0]))
    assert t2.asset_type == "helo"  # priority 1 with a ground ETA of more than 45 min
