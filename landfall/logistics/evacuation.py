"""Simulate the evacuation: demand, departures, route assignment, and clearance.

1. Demand per zone = population x compliance, plus 15% shadow evacuation from the next zone.
2. Departures follow a logistic curve over 12 h after the release time.
3. The route assignment loads the demand in 5 increments on capacity-aware shortest paths.
4. A point queue per zone moves the vehicles through the most loaded edge of the zone.
The model works on a 1-h grid from T0 to T0 + 120 h.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from landfall.config import (
    DEPARTURE_WINDOW_H,
    HOURS,
    LOADING_ROUNDS,
    PERSONS_PER_HOUSEHOLD,
    SHADOW_EVAC,
    SHELTER_FRACTION,
    VEHICLES_PER_HOUSEHOLD,
    ZONES,
)
from landfall.logistics.network import Net

H = HOURS + 1
PERSONS_PER_VEHICLE = PERSONS_PER_HOUSEHOLD / VEHICLES_PER_HOUSEHOLD
BPR_A, BPR_B = 0.15, 4.0
SHARE_MIN = 0.10  # an edge limits a zone only if it carries 10% or more of the zone vehicles


@dataclass
class EvacInputs:
    """The static inputs of the evacuation model for one advisory."""

    bg_pop: np.ndarray  # (B,)
    bg_zone: np.ndarray  # (B,) zone letter or ""
    bg_node: np.ndarray  # (B,) node index of the origin
    exit_nodes: dict[str, int]
    shelter_ids: list[str]
    shelter_nodes: list[int]
    shelter_cap: np.ndarray  # (S,)


@dataclass
class Assignment:
    """The route assignment of one set of ordered zones."""

    share: np.ndarray  # (Z, E) fraction of the zone vehicles that use each edge
    travel_h: np.ndarray  # (Z,) mean travel time to the destination
    shelter_share: np.ndarray  # (Z, S) fraction of the zone vehicles that go to each shelter
    bg_evac_weight: np.ndarray  # (B,) persons that leave from each block group at compliance 1


@dataclass
class EvacResult:
    """The result of one evacuation simulation."""

    release_h: dict[str, float | None]
    vehicles: np.ndarray  # (Z,)
    persons: np.ndarray  # (Z,)
    cleared: np.ndarray  # (Z, H) cumulative persons cleared
    clearance_h: np.ndarray  # (Z,) NaN if the zone does not clear
    ts_h: np.ndarray  # (Z,) NaN if no TS wind
    not_cleared: np.ndarray  # (Z,) persons not cleared before TS arrival
    evac_frac: np.ndarray  # (Z,) fraction of the zone population cleared before TS arrival
    edge_vph: np.ndarray  # (E, H) vehicles per hour on each edge
    edge_ratio_max: np.ndarray  # (E,) the peak demand-to-capacity ratio
    shelter_occ: np.ndarray  # (S, H) persons in each shelter
    shelter_overflow: np.ndarray  # (S,)
    extra: dict[str, float] = field(default_factory=dict)


def departure_curve(release_h: float) -> np.ndarray:
    """Return the cumulative fraction of departures on the hour grid (logistic over 12 h)."""
    t = np.arange(H, dtype=float)
    mid = release_h + DEPARTURE_WINDOW_H / 2
    k = DEPARTURE_WINDOW_H / 8.0
    f = 1.0 / (1.0 + np.exp(-(t - mid) / k))
    f0 = 1.0 / (1.0 + np.exp(-(release_h - mid) / k))
    f1 = 1.0 / (1.0 + np.exp(-(release_h + DEPARTURE_WINDOW_H - mid) / k))
    f = np.clip((f - f0) / (f1 - f0), 0.0, 1.0)
    f[t < release_h] = 0.0
    return f


def zone_weights(inp: EvacInputs, ordered: set[str]) -> np.ndarray:
    """Return the persons that leave from each block group at compliance 1.

    A block group in an ordered zone sends all persons. A block group in the next zone
    of an ordered zone sends the shadow fraction, as a fraction of a full order.
    """
    w = np.zeros(len(inp.bg_pop))
    for i, z in enumerate(inp.bg_zone):
        if z in ordered:
            w[i] = inp.bg_pop[i]
        elif z and z in ZONES:
            k = ZONES.index(z)
            nb = {ZONES[j] for j in (k - 1, k + 1) if 0 <= j < len(ZONES)}
            if nb & ordered:
                w[i] = inp.bg_pop[i] * SHADOW_EVAC / 0.7  # the shadow rate is not scaled by compliance
    return w


def assign(net: Net, inp: EvacInputs, ordered: set[str], compliance: float = 0.7) -> Assignment:
    """Assign the evacuation demand of the ordered zones to routes (incremental loading)."""
    zi = {z: i for i, z in enumerate(ZONES)}
    nz, ne, ns = len(ZONES), len(net.eu), len(inp.shelter_ids)
    w = zone_weights(inp, ordered)
    persons = w * compliance
    veh = persons / PERSONS_PER_VEHICLE
    # Destinations: the nearest shelter with space for the shelter share, the nearest exit for the rest.
    exits = list(inp.exit_nodes.values())
    dest_nodes = exits + inp.shelter_nodes
    from scipy.sparse.csgraph import dijkstra

    rev = net.matrix(net.tt_h, reverse=True)
    dist_to = dijkstra(rev, directed=True, indices=dest_nodes)  # (D, N) time from node to dest
    od: dict[int, np.ndarray] = {d: np.zeros((net.n_nodes, nz)) for d in range(len(dest_nodes))}
    shelter_left = inp.shelter_cap.astype(float).copy()
    shelter_share = np.zeros((nz, ns))
    zone_veh = np.zeros(nz)
    order = np.argsort([ZONES.index(z) if z in zi else 9 for z in inp.bg_zone])
    for i in order:
        if veh[i] <= 0:
            continue
        z = inp.bg_zone[i]
        zk = zi.get(z)
        if zk is None:
            continue
        o = inp.bg_node[i]
        zone_veh[zk] += veh[i]
        ex = int(np.argmin(dist_to[: len(exits), o]))
        od[ex][o, zk] += veh[i] * (1 - SHELTER_FRACTION)
        need = persons[i] * SHELTER_FRACTION
        cand = np.argsort(dist_to[len(exits):, o])
        for s in cand:
            if need <= 0:
                break
            if not np.isfinite(dist_to[len(exits) + s, o]):
                continue
            take = min(need, shelter_left[s])
            if take <= 0:
                continue
            shelter_left[s] -= take
            need -= take
            od[len(exits) + s][o, zk] += take / PERSONS_PER_VEHICLE
            shelter_share[zk, s] += take / PERSONS_PER_VEHICLE
        if need > 0:  # no shelter space: these persons also leave the county
            od[ex][o, zk] += need / PERSONS_PER_VEHICLE
    load = np.zeros(ne)
    zone_edge = np.zeros((nz, ne))
    zone_time = np.zeros(nz)
    for _ in range(LOADING_ROUNDS):
        cost = net.tt_h * (1 + BPR_A * (load / (net.cap_vph * DEPARTURE_WINDOW_H)) ** BPR_B)
        for d, node in enumerate(dest_nodes):
            dem = od[d] / LOADING_ROUNDS
            if dem.sum() <= 0:
                continue
            dist, pred = net.tree_to(node, cost)
            flows = _accumulate_multi(pred, dist, dem, net)
            zone_edge += flows.T
            load += flows.sum(axis=1)
            fin = np.isfinite(dist)
            zone_time += (dem[fin] * dist[fin, None]).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        share = np.where(zone_veh[:, None] > 0, zone_edge / zone_veh[:, None], 0.0)
        travel = np.where(zone_veh > 0, zone_time / zone_veh, 0.0)
        sh = np.where(zone_veh[:, None] > 0, shelter_share / zone_veh[:, None], 0.0)
    return Assignment(share, travel, sh, w)


def _accumulate_multi(pred: np.ndarray, dist: np.ndarray, demand: np.ndarray, net: Net) -> np.ndarray:
    """Return edge flows (E, Z) when every node sends its demand row along the tree."""
    flow_node = demand.copy()
    out = np.zeros((len(net.eu), demand.shape[1]))
    finite = np.isfinite(dist)
    order = np.argsort(-np.where(finite, dist, -1.0))
    active = flow_node.sum(axis=1) > 0
    for n in order:
        if not finite[n] or not active[n]:
            continue
        p = pred[n]
        if p < 0:
            continue
        out[net.edge_of(int(n), int(p))] += flow_node[n]
        flow_node[p] += flow_node[n]
        active[p] = True
    return out


def simulate(net: Net, inp: EvacInputs, asg: Assignment, release_h: dict[str, float | None],
             compliance: float, ts_h: np.ndarray) -> EvacResult:
    """Run the point-queue simulation for one release plan and one compliance value."""
    nz = len(ZONES)
    zone_pop = np.array([inp.bg_pop[inp.bg_zone == z].sum() for z in ZONES])
    persons_bg = asg.bg_evac_weight * compliance
    zone_of = {z: i for i, z in enumerate(ZONES)}
    persons = np.zeros(nz)
    for i, z in enumerate(inp.bg_zone):
        if z in zone_of:
            persons[zone_of[z]] += persons_bg[i]
    vehicles = persons / PERSONS_PER_VEHICLE
    # Shadow evacuees leave with the next ordered zone.
    rel = np.full(nz, np.nan)
    for z, r in release_h.items():
        if r is not None:
            rel[zone_of[z]] = r
    for k in range(nz):
        if np.isnan(rel[k]) and persons[k] > 0:
            nb = [rel[j] for j in (k - 1, k + 1) if 0 <= j < nz and not np.isnan(rel[j])]
            rel[k] = min(nb) if nb else np.nan
    arrivals = np.zeros((nz, H))
    for k in range(nz):
        if np.isnan(rel[k]) or vehicles[k] <= 0:
            continue
        f = departure_curve(rel[k])
        arrivals[k] = np.diff(np.concatenate([[0.0], f])) * vehicles[k]
    key = asg.share > SHARE_MIN  # (Z, E) the edges that each zone uses
    used = key.any(axis=0)
    share_u = asg.share[:, used]
    cap_u = net.cap_vph[used]
    key_u = key[:, used]
    q = np.zeros(nz)
    served = np.zeros((nz, H))
    ratio_max = np.zeros(used.sum())
    for h in range(H):
        want = q + arrivals[:, h]
        load = want @ share_u  # (E_used,)
        ratio = load / cap_u
        ratio_max = np.maximum(ratio_max, ratio)
        rz = np.array([ratio[key_u[k]].max() if key_u[k].any() else 0.0 for k in range(nz)])
        s = want / np.maximum(1.0, rz)
        served[:, h] = s
        q = want - s
    vph_used = served.T @ share_u  # (H, E_used)
    edge_vph = np.zeros((len(net.eu), H), dtype=np.float32)
    edge_vph[used] = vph_used.T
    ratio_all = np.zeros(len(net.eu))
    ratio_all[used] = ratio_max
    # Cleared = served plus the mean travel time to the destination.
    cleared_veh = np.zeros((nz, H))
    for k in range(nz):
        shift = int(round(asg.travel_h[k]))
        c = np.cumsum(served[k])
        cleared_veh[k, shift:] = c[: H - shift] if shift < H else 0.0
    cleared = cleared_veh * PERSONS_PER_VEHICLE
    clearance = np.full(nz, np.nan)
    not_cleared = np.zeros(nz)
    evac_frac = np.zeros(nz)
    for k in range(nz):
        if persons[k] <= 0:
            continue
        done = np.where(cleared[k] >= 0.99 * persons[k])[0]
        clearance[k] = float(done[0]) if len(done) else np.nan
        if np.isfinite(ts_h[k]):
            t = int(np.clip(ts_h[k], 0, H - 1))
            not_cleared[k] = max(0.0, persons[k] - cleared[k, t])
            evac_frac[k] = cleared[k, t] / max(zone_pop[k], 1.0)
        else:
            evac_frac[k] = cleared[k, -1] / max(zone_pop[k], 1.0)
    occ = np.zeros((len(inp.shelter_ids), H))
    for k in range(nz):
        occ += asg.shelter_share[k][:, None] * cleared_veh[k][None, :] * PERSONS_PER_VEHICLE
    overflow = np.maximum(0.0, occ[:, -1] - inp.shelter_cap)
    occ = np.minimum(occ, inp.shelter_cap[:, None])
    return EvacResult(
        release_h=dict(release_h), vehicles=vehicles, persons=persons, cleared=cleared,
        clearance_h=clearance, ts_h=ts_h, not_cleared=not_cleared, evac_frac=evac_frac,
        edge_vph=edge_vph, edge_ratio_max=ratio_all, shelter_occ=occ, shelter_overflow=overflow,
    )
