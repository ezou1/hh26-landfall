"""Roll out the Monte Carlo ensemble of tracks and summarise it.

The rollout is vectorised over all members. At each 6-h step it rebuilds the StormState
features from the history of each member, with the same formulas as the Chalk resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint, mapping
from shapely.ops import unary_union

from landfall.config import (
    BBOX,
    DISSIPATE_HOURS,
    DISSIPATE_KT,
    HORIZON_H,
    LAND_DECAY_PER_H,
    STEP_H,
    STORM_ID,
    VMAX_MAX_KT,
    VMAX_MIN_KT,
)
from landfall.ingest.geo import county_grid, land_distance_km
from landfall.predict.features import chalk_module, feature_matrix, state_columns
from landfall.predict.model import Predictor

LAG_STEPS = 4  # 24 h of history at 6-h spacing


@dataclass
class History:
    """The 6-hourly history of each batch row. Column -1 is the current time."""

    lat: np.ndarray  # (B, L)
    lon: np.ndarray
    v: np.ndarray
    p: np.ndarray
    t_now_h: np.ndarray  # (B,) hours since the Unix epoch
    genesis_h: np.ndarray  # (B,)

    @property
    def size(self) -> int:
        """Return the batch size."""
        return self.lat.shape[0]

    def repeat(self, n: int) -> History:
        """Return a history with each row repeated n times."""
        return History(*(np.repeat(a, n, axis=0) for a in (self.lat, self.lon, self.v, self.p,
                                                             self.t_now_h, self.genesis_h)))


def history_from_fixes(fixes: pd.DataFrame, now: datetime, fix_source: str) -> History:
    """Return a 1-row history from the fixes at or before now (point-in-time)."""
    rz = chalk_module("resolvers")
    f = fixes[fixes["source"] == fix_source]
    now_ts = pd.Timestamp(now)
    f = f[f["time"] <= now_ts].sort_values("time")
    if f.empty:
        raise ValueError(f"no {fix_source} fix at or before {now}")
    t = (f["time"].astype("int64").to_numpy() // 10**9) / 3600.0
    tn = now_ts.value / 1e9 / 3600.0
    grid = tn - STEP_H * np.arange(LAG_STEPS, -1, -1)
    p_raw = f["pmin_mb"].to_numpy(dtype=float)
    v_raw = f["vmax_kt"].to_numpy(dtype=float)
    p_raw = np.where(np.isnan(p_raw), rz.pressure_from_wind(v_raw), p_raw)

    def interp(vals: np.ndarray) -> np.ndarray:
        return np.interp(np.maximum(grid, t[0]), t, vals)[None, :]

    return History(interp(f["lat"].to_numpy(float)), interp(f["lon"].to_numpy(float)), interp(v_raw),
                   interp(p_raw), np.array([tn]), np.array([t[0]]))


def history_from_state(state: dict[str, float], now: datetime) -> History:
    """Return a 1-row history from a StormState (the online Chalk output).

    The lag features give the positions at -6, -12, and -24 h. The position at -18 h
    is the mean of the -12 h and -24 h positions.
    """
    lat, lon, v = state["lat"], state["lon"], state["vmax_kt"]

    def series(cur: float, d6: float, d12: float, d24: float) -> np.ndarray:
        p24, p12, p6 = cur - d24, cur - d12, cur - d6
        return np.array([[p24, 0.5 * (p24 + p12), p12, p6, cur]])

    la = series(lat, state["dlat_6"], state["dlat_12"], state["dlat_24"])
    lo = series(lon, state["dlon_6"], state["dlon_12"], state["dlon_24"])
    vv = series(v, state["dv_6"], state["dv_12"], state["dv_24"])
    rz = chalk_module("resolvers")
    pp = rz.pressure_from_wind(vv)
    pp[0, -1] = state["pmin_mb"]
    tn = pd.Timestamp(now).value / 1e9 / 3600.0
    return History(la, lo, vv, pp, np.array([tn]), np.array([tn - state["hours_since_genesis"]]))


def state_frame(h: History) -> pd.DataFrame:
    """Return the StormState features of each batch row as a frame."""
    rz = chalk_module("resolvers")
    lat, lon, v = h.lat[:, -1], h.lon[:, -1], h.v[:, -1]
    d: dict[str, np.ndarray] = {"lat": lat, "lon": lon, "vmax_kt": v, "pmin_mb": h.p[:, -1]}
    for lag, k in ((6, 1), (12, 2), (24, 4)):
        d[f"dlat_{lag}"] = lat - h.lat[:, -1 - k]
        d[f"dlon_{lag}"] = lon - h.lon[:, -1 - k]
        d[f"dv_{lag}"] = v - h.v[:, -1 - k]
    dy = d["dlat_6"] * 60.0
    dx = d["dlon_6"] * 60.0 * np.cos(np.radians(lat))
    d["heading_deg"] = (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0
    d["speed_kt"] = np.hypot(dx, dy) / 6.0
    ts = pd.to_datetime(h.t_now_h * 3600.0, unit="s", utc=True)
    d["day_of_year"] = ts.dayofyear.to_numpy()
    d["sst_proxy_c"] = rz.sst_proxy_vec(lat, lon, ts.month.to_numpy())
    d["land_distance_km"] = land_distance_km(lon, lat)
    d["hours_since_genesis"] = h.t_now_h - h.genesis_h
    return pd.DataFrame(d)[state_columns()]


@dataclass
class Rollout:
    """The result of a rollout: arrays (B, T) at 6-h spacing. Column 0 is the start."""

    lat: np.ndarray
    lon: np.ndarray
    v: np.ndarray
    p: np.ndarray
    alive: np.ndarray  # bool (B, T)
    pred: np.ndarray  # (B, T-1, 3) model prediction of each step, before residuals


def rollout(
    pred: Predictor,
    h0: History,
    n_steps: int,
    rng: np.random.Generator | None = None,
    stochastic: bool = True,
) -> Rollout:
    """Roll the model forward n_steps of 6 h for every batch row.

    If stochastic is True, each row takes one residual trajectory from the bank and adds
    a small Gaussian jitter. If not, the rollout is deterministic.
    """
    rz = chalk_module("resolvers")
    rng = rng or np.random.default_rng(0)
    h = History(h0.lat.copy(), h0.lon.copy(), h0.v.copy(), h0.p.copy(), h0.t_now_h.copy(), h0.genesis_h.copy())
    b = h.size
    shape = (b, n_steps + 1)
    out_lat, out_lon, out_v, out_p = (np.full(shape, np.nan) for _ in range(4))
    alive = np.zeros(shape, dtype=bool)
    preds = np.zeros((b, n_steps, 3))
    out_lat[:, 0], out_lon[:, 0], out_v[:, 0], out_p[:, 0] = h.lat[:, -1], h.lon[:, -1], h.v[:, -1], h.p[:, -1]
    alive[:, 0] = True
    weak_steps = np.zeros(b, dtype=int)
    decay = np.exp(-LAND_DECAY_PER_H * STEP_H)
    for k in range(n_steps):
        x = feature_matrix(state_frame(h))
        y = pred.predict(x)
        preds[:, k] = y
        if stochastic:
            y = y + pred.sample_residuals(k, b, rng, lat=h.lat[:, -1])
        lat, lon, v = h.lat[:, -1], h.lon[:, -1], h.v[:, -1]
        over_land = land_distance_km(lon, lat) < 0
        v_new = np.where(over_land, v * decay + y[:, 2], v + y[:, 2])
        v_new = np.clip(v_new, VMAX_MIN_KT, VMAX_MAX_KT)
        lat_new = lat + y[:, 0]
        lon_new = lon + y[:, 1]
        weak_steps = np.where(v_new < DISSIPATE_KT, weak_steps + 1, 0)
        still = alive[:, k] & (weak_steps * STEP_H < DISSIPATE_HOURS)
        p_new = rz.pressure_from_wind(v_new)
        h.lat = np.concatenate([h.lat[:, 1:], lat_new[:, None]], axis=1)
        h.lon = np.concatenate([h.lon[:, 1:], lon_new[:, None]], axis=1)
        h.v = np.concatenate([h.v[:, 1:], v_new[:, None]], axis=1)
        h.p = np.concatenate([h.p[:, 1:], p_new[:, None]], axis=1)
        h.t_now_h = h.t_now_h + STEP_H
        alive[:, k + 1] = still
        out_lat[:, k + 1] = np.where(still, lat_new, np.nan)
        out_lon[:, k + 1] = np.where(still, lon_new, np.nan)
        out_v[:, k + 1] = np.where(still, v_new, np.nan)
        out_p[:, k + 1] = np.where(still, p_new, np.nan)
    return Rollout(out_lat, out_lon, out_v, out_p, alive, preds)


def ensemble(
    pred: Predictor, fixes: pd.DataFrame, t0: datetime, n: int, seed: int, fix_source: str = "carq",
    horizon_h: int = HORIZON_H,
) -> Rollout:
    """Return an n-member ensemble that starts from the Chalk StormState at t0."""
    from landfall.predict.features import online_state

    state = online_state(STORM_ID if fixes is None else str(_storm_of(fixes)), t0, fix_source)
    h0 = history_from_state(state, t0).repeat(n)
    rng = np.random.default_rng(seed)
    return rollout(pred, h0, horizon_h // STEP_H, rng=rng, stochastic=True)


def _storm_of(fixes: pd.DataFrame) -> str:
    """Return the storm id for the ensemble. The replay storm is always Ian."""
    return STORM_ID


# ----------------------------------------------------------------- summaries
def category(vmax_kt: float) -> str:
    """Return the Saffir-Simpson category of a wind speed: TS, 1, 2, 3, 4, or 5."""
    for cat, lo in (("5", 137), ("4", 113), ("3", 96), ("2", 83), ("1", 64)):
        if vmax_kt >= lo:
            return cat
    return "TS"


def hourly(track_lat: np.ndarray, track_lon: np.ndarray, track_v: np.ndarray) -> tuple[np.ndarray, ...]:
    """Return a 6-hourly track interpolated to 1-h spacing (NaN after the end)."""
    n = len(track_lat)
    t6 = np.arange(n) * STEP_H
    t1 = np.arange((n - 1) * STEP_H + 1)
    ok = ~np.isnan(track_lat)
    if ok.sum() < 2:
        return (np.full(len(t1), np.nan),) * 3
    last = t6[ok][-1]
    out = []
    for a in (track_lat, track_lon, track_v):
        y = np.interp(t1, t6[ok], a[ok])
        y[t1 > last] = np.nan
        out.append(y)
    return tuple(out)


_COUNTY: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None


def county_landfall(lat_h: np.ndarray, lon_h: np.ndarray) -> int | None:
    """Return the first hour index where the centre crosses from water to county land."""
    global _COUNTY
    if _COUNTY is None:
        g = county_grid()
        _COUNTY = (g.lon, g.lat, g.land)
    glon, glat, land = _COUNTY
    w, s, e, n = BBOX
    prev_water = None
    for i in range(len(lat_h)):
        la, lo = lat_h[i], lon_h[i]
        if np.isnan(la):
            break
        if w <= lo <= e and s <= la <= n:
            r = int(np.clip(np.searchsorted(glat, la), 0, len(glat) - 1))
            c = int(np.clip(np.searchsorted(glon, lo), 0, len(glon) - 1))
            is_land = bool(land[r, c])
        else:
            is_land = bool(land_distance_km(lo, la) < 0)
            if is_land:
                prev_water = False
                continue
        if is_land and prev_water and (w <= lo <= e and s <= la <= n):
            return i
        prev_water = not is_land
    return None


def _is_land(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (land, inside the county bbox) for arrays of points."""
    global _COUNTY
    if _COUNTY is None:
        g = county_grid()
        _COUNTY = (g.lon, g.lat, g.land)
    glon, glat, land = _COUNTY
    w, s, e, n = BBOX
    inside = (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    r = np.clip(np.searchsorted(glat, np.nan_to_num(lat)), 0, len(glat) - 1)
    c = np.clip(np.searchsorted(glon, np.nan_to_num(lon)), 0, len(glon) - 1)
    county_land = land[r, c]
    basin_land = land_distance_km(np.nan_to_num(lon), np.nan_to_num(lat)) < 0
    return np.where(inside, county_land, basin_land) & ~np.isnan(lat), inside


def landfall_hours(ro: Rollout) -> tuple[np.ndarray, np.ndarray]:
    """Return the county landfall hour of each member (NaN if none) and the wind at landfall."""
    n, t = ro.lat.shape
    t6 = np.arange(t) * STEP_H
    t1 = np.arange((t - 1) * STEP_H + 1)
    idx = np.clip(np.searchsorted(t6, t1, side="right") - 1, 0, t - 2)
    frac = (t1 - t6[idx]) / STEP_H
    lat = ro.lat[:, idx] * (1 - frac) + ro.lat[:, idx + 1] * frac
    lon = ro.lon[:, idx] * (1 - frac) + ro.lon[:, idx + 1] * frac
    v = ro.v[:, idx] * (1 - frac) + ro.v[:, idx + 1] * frac
    exact = frac == 0
    lat[:, exact], lon[:, exact], v[:, exact] = ro.lat[:, idx[exact]], ro.lon[:, idx[exact]], ro.v[:, idx[exact]]
    land, inside = _is_land(lat, lon)
    valid = ~np.isnan(lat)
    hit = np.zeros_like(land)
    hit[:, 1:] = land[:, 1:] & inside[:, 1:] & ~land[:, :-1] & valid[:, :-1] & valid[:, 1:]
    first = np.where(hit.any(axis=1), np.argmax(hit, axis=1), -1)
    hours = np.where(first >= 0, first, np.nan).astype(float)
    vl = np.where(first >= 0, v[np.arange(n), np.maximum(first, 0)], np.nan)
    return hours, vl


def landfall_summary(ro: Rollout, t0: datetime) -> dict[str, object]:
    """Return p(landfall in the county), the landfall time quantiles, and the category mix."""
    cats: dict[str, int] = {k: 0 for k in ("TS", "1", "2", "3", "4", "5")}
    hrs, vl = landfall_hours(ro)
    ok = np.isfinite(hrs)
    times: list[float] = hrs[ok].tolist()
    for v in vl[ok]:
        cats[category(float(v))] += 1
    n = ro.lat.shape[0]
    p = len(times) / n

    def q(x: float) -> str | None:
        if not times:
            return None
        return (t0 + timedelta(hours=float(np.quantile(times, x)))).strftime("%Y-%m-%dT%H:%M:%SZ")

    total = max(1, len(times))
    return {
        "p_landfall_county": p,
        "landfall_time_p10": q(0.1),
        "landfall_time_p50": q(0.5),
        "landfall_time_p90": q(0.9),
        "category_dist": {k: c / total for k, c in cats.items()},
        "n_landfall": len(times),
    }


def cone(ro: Rollout, levels: tuple[float, ...] = (0.5, 0.66, 0.9)) -> dict[str, object]:
    """Return the cone as GeoJSON: one swath polygon for each quantile level.

    For each step, the function keeps the members inside the quantile of distance to the
    ensemble mean and takes the convex hull. A swath joins the hulls of adjacent steps.
    """
    feats = []
    for q in levels:
        hulls = []
        for k in range(ro.lat.shape[1]):
            ok = ~np.isnan(ro.lat[:, k])
            if ok.sum() < 5:
                break
            la, lo = ro.lat[ok, k], ro.lon[ok, k]
            cy, cx = la.mean(), lo.mean()
            d = np.hypot((lo - cx) * np.cos(np.radians(cy)), la - cy)
            keep = d <= np.quantile(d, q)
            pts = MultiPoint(list(zip(lo[keep], la[keep], strict=True)))
            hulls.append(pts.convex_hull.buffer(0.08))
        parts = [unary_union([hulls[i], hulls[i + 1]]).convex_hull for i in range(len(hulls) - 1)]
        geom = unary_union(parts).simplify(0.02) if parts else None
        if geom is not None:
            feats.append({"type": "Feature", "properties": {"level": f"p{int(round(q * 100))}"},
                          "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": feats}
