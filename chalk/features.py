"""Declare every feature that the LANDFALL predictor uses.

This file is the one feature definition for both Chalk modes. In remote mode, Chalk
deploys these classes. In local mode, chalk/local_runtime.py reads the same classes and
calls the same resolver bodies with pandas.
"""

from __future__ import annotations

from chalk.features import DataFrame, FeatureTime, features, has_many, has_one


@features
class StormFix:
    """One best-track or advisory fix for one storm."""

    id: str  # f"{storm_id}:{source}:{time.isoformat()}"
    storm_id: str
    time: FeatureTime
    lat: float
    lon: float
    vmax_kt: float
    pmin_mb: float | None
    status: str  # TD, TS, HU, EX, ...
    source: str  # "hurdat2" | "carq" | "ofcl"


@features
class Storm:
    """One storm and all of its fixes."""

    id: str  # e.g. "AL092022"
    name: str
    basin: str
    fixes: DataFrame[StormFix] = has_many(lambda: StormFix.storm_id == Storm.id)


@features
class StormState:
    """Point-in-time predictor inputs for one storm at one time."""

    id: str  # f"{storm_id}:{fix_source}:{time}"
    storm_id: str
    fix_source: str  # the fix source that the resolver can read: "hurdat2" or "carq"
    storm: Storm = has_one(lambda: Storm.id == StormState.storm_id)
    time: FeatureTime
    lat: float
    lon: float
    vmax_kt: float
    pmin_mb: float
    # lagged motion (6, 12, 24 h)
    dlat_6: float
    dlon_6: float
    dv_6: float
    dlat_12: float
    dlon_12: float
    dv_12: float
    dlat_24: float
    dlon_24: float
    dv_24: float
    heading_deg: float
    speed_kt: float
    day_of_year: int
    sst_proxy_c: float  # climatological SST proxy from data/static/sst_clim_2deg.npz
    land_distance_km: float  # signed distance to the coast; negative over land
    hours_since_genesis: float
    # targets (only populated for training rows, by an offline resolver)
    tgt_dlat_6: float | None
    tgt_dlon_6: float | None
    tgt_dv_6: float | None


STATE_FEATURES = [
    "lat", "lon", "vmax_kt", "pmin_mb",
    "dlat_6", "dlon_6", "dv_6", "dlat_12", "dlon_12", "dv_12", "dlat_24", "dlon_24", "dv_24",
    "heading_deg", "speed_kt", "day_of_year", "sst_proxy_c", "land_distance_km",
    "hours_since_genesis",
]
TARGET_FEATURES = ["tgt_dlat_6", "tgt_dlon_6", "tgt_dv_6"]
