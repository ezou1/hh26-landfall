"""Give fast shortest-path tools on the routing graph with SciPy sparse graphs.

The logistics models use these tools for evacuation routes, supply travel times, the
high-water truck routes, and the access weights of the debris model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from landfall.ingest.osm import RoadGraph, nearest_node


@dataclass
class Net:
    """The routing graph as index arrays for SciPy."""

    rg: RoadGraph
    node_ids: np.ndarray  # (N,) OSM node id of each index
    index: dict[int, int]  # OSM node id -> index
    eu: np.ndarray  # (E,) from-node index of each edge
    ev: np.ndarray  # (E,) to-node index of each edge
    tt_h: np.ndarray  # (E,) free-flow travel time in hours
    cap_vph: np.ndarray  # (E,) capacity in vehicles per hour
    length_m: np.ndarray
    _pair_edge: dict[tuple[int, int], int] = field(default_factory=dict)

    @property
    def n_nodes(self) -> int:
        """Return the number of nodes."""
        return len(self.node_ids)

    def matrix(self, cost: np.ndarray, closed: np.ndarray | None = None, reverse: bool = False) -> csr_matrix:
        """Return a sparse cost matrix. Closed edges are left out."""
        keep = np.ones(len(cost), bool) if closed is None else ~closed
        # For parallel edges keep the cheapest: sort by cost so that the first one wins.
        u, v, c = self.eu[keep], self.ev[keep], np.maximum(cost[keep], 1e-6)
        if reverse:
            u, v = v, u
        order = np.lexsort((c, v, u))
        u, v, c = u[order], v[order], c[order]
        first = np.ones(len(u), bool)
        first[1:] = (u[1:] != u[:-1]) | (v[1:] != v[:-1])
        return csr_matrix((c[first], (u[first], v[first])), shape=(self.n_nodes, self.n_nodes))

    def edge_of(self, a: int, b: int) -> int:
        """Return the cheapest edge index from node index a to node index b."""
        return self._pair_edge[(a, b)]

    def node(self, lon: float, lat: float) -> int:
        """Return the node index nearest to a point."""
        return self.index[nearest_node(self.rg, lon, lat)]

    def times_from(self, sources: list[int], cost: np.ndarray | None = None,
                   closed: np.ndarray | None = None) -> np.ndarray:
        """Return the travel time in hours from each source to every node."""
        m = self.matrix(self.tt_h if cost is None else cost, closed)
        return dijkstra(m, directed=True, indices=sources)

    def tree_to(self, target: int, cost: np.ndarray, closed: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Return (time to target, next node toward target) for every node."""
        m = self.matrix(cost, closed, reverse=True)
        dist, pred = dijkstra(m, directed=True, indices=[target], return_predecessors=True)
        return dist[0], pred[0]

    def path_nodes(self, pred_to_target: np.ndarray, start: int, max_len: int = 5000) -> list[int]:
        """Return the node path from start to the target of a tree from tree_to."""
        out = [start]
        cur = start
        while pred_to_target[cur] >= 0 and len(out) < max_len:
            cur = int(pred_to_target[cur])
            out.append(cur)
        return out

    def path_coords(self, nodes: list[int]) -> list[tuple[float, float]]:
        """Return the coordinates of a node path, with the edge geometry."""
        pts: list[tuple[float, float]] = []
        for a, b in zip(nodes[:-1], nodes[1:], strict=True):
            e = self.rg.edges[self.edge_of(a, b)]
            c = e["coords"]
            pts.extend(c if not pts else c[1:])
        if not pts and nodes:
            x, y = self.rg.node_xy[int(self.node_ids[nodes[0]])]
            pts = [(x, y)]
        return pts


def build_net(rg: RoadGraph) -> Net:
    """Return the Net arrays of a routing graph."""
    from landfall.config import CAPACITY_FACTOR, LANE_CAPACITY_VPH

    node_ids = np.array(sorted(rg.node_xy.keys()))
    index = {int(n): i for i, n in enumerate(node_ids)}
    eu = np.array([index[e["u"]] for e in rg.edges])
    ev = np.array([index[e["v"]] for e in rg.edges])
    tt = np.array([e["tt_h"] for e in rg.edges], dtype=float)
    cap = np.array([e["lanes"] * LANE_CAPACITY_VPH * CAPACITY_FACTOR for e in rg.edges], dtype=float)
    length = np.array([e["length_m"] for e in rg.edges], dtype=float)
    net = Net(rg, node_ids, index, eu, ev, tt, cap, length)
    for i in np.argsort(-tt):  # the cheapest edge of a pair wins
        net._pair_edge[(int(eu[i]), int(ev[i]))] = int(i)
    return net


def accumulate_tree(pred: np.ndarray, dist: np.ndarray, demand: np.ndarray, net: Net) -> np.ndarray:
    """Return the flow on each edge when every node sends its demand along the tree to the target."""
    flow_node = demand.astype(float).copy()
    edge_flow = np.zeros(len(net.eu))
    order = np.argsort(-np.where(np.isfinite(dist), dist, -1))
    for n in order:
        if not np.isfinite(dist[n]) or flow_node[n] <= 0:
            continue
        p = pred[n]
        if p < 0:
            continue
        edge_flow[net.edge_of(int(n), int(p))] += flow_node[n]
        flow_node[p] += flow_node[n]
    return edge_flow
