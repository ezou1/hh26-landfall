"""Aggregate the metrics of all scenario samples into expected values and quantiles.

Each scenario has a probability. Each of its M draws has an equal part of that
probability. "worst10" is the mean of the metric over the worst 10% of the probability.
"""

from __future__ import annotations

import numpy as np

HIGHER_IS_WORSE = {
    "persons_at_risk", "persons_not_cleared", "unmet_supply_kg", "expected_rescues",
    "unmet_tasks_72h", "median_time_to_rescue_h", "objective", "blocked_edges", "transport_cost",
    "persons_evacuated_unnecessarily",
}


def weighted_quantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    """Return the weighted quantile q of x."""
    order = np.argsort(x)
    xs, ws = x[order], w[order]
    cw = np.cumsum(ws) / ws.sum()
    return float(np.interp(q, cw, xs))


def stats(x: np.ndarray, w: np.ndarray, higher_is_worse: bool = True) -> dict[str, float]:
    """Return the expected value, the worst-10% mean, and the p10, p50, and p90 values."""
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    ok = np.isfinite(x)
    x, w = x[ok], w[ok]
    if len(x) == 0:
        return {"expected": 0.0, "worst10": 0.0, "p10": 0.0, "p50": 0.0, "p90": 0.0}
    w = w / w.sum()
    order = np.argsort(-x if higher_is_worse else x)
    xs, ws = x[order], w[order]
    cw = np.cumsum(ws)
    take = cw - ws < 0.1
    tail_w = np.minimum(ws, np.maximum(0.0, 0.1 - (cw - ws)))[take]
    worst = float((xs[take] * tail_w).sum() / max(tail_w.sum(), 1e-12))
    return {
        "expected": float((x * w).sum()), "worst10": worst,
        "p10": weighted_quantile(x, w, 0.1), "p50": weighted_quantile(x, w, 0.5),
        "p90": weighted_quantile(x, w, 0.9),
    }


def aggregate(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Return the statistics of every metric. Each row has "weight" and the metric values."""
    w = np.array([r["weight"] for r in rows])
    keys = [k for k in rows[0] if k not in ("weight", "scenario_id", "draw", "probability")]
    out = {}
    for k in keys:
        out[k] = stats(np.array([r[k] for r in rows]), w, k in HIGHER_IS_WORSE)
    return out


def per_scenario(rows: list[dict[str, float]]) -> list[dict[str, float]]:
    """Return the mean metrics of each scenario over its draws."""
    ids = sorted({int(r["scenario_id"]) for r in rows})
    out = []
    for s in ids:
        sub = [r for r in rows if int(r["scenario_id"]) == s]
        d = {"scenario_id": float(s), "probability": float(sub[0]["probability"])}
        for k in sub[0]:
            if k in ("weight", "scenario_id", "draw", "probability"):
                continue
            vals = np.array([r[k] for r in sub], dtype=float)
            d[k] = float(np.nanmean(vals)) if np.isfinite(vals).any() else 0.0
        out.append(d)
    return out
