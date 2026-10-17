"""Compute the wind field of a scenario with a Holland (1980) symmetric profile.

V(r) = Vmax * sqrt((Rmax/r)^B * exp(1 - (Rmax/r)^B)), with B = 1.3. The radius of
maximum wind is 35 km for Category 3 and higher, and 50 km for weaker storms. The model
adds 60% of the forward speed times cos(angle from the right of the motion), on the
right half only. The model does not reduce the wind over land. This is a simplification.

The field uses the gradient-wind form of the same profile. It adds the Coriolis term
(r f / 2) and scales the result so that the wind at Rmax is Vmax. Without this term, the
34-kt wind reaches about 380 km from the centre. With it, the radius is about 230 km.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from landfall.config import (
    FORWARD_MOTION_FRACTION,
    GUST_FACTOR,
    HOLLAND_B,
    RMAX_MAJOR_KM,
    RMAX_OTHER_KM,
)
from landfall.geoutil import bearing_deg, destination, haversine_km

THRESHOLDS_KT = (34, 50, 64, 96)


def rmax_km(vmax_kt: np.ndarray | float) -> np.ndarray:
    """Return the radius of maximum wind for a wind speed."""
    return np.where(np.asarray(vmax_kt) >= 96, RMAX_MAJOR_KM, RMAX_OTHER_KM)


def holland(r_km: np.ndarray, vmax_kt: float | np.ndarray, rmax: float | np.ndarray,
            b: float = HOLLAND_B) -> np.ndarray:
    """Return the symmetric Holland wind speed at radius r (same unit as vmax)."""
    r = np.maximum(np.asarray(r_km, dtype=float), 1e-3)
    x = (np.asarray(rmax) / r) ** b
    return np.asarray(vmax_kt) * np.sqrt(x * np.exp(1.0 - x))


OMEGA = 7.292e-5


def holland_gradient(r_km: np.ndarray, vmax_kt: float, rmax: float, lat_deg: float,
                     b: float = HOLLAND_B) -> np.ndarray:
    """Return the Holland wind with the Coriolis term, scaled so that V(Rmax) = Vmax."""
    f = 2 * OMEGA * abs(np.sin(np.radians(lat_deg)))
    def grad(r: np.ndarray) -> np.ndarray:
        vc = holland(r, vmax_kt, rmax, b)
        rf2 = np.asarray(r, dtype=float) * 1000.0 * f / 2.0 / 0.514444  # kt
        return np.sqrt(vc**2 + rf2**2) - rf2
    scale = float(vmax_kt) / max(float(grad(np.array([rmax]))[0]), 1e-6)
    return grad(r_km) * scale


def forward_motion(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the forward speed in kt and the heading in degrees of an hourly track."""
    n = len(lat)
    spd = np.zeros(n)
    hdg = np.zeros(n)
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        if b == a or np.isnan(lat[a]) or np.isnan(lat[b]):
            continue
        d = haversine_km(lat[a], lon[a], lat[b], lon[b])
        spd[i] = d / (b - a) / 1.852
        hdg[i] = bearing_deg(lat[a], lon[a], lat[b], lon[b])
    return spd, hdg


