"""Convert wind and surge into damage, injuries, and rescue requests per block group.

p_major_damage = sigmoid(a * (gust - 95 mph)) * (1 + 0.5 * surge_depth), clipped to 1.
expected injuries = population * p_major * 0.02 * (1 - evacuated_fraction).
expected rescue requests = population * (1 - evacuated_fraction) * p(depth > 1 m) * 0.3.
These are documented assumptions. The UI shows them in the assumptions drawer.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
from rasterio import features as rfeatures
from rasterio.transform import from_origin

from landfall.config import (
    DAMAGE_GUST_MID_MPH,
    DAMAGE_SIGMOID_A,
    INJURY_RATE,
    KT_TO_MPH,
    RESCUE_RATE,
)
from landfall.ingest.geo import CountyGrid


def sigmoid(x: np.ndarray) -> np.ndarray:
    """Return the logistic function of x."""
    return 1.0 / (1.0 + np.exp(-x))


def block_group_index(grid: CountyGrid, bgs: gpd.GeoDataFrame) -> np.ndarray:
    """Return a grid of block-group row numbers (-1 outside all block groups)."""
    dlon = grid.lon[1] - grid.lon[0]
    dlat = grid.lat[1] - grid.lat[0]
    tf = from_origin(grid.lon[0] - dlon / 2, grid.lat[-1] + dlat / 2, dlon, dlat)
    shapes = ((geom, i) for i, geom in enumerate(bgs.geometry.values))
    out = rfeatures.rasterize(shapes, out_shape=grid.shape, transform=tf, fill=-1, dtype="int32",
                              all_touched=False)
    return out[::-1, :]


@dataclass
class BlockGroupExposure:
    """The hazard values of each block group in one scenario."""

    gust_kt: np.ndarray  # (n_bg,) area mean of the peak gust
    depth_m: np.ndarray  # (n_bg,) area mean of the flood depth over land
    p_deep: np.ndarray  # (n_bg,) area fraction with depth > 1 m
    p_shallow: np.ndarray  # (n_bg,) area fraction with 0.3 m < depth <= 1 m
    t_ts: np.ndarray  # (n_bg,) first hour of tropical-storm wind
    grid_out: np.ndarray  # (n_bg,) bool, gust > 100 mph


def exposure(grid: CountyGrid, bg_index: np.ndarray, bgs: gpd.GeoDataFrame, gust_kt: np.ndarray,
             depth_m: np.ndarray, t_ts: np.ndarray) -> BlockGroupExposure:
    """Return the hazard values of each block group."""
    n = len(bgs)
    flat = bg_index.ravel()
    ok = flat >= 0
    cnt = np.bincount(flat[ok], minlength=n).astype(float)

    def mean(field: np.ndarray) -> np.ndarray:
        s = np.bincount(flat[ok], weights=np.nan_to_num(field.ravel()[ok]), minlength=n)
        return s / np.maximum(cnt, 1)

    g = mean(gust_kt)
    d = mean(depth_m)
    deep = mean((depth_m > 1.0).astype(float))
    shallow = mean(((depth_m > 0.3) & (depth_m <= 1.0)).astype(float))
    tts = np.full(n, np.nan)
    tflat = t_ts.ravel()
    for i in np.unique(flat[ok]):
        vals = tflat[flat == i]
        if np.isfinite(vals).any():
            tts[i] = np.nanmin(vals)
    # Block groups smaller than one cell: sample the cell at the representative point.
    small = cnt == 0
    if small.any():
        for i in np.where(small)[0]:
            la, lo = float(bgs["lat"].iloc[i]), float(bgs["lon"].iloc[i])
            r = int(np.clip(np.searchsorted(grid.lat, la), 0, len(grid.lat) - 1))
            c = int(np.clip(np.searchsorted(grid.lon, lo), 0, len(grid.lon) - 1))
            g[i], d[i] = gust_kt[r, c], depth_m[r, c]
            deep[i] = float(depth_m[r, c] > 1.0)
            shallow[i] = float(0.3 < depth_m[r, c] <= 1.0)
            tts[i] = t_ts[r, c]
    return BlockGroupExposure(g, d, deep, shallow, tts, g * KT_TO_MPH > 100.0)


def p_major_damage(gust_kt: np.ndarray, depth_m: np.ndarray) -> np.ndarray:
    """Return the probability of major damage."""
    mph = gust_kt * KT_TO_MPH
    return np.clip(sigmoid(DAMAGE_SIGMOID_A * (mph - DAMAGE_GUST_MID_MPH)) * (1 + 0.5 * depth_m), 0.0, 1.0)


def injuries(pop: np.ndarray, p_major: np.ndarray, evac_frac: np.ndarray) -> np.ndarray:
    """Return the expected injuries."""
    return pop * p_major * INJURY_RATE * (1.0 - evac_frac)


def rescue_requests(pop: np.ndarray, p_deep: np.ndarray, evac_frac: np.ndarray) -> np.ndarray:
    """Return the expected number of persons that ask for rescue."""
    return pop * (1.0 - evac_frac) * p_deep * RESCUE_RATE
