"""Reduce the N-member ensemble to K representative scenarios with k-medoids.

The track distance is the sum of the great-circle distances at matched times plus a
weighted intensity term. The official NHC forecast (OFCL) is a fixed medoid. It is
always scenario 0 and its probability is the size of its cluster divided by N.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from landfall.config import K_SCENARIOS, REDUCE_INTENSITY_WEIGHT_KM_PER_KT
from landfall.geoutil import haversine_km


@dataclass
class Reduction:
    """The result of the scenario reduction."""

    medoids: list[int]  # index into the stacked tracks; index N is OFCL
    probability: list[float]
    labels: np.ndarray  # (N,) cluster index of each member


def _ffill(a: np.ndarray) -> np.ndarray:
    """Carry the last valid value of each row forward over NaN values."""
    out = a.copy()
    for k in range(1, out.shape[1]):
        m = np.isnan(out[:, k])
        out[m, k] = out[m, k - 1]
    return out


def distance_matrix(lat: np.ndarray, lon: np.ndarray, v: np.ndarray,
                    w_kt: float = REDUCE_INTENSITY_WEIGHT_KM_PER_KT) -> np.ndarray:
    """Return the pairwise track distance in km for tracks [n, T]."""
    lat, lon = _ffill(lat), _ffill(lon)
    v = np.nan_to_num(_ffill(v), nan=0.0)
    n, t = lat.shape
    d = np.zeros((n, n))
    for k in range(t):
        ok = ~np.isnan(lat[:, k])
        la = np.where(ok, lat[:, k], 0.0)
        lo = np.where(ok, lon[:, k], 0.0)
        dk = haversine_km(la[:, None], lo[:, None], la[None, :], lo[None, :])
        both = ok[:, None] & ok[None, :]
        d += np.where(both, dk, 0.0)
        d += w_kt * np.abs(v[:, k][:, None] - v[:, k][None, :])
    return d


def kmedoids(d: np.ndarray, k: int, fixed: list[int], n_members: int, seed: int,
             iterations: int = 50) -> Reduction:
    """Run k-medoids on a distance matrix with some fixed medoids.

    Only the first n_members rows count toward the cluster probabilities.
    """
    rng = np.random.default_rng(seed)
    medoids = list(fixed)
    # k-means++ seeding over the members
    while len(medoids) < k:
        dmin = d[:, medoids].min(axis=1)[:n_members]
        p = dmin**2
        if p.sum() <= 0:
            cand = [i for i in range(n_members) if i not in medoids]
            medoids.append(int(rng.choice(cand)))
            continue
        medoids.append(int(rng.choice(n_members, p=p / p.sum())))
    for _ in range(iterations):
        labels = np.argmin(d[:, medoids], axis=1)
        changed = False
        for ci in range(len(fixed), k):
            members = np.where(labels[:n_members] == ci)[0]
            if len(members) == 0:
                continue
            sub = d[np.ix_(members, members)].sum(axis=1)
            best = int(members[np.argmin(sub)])
            if best != medoids[ci]:
                medoids[ci] = best
                changed = True
        if not changed:
            break
    labels = np.argmin(d[:, medoids], axis=1)
    counts = np.bincount(labels[:n_members], minlength=k)
    return Reduction(medoids, (counts / n_members).tolist(), labels[:n_members])


def reduce_tracks(lat: np.ndarray, lon: np.ndarray, v: np.ndarray,
                  ofcl: tuple[np.ndarray, np.ndarray, np.ndarray] | None, seed: int,
                  k: int = K_SCENARIOS) -> Reduction:
    """Reduce member tracks [N, T] to k scenarios. Put OFCL first if it exists."""
    n = lat.shape[0]
    if ofcl is not None:
        lat = np.vstack([lat, ofcl[0][None]])
        lon = np.vstack([lon, ofcl[1][None]])
        v = np.vstack([v, ofcl[2][None]])
        fixed = [n]
    else:
        fixed = []
    d = distance_matrix(lat, lon, v)
    return kmedoids(d, k, fixed, n, seed)
