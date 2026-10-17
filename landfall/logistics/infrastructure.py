"""Find the infrastructure to harden from all scenario samples.

For each edge, p_blocked_any is the fraction of samples with the edge blocked, and
criticality = betweenness x population served. The 10 edges with the highest
p_blocked_any x criticality make the "harden these" list. The module also flags:

- The zones that clear after TS arrival in more than 30% of the samples.
- The shelters that fill in more than 50% of the samples.
"""

from __future__ import annotations

import numpy as np

from landfall.config import ZONES
from landfall.logistics.debris import EdgeWeights
from landfall.logistics.network import Net


def harden_list(net: Net, blocked_counts: np.ndarray, n_samples: int, weights: EdgeWeights,
                top: int = 10) -> list[dict[str, object]]:
    """Return the top edges by p_blocked_any x criticality. Keep one edge for each road name."""
    p_any = blocked_counts / max(n_samples, 1)
    crit = weights.betweenness * weights.population_served
    score = p_any * crit
    order = np.argsort(-score)
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for i in order:
        if score[i] <= 0 or len(out) >= top:
            break
        e = net.rg.edges[int(i)]
        key = str(e["critical_name"] or e["name"])  # one entry for each named road
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "rank": len(out) + 1, "edge_id": e["edge_id"],
            "name": e["critical_name"] or e["name"], "p_blocked_any": float(p_any[i]),
            "criticality": float(crit[i]), "score": float(score[i]),
            "path": [(float(x), float(y)) for x, y in e["coords"]],
        })
    return out


def zone_flags(late_counts: np.ndarray, n_samples: int, threshold: float = 0.3) -> list[dict[str, object]]:
    """Return the zones that clear after TS arrival in more than 30% of the samples."""
    p = late_counts / max(n_samples, 1)
    return [{"zone": z, "p_late": float(p[k]), "action": "add road capacity or release earlier"}
            for k, z in enumerate(ZONES) if p[k] > threshold]


def shelter_flags(shelter_ids: list[str], full_counts: np.ndarray, n_samples: int,
                  threshold: float = 0.5) -> list[dict[str, object]]:
    """Return the shelters that fill in more than 50% of the samples."""
    p = full_counts / max(n_samples, 1)
    return [{"shelter_id": s, "p_full": float(p[k]), "action": "add capacity"}
            for k, s in enumerate(shelter_ids) if p[k] > threshold]
