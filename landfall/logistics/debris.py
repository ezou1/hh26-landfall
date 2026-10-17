"""Schedule the debris crews that clear the blocked edges.

The priority of a task is betweenness x (1 + hospital access weight + shelter access weight).
8 county crews and 4 state crews start after the storm. A crew clears one edge in
max(1 h, 0.5 h per 100 m). A bridge repair or a washed-out critical link takes 30 days.
The plan shows these tasks but does not schedule them. The greedy schedule picks the
task with the best priority per hour of travel and work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from landfall.config import (
    CLEAR_H_PER_100M,
    CLEAR_MIN_H,
    CREW_SPEED_KMH,
    CREWS_COUNTY,
    CREWS_STATE,
    HOURS,
)
from landfall.geoutil import haversine_km
from landfall.logistics.network import Net, accumulate_tree


@dataclass
class EdgeWeights:
    """The static edge weights for the debris priority and the infrastructure insight."""

    betweenness: np.ndarray  # (E,) normalised to max 1
    hospital_access: np.ndarray  # (E,) normalised to max 1
    shelter_access: np.ndarray  # (E,)
    population_served: np.ndarray  # (E,) persons whose route to a hospital or shelter uses the edge


def edge_weights(net: Net, bg_nodes: np.ndarray, bg_pop: np.ndarray, hospital_nodes: list[int],
                 shelter_nodes: list[int], n_samples: int = 120, seed: int = 0) -> EdgeWeights:
    """Return the sampled edge betweenness and the access weights."""
    rng = np.random.default_rng(seed)
    bt = np.zeros(len(net.eu))
    targets = rng.choice(net.n_nodes, size=min(n_samples, net.n_nodes), replace=False)
    ones = np.ones(net.n_nodes)
    for t in targets:
        dist, pred = net.tree_to(int(t), net.tt_h)
        bt += accumulate_tree(pred, dist, ones, net)
    demand = np.zeros(net.n_nodes)
    np.add.at(demand, bg_nodes, bg_pop)

    def access(nodes: list[int]) -> np.ndarray:
        acc = np.zeros(len(net.eu))
        for n in nodes:
            dist, pred = net.tree_to(int(n), net.tt_h)
            acc += accumulate_tree(pred, dist, demand, net)
        return acc

    hosp = access(hospital_nodes)
    shel = access(shelter_nodes)
    norm = lambda a: a / max(float(a.max()), 1e-9)  # noqa: E731
    return EdgeWeights(norm(bt), norm(hosp), norm(shel), hosp + shel)


@dataclass
class DebrisResult:
    """The crew schedule and the reopen hour of every blocked edge."""

    reopen_h: np.ndarray  # (E,) NaN if the edge stays closed in the horizon
    repair: np.ndarray  # (E,) bool, a 30-day repair task
    crews: list[dict[str, object]] = field(default_factory=list)


def schedule(net: Net, blocked: np.ndarray, blocked_h: np.ndarray, repair: np.ndarray, start_h: float,
             weights: EdgeWeights, crew_bases: list[tuple[float, float]]) -> DebrisResult:
    """Run the greedy crew schedule. Return the reopen hour of each edge and the crew routes."""
    reopen = np.full(len(net.eu), np.nan)
    tasks = [int(i) for i in np.where(blocked & ~repair)[0]]
    prio = weights.betweenness * (1 + weights.hospital_access + weights.shelter_access)
    mids = np.array([net.rg.edges[i]["mid"] for i in range(len(net.eu))])
    crews = []
    kinds = ["county"] * CREWS_COUNTY + ["state"] * CREWS_STATE
    for k, kind in enumerate(kinds):
        lon, lat = crew_bases[k % len(crew_bases)]
        crews.append({"id": f"c{k + 1:02d}", "kind": kind, "t": start_h, "lon": lon, "lat": lat,
                      "waypoints": [{"t_h": start_h, "lon": lon, "lat": lat, "edge_id": None}]})
    remaining = set(tasks)
    horizon = float(HOURS)
    while remaining:
        crew = min(crews, key=lambda c: c["t"])
        if crew["t"] >= horizon:
            break
        cand = np.array(sorted(remaining))
        d_km = haversine_km(crew["lat"], crew["lon"], mids[cand, 1], mids[cand, 0])
        travel = d_km / CREW_SPEED_KMH
        work = np.maximum(CLEAR_MIN_H, CLEAR_H_PER_100M * net.length_m[cand] / 100.0)
        ready = np.maximum(crew["t"] + travel, blocked_h[cand])
        score = (prio[cand] + 1e-4) / (ready - crew["t"] + work)
        best = int(np.argmax(score))
        e = int(cand[best])
        t_arr = float(ready[best])
        t_done = t_arr + float(work[best])
        remaining.discard(e)
        reopen[e] = t_done
        crew["waypoints"].append({"t_h": t_arr, "lon": float(mids[e, 0]), "lat": float(mids[e, 1]),
                                  "edge_id": net.rg.edges[e]["edge_id"]})
        crew["waypoints"].append({"t_h": t_done, "lon": float(mids[e, 0]), "lat": float(mids[e, 1]),
                                  "edge_id": net.rg.edges[e]["edge_id"]})
        crew["t"], crew["lon"], crew["lat"] = t_done, float(mids[e, 0]), float(mids[e, 1])
    return DebrisResult(reopen, repair, crews)


def closed_at(blocked: np.ndarray, blocked_h: np.ndarray, reopen_h: np.ndarray, h: float) -> np.ndarray:
    """Return the edges that are closed at hour h."""
    return blocked & (blocked_h <= h) & ~(np.isfinite(reopen_h) & (reopen_h <= h))
