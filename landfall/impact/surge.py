"""Compute a storm-surge proxy. This is not SLOSH.

The peak surge at the coast is S = C * Vmax_kt^1.7 * k_angle metres, with
k_angle = max(0.3, cos(approach angle)). The full value applies from 0 to 3 Rmax to the
right of the track, and it decreases linearly to 0 at 6 Rmax. On the left of the track
it decreases to 0 at 1 Rmax. A land cell floods if two conditions are true:

- Its elevation is less than the surge at the nearest water cell.
- It is not more than 15 km from the coast.

The constant C is calibrated so that the Ian truth track gives 4 m near Fort Myers Beach.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from landfall.config import (
    CACHE,
    GRID_RES_M,
    SURGE_COEFF,
    SURGE_EXP,
    SURGE_INLAND_KM,
    SURGE_K_ANGLE_MIN,
)
from landfall.geoutil import local_xy_km
from landfall.impact.wind import forward_motion, rmax_km
from landfall.ingest.geo import CountyGrid

ONSHORE_HEADING_DEG = 75.0  # the onshore normal of the Lee County Gulf coast
CALIBRATION_FILE = CACHE / "surge_calibration.json"
FORT_MYERS_BEACH = (26.452, -81.945)  # lat, lon
TARGET_FMB_M = 4.0
NEAR_COAST_KM = 60.0  # the storm centre must be this near the coast to make surge


@dataclass
class SurgeField:
    """The surge result of one scenario on the county grid."""

    depth_m: np.ndarray  # (ny, nx) flood depth over land; 0 over water
    coast_m: np.ndarray  # (ny, nx) surge height at the nearest water cell
    peak_hour: float | None


def coefficient() -> float:
    """Return the calibrated surge constant, or the default constant if not calibrated."""
    if CALIBRATION_FILE.exists():
        return float(json.loads(CALIBRATION_FILE.read_text())["coeff"])
    return SURGE_COEFF


def surge_field(grid: CountyGrid, lat: np.ndarray, lon: np.ndarray, v: np.ndarray,
                coeff: float | None = None) -> SurgeField:
    """Return the surge field for an hourly track (index = hour from T0)."""
    c = coefficient() if coeff is None else coeff
    yy, xx = np.meshgrid(grid.lat, grid.lon, indexing="ij")
    water = ~grid.land
    spd, hdg = forward_motion(lat, lon)
    s_max = np.zeros(yy.shape)
    t_max = np.full(yy.shape, np.nan)
    # distance of each grid cell to the nearest land cell, to find hours when the centre is near the coast
    lat0, lon0 = float(grid.lat.mean()), float(grid.lon.mean())
    for h in range(len(lat)):
        if np.isnan(lat[h]) or v[h] < 34:
            continue
        cx, cy = local_xy_km(np.array([lat[h]]), np.array([lon[h]]), lat0, lon0)
        if abs(cx[0]) > 120 or abs(cy[0]) > 120:
            continue
        rm = float(rmax_km(v[h]))
        approach = np.radians(hdg[h] - ONSHORE_HEADING_DEG)
        k = max(SURGE_K_ANGLE_MIN, float(np.cos(approach)))
        s0 = c * v[h] ** SURGE_EXP * k
        ex, ey = local_xy_km(yy, xx, float(lat[h]), float(lon[h]))
        hr = np.radians(hdg[h])
        along = ex * np.sin(hr) + ey * np.cos(hr)
        right = ex * np.cos(hr) - ey * np.sin(hr)  # positive to the right of the motion
        f_right = np.clip((6 * rm - right) / (3 * rm), 0.0, 1.0)
        f_left = np.clip(1.0 + right / rm, 0.0, 1.0)
        f_cross = np.where(right >= 0, f_right, f_left)
        f_along = np.clip(1.0 - (np.abs(along) - 2 * rm) / (2 * rm), 0.0, 1.0)
        s = s0 * f_cross * f_along
        newer = s > s_max
        t_max = np.where(newer, h, t_max)
        s_max = np.maximum(s_max, s)
    # Each land cell takes the surge of its nearest water cell.
    if water.any():
        _, (iy, ix) = ndimage.distance_transform_edt(~water, return_indices=True)
        coast_s = s_max[iy, ix]
        coast_t = t_max[iy, ix]
    else:
        coast_s, coast_t = s_max, t_max
    inland_km = ndimage.distance_transform_edt(grid.land) * GRID_RES_M / 1000.0
    elev = np.maximum(grid.elev, 0.0)
    depth = np.where(grid.land & (inland_km <= SURGE_INLAND_KM) & (elev < coast_s), coast_s - elev, 0.0)
    peak = float(np.nanmin(np.where(depth > 0.3, coast_t, np.nan))) if (depth > 0.3).any() else None
    return SurgeField(depth.astype(np.float32), coast_s.astype(np.float32), peak)


def sample_point(grid: CountyGrid, field: np.ndarray, lat: float, lon: float, radius_cells: int = 1) -> float:
    """Return the maximum of a grid field in a small window around a point."""
    r = int(np.clip(np.searchsorted(grid.lat, lat), 0, len(grid.lat) - 1))
    c = int(np.clip(np.searchsorted(grid.lon, lon), 0, len(grid.lon) - 1))
    win = field[max(0, r - radius_cells) : r + radius_cells + 1, max(0, c - radius_cells) : c + radius_cells + 1]
    return float(np.nanmax(win))


def calibrate(grid: CountyGrid, lat: np.ndarray, lon: np.ndarray, v: np.ndarray) -> float:
    """Fit the surge constant so that the truth track gives 4 m near Fort Myers Beach."""
    sf = surge_field(grid, lat, lon, v, coeff=SURGE_COEFF)
    s_fmb = sample_point(grid, sf.coast_m, *FORT_MYERS_BEACH)
    coeff = SURGE_COEFF * TARGET_FMB_M / max(s_fmb, 1e-6)
    check = surge_field(grid, lat, lon, v, coeff=coeff)
    out = {
        "coeff": coeff, "default_coeff": SURGE_COEFF, "target_m": TARGET_FMB_M,
        "fmb_surge_default_m": s_fmb,
        "fmb_surge_calibrated_m": sample_point(grid, check.coast_m, *FORT_MYERS_BEACH),
        "fmb_depth_calibrated_m": sample_point(grid, check.depth_m, *FORT_MYERS_BEACH, radius_cells=2),
        "note": "fit on the HURDAT2 truth track of Ian at one point; not a SLOSH result",
    }
    CALIBRATION_FILE.write_text(json.dumps(out, indent=2))
    return coeff