def wind_at(lat_c: float, lon_c: float, vmax: float, fwd_kt: float, heading: float,
            lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Return the sustained wind in kt at points for one storm position."""
    r = haversine_km(lat_c, lon_c, lat, lon)
    rm = float(rmax_km(vmax))
    v = holland_gradient(r, vmax, rm, lat_c)
    az = bearing_deg(lat_c, lon_c, lat, lon)
    rel = np.radians(az - (heading + 90.0))  # 0 = right of the motion
    v = v + FORWARD_MOTION_FRACTION * fwd_kt * np.clip(np.cos(rel), 0.0, None)
    return v


@dataclass
class WindField:
    """The wind result of one scenario on the county grid."""

    peak_gust_kt: np.ndarray  # (ny, nx)
    hours_34: np.ndarray
    hours_64: np.ndarray
    t_ts_arrival: np.ndarray  # hour index from T0, NaN if never
    t_peak: np.ndarray  # hour index of the peak wind
    hourly_max_kt: np.ndarray  # (H,) maximum sustained wind over the county at each hour
    t_last_64: np.ndarray  # (ny, nx) last hour with hurricane-force wind, NaN if never


def wind_field(track_lat: np.ndarray, track_lon: np.ndarray, track_v: np.ndarray,
               grid_lat: np.ndarray, grid_lon: np.ndarray) -> WindField:
    """Return the wind field over the grid for an hourly track (index = hour from T0)."""
    yy, xx = np.meshgrid(grid_lat, grid_lon, indexing="ij")
    peak = np.zeros(yy.shape)
    h34 = np.zeros(yy.shape)
    h64 = np.zeros(yy.shape)
    t_ts = np.full(yy.shape, np.nan)
    t_peak = np.zeros(yy.shape)
    t_last64 = np.full(yy.shape, np.nan)
    hourly = np.zeros(len(track_lat))
    spd, hdg = forward_motion(track_lat, track_lon)
    clat, clon = float(grid_lat.mean()), float(grid_lon.mean())
    for h in range(len(track_lat)):
        if np.isnan(track_lat[h]):
            continue
        if haversine_km(track_lat[h], track_lon[h], clat, clon) > 900:
            continue
        v = wind_at(track_lat[h], track_lon[h], track_v[h], spd[h], hdg[h], yy, xx)
        hourly[h] = float(v.max())
        newer = v > peak
        t_peak = np.where(newer, h, t_peak)
        peak = np.maximum(peak, v)
        h34 += v >= 34
        h64 += v >= 64
        t_ts = np.where(np.isnan(t_ts) & (v >= 34), h, t_ts)
        t_last64 = np.where(v >= 64, h, t_last64)
    return WindField(peak * GUST_FACTOR, h34, h64, t_ts, t_peak, hourly, t_last64)


def rings(track_lat: np.ndarray, track_lon: np.ndarray, track_v: np.ndarray,
          n_bearings: int = 72) -> dict[str, list[list[tuple[float, float]] | None]]:
    """Return, for each hour and threshold, the outer ring of the area at or above it."""
    spd, hdg = forward_motion(track_lat, track_lon)
    bearings = np.arange(n_bearings) * (360.0 / n_bearings)
    radii = np.linspace(1.0, 700.0, 700)
    out: dict[str, list[list[tuple[float, float]] | None]] = {str(t): [] for t in THRESHOLDS_KT}
    for h in range(len(track_lat)):
        if np.isnan(track_lat[h]):
            for t in THRESHOLDS_KT:
                out[str(t)].append(None)
            continue
        rm = float(rmax_km(track_v[h]))
        base = holland_gradient(radii, track_v[h], rm, float(track_lat[h]))  # (R,)
        rel = np.radians(bearings - (hdg[h] + 90.0))
        add = FORWARD_MOTION_FRACTION * spd[h] * np.clip(np.cos(rel), 0.0, None)  # (Bn,)
        v = base[None, :] + add[:, None]  # (Bn, R)
        for t in THRESHOLDS_KT:
            above = v >= t
            if not above.any():
                out[str(t)].append(None)
                continue
            # outer radius: the last radius at or above the threshold
            idx = np.where(above.any(axis=1), above.shape[1] - 1 - np.argmax(above[:, ::-1], axis=1), -1)
            r = np.where(idx >= 0, radii[np.clip(idx, 0, None)], 0.5)
            la, lo = destination(float(track_lat[h]), float(track_lon[h]), bearings, r)
            ring = [(round(float(x), 4), round(float(y), 4)) for x, y in zip(lo, la, strict=True)]
            ring.append(ring[0])
            out[str(t)].append(ring)
    return out
