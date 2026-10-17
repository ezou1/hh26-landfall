"""Compute the probability that each road edge is blocked, and sample blocked sets.

The formulas are:

- p_blocked = 1 - (1 - p_tree) * (1 - p_flood) * (1 - p_bridge).
- p_tree = sigmoid(c * (gust - 80 mph)) * tree_cover_proxy.
- p_flood = 1 if the surge depth is more than 0.3 m.
- p_bridge = 0.5 for a bridge with a gust of more than 120 mph.

The tree-cover proxy depends on the road class. The repository has no land-cover data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from landfall.config import (
    BRIDGE_BLOCK_GUST_MPH,
    BRIDGE_BLOCK_P,
    FLOOD_BLOCK_DEPTH_M,
    KT_TO_MPH,
    TREE_GUST_MID_MPH,
    TREE_SIGMOID_C,
)
from landfall.impact.damage import sigmoid
from landfall.ingest.geo import CountyGrid
from landfall.ingest.osm import RoadGraph

TREE_COVER_PROXY = {
    "motorway": 0.02, "motorway_link": 0.03, "trunk": 0.05, "trunk_link": 0.05, "primary": 0.10,
    "primary_link": 0.10, "secondary": 0.15, "secondary_link": 0.15, "tertiary": 0.25,
    "tertiary_link": 0.25,
}
DEFAULT_TREE_COVER = 0.35


@dataclass
class EdgeHazard:
    """The hazard and the blockage probability of every edge in one scenario."""

    gust_kt: np.ndarray  # (E,)
    depth_m: np.ndarray  # (E,)
    t_peak: np.ndarray  # (E,) hour of the peak wind at the edge
    t_flood: np.ndarray  # (E,) hour of the surge peak, NaN if no flood
    p_tree: np.ndarray
    p_flood: np.ndarray
    p_bridge: np.ndarray
    p_blocked: np.ndarray


def _cells(grid: CountyGrid, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r = np.clip(np.searchsorted(grid.lat, lat), 0, len(grid.lat) - 1)
    c = np.clip(np.searchsorted(grid.lon, lon), 0, len(grid.lon) - 1)
    return r, c


def edge_hazard(rg: RoadGraph, grid: CountyGrid, gust_kt: np.ndarray, coast_m: np.ndarray,
                depth_m: np.ndarray, t_peak: np.ndarray, surge_peak_h: float | None) -> EdgeHazard:
    """Return the hazard values and the blockage probability of every edge."""
    n = len(rg.edges)
    g = np.zeros(n)
    d = np.zeros(n)
    tp = np.zeros(n)
    elev = np.maximum(grid.elev, 0.0)
    for i, e in enumerate(rg.edges):
        pts = np.array(e["coords"])
        r, c = _cells(grid, pts[:, 0], pts[:, 1])
        g[i] = float(gust_kt[r, c].max())
        tp[i] = float(np.median(t_peak[r, c]))
        if e["bridge"]:
            d[i] = 0.0  # a bridge deck is above the surge in this model
        else:
            # Causeway and coastal road segments: use the surge minus the ground elevation.
            dd = np.maximum(depth_m[r, c], np.where(grid.land[r, c], 0.0, coast_m[r, c] - elev[r, c] - 1.0))
            d[i] = float(dd.max())
    tree = np.array([TREE_COVER_PROXY.get(e["highway"], DEFAULT_TREE_COVER) for e in rg.edges])
    p_tree = sigmoid(TREE_SIGMOID_C * (g * KT_TO_MPH - TREE_GUST_MID_MPH)) * tree
    p_flood = (d > FLOOD_BLOCK_DEPTH_M).astype(float)
    bridge = np.array([bool(e["bridge"]) for e in rg.edges])
    p_bridge = np.where(bridge & (g * KT_TO_MPH > BRIDGE_BLOCK_GUST_MPH), BRIDGE_BLOCK_P, 0.0)
    p_blocked = 1.0 - (1.0 - p_tree) * (1.0 - p_flood) * (1.0 - p_bridge)
    t_flood = np.where(p_flood > 0, surge_peak_h if surge_peak_h is not None else np.nan, np.nan)
    return EdgeHazard(g, d, tp, t_flood, p_tree, p_flood, p_bridge, p_blocked)


@dataclass
class BlockedSet:
    """One sampled set of blocked edges."""

    blocked: np.ndarray  # bool (E,)
    cause: np.ndarray  # object (E,) "tree" | "flood" | "bridge" | ""
    blocked_h: np.ndarray  # (E,) hour index when the edge closes


def sample_blocked(hz: EdgeHazard, rng: np.random.Generator) -> BlockedSet:
    """Sample one blocked set from the edge probabilities."""
    n = len(hz.p_blocked)
    u_tree, u_bridge = rng.random(n), rng.random(n)
    tree = u_tree < hz.p_tree
    flood = hz.p_flood > 0.5
    bridge = u_bridge < hz.p_bridge
    blocked = tree | flood | bridge
    cause = np.full(n, "", dtype=object)
    cause[tree] = "tree"
    cause[bridge] = "bridge"
    cause[flood] = "flood"
    t = np.where(flood & np.isfinite(hz.t_flood), hz.t_flood, hz.t_peak)
    return BlockedSet(blocked, cause, t)
