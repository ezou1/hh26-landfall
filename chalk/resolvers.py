"""Resolvers for the LANDFALL features.

Each resolver body is a plain function with a name that ends in "_fn". The Chalk
decorators at the end of this file wrap the plain functions for remote mode.
The local runtime calls the plain functions directly. Thus both modes use one implementation.

The online resolver reads only the fixes at or before "now". The target resolver reads
fixes after the row time. Only the offline training query calls it.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
STATIC = ROOT / "data" / "static"
SST_FILE = STATIC / "sst_clim_2deg.npz"
FIXES_PARQUET = CACHE / "storm_fixes.parquet"

ATKINSON_A = 6.7
ATKINSON_B = 0.644
P_ENV_MB = 1010.0


def pressure_from_wind(vmax_kt: np.ndarray | float) -> np.ndarray:
    """Return a pressure estimate in mb from the wind speed (Atkinson-Holliday form)."""
    v = np.maximum(np.asarray(vmax_kt, dtype=float), 0.0)
    return P_ENV_MB - (v / ATKINSON_A) ** (1.0 / ATKINSON_B)


# ----------------------------------------------------------------- SST proxy
def build_sst_climatology(path: Path = SST_FILE) -> None:
    """Write the 2-degree monthly SST proxy grid.

    The proxy is 28 - 0.25 * max(0, |lat| - 10) degC with a seasonal term. It is not data.
    """
    lat = np.arange(-89.0, 90.0, 2.0)
    lon = np.arange(-179.0, 180.0, 2.0)
    month = np.arange(1, 13)
    la = lat[None, :, None]
    base = 28.0 - 0.25 * np.maximum(0.0, np.abs(la) - 10.0)
    # Northern hemisphere peaks in September, southern in March. Amplitude grows with latitude.
    phase = np.where(la >= 0, np.cos(2 * np.pi * (month[:, None, None] - 9) / 12.0),
                     np.cos(2 * np.pi * (month[:, None, None] - 3) / 12.0))
    amp = 0.06 * np.minimum(np.abs(la), 45.0)
    sst = base + amp * phase - amp
    sst = np.broadcast_to(sst, (12, len(lat), len(lon))).astype(np.float32)
    np.savez_compressed(path, lat=lat, lon=lon, sst=sst)


_SST: dict[str, np.ndarray] | None = None


def sst_proxy_vec(lat: np.ndarray, lon: np.ndarray, month: np.ndarray) -> np.ndarray:
    """Return the climatological SST proxy for arrays of points and months."""
    global _SST
    if _SST is None:
        if not SST_FILE.exists():
            build_sst_climatology()
        z = np.load(SST_FILE)
        _SST = {k: z[k] for k in ("lat", "lon", "sst")}
    lat_a = np.asarray(lat, dtype=float)
    lon_a = np.asarray(lon, dtype=float)
    i = np.clip(np.round((lat_a - _SST["lat"][0]) / 2.0).astype(int), 0, len(_SST["lat"]) - 1)
    j = np.clip(np.round((lon_a - _SST["lon"][0]) / 2.0).astype(int), 0, len(_SST["lon"]) - 1)
    m = np.asarray(month, dtype=int) - 1
    return _SST["sst"][m, i, j].astype(float)


def sst_proxy_c_fn(lat: float, lon: float, time: datetime) -> float:
    """Return the climatological SST proxy for a point and a month."""
    return float(sst_proxy_vec(np.array([lat]), np.array([lon]), np.array([time.month]))[0])


# ----------------------------------------------------------------- fixes
def load_storm_fixes_fn() -> pd.DataFrame:
    """Return every StormFix row from the parquet cache (HURDAT2, CARQ, and OFCL)."""
    return pd.read_parquet(FIXES_PARQUET)


def build_storm_fixes(hurdat: pd.DataFrame, adeck: pd.DataFrame) -> pd.DataFrame:
    """Return the StormFix frame from the HURDAT2 and a-deck frames."""
    h = hurdat[hurdat["time"].dt.minute.eq(0) & hurdat["time"].dt.hour.isin([0, 6, 12, 18])].copy()
    h = h.drop_duplicates(["storm_id", "time"])
    h["source"] = "hurdat2"
    c = adeck[(adeck["tech"] == "CARQ") & (adeck["tau"] == 0)].copy()
    c["source"] = "carq"
    o = adeck[adeck["tech"] == "OFCL"].copy()
    o["source"] = "ofcl"
    cols = ["storm_id", "time", "lat", "lon", "vmax_kt", "pmin_mb", "status", "source"]
    out = pd.concat([h[cols], c[cols]], ignore_index=True)
    out["id"] = out["storm_id"] + ":" + out["source"] + ":" + out["time"].dt.strftime("%Y-%m-%dT%H:%M")
    o_cols = cols + ["base_time", "tau"]
    o = o[o_cols].copy()
    o["id"] = (o["storm_id"] + ":ofcl:" + o["base_time"].dt.strftime("%Y-%m-%dT%H:%M") + ":" + o["tau"].astype(str))
    out = pd.concat([out, o], ignore_index=True)
    return out


# ----------------------------------------------------------------- state
def _interp_at(times: np.ndarray, values: np.ndarray, t: float) -> float:
    """Return the value at time t by linear interpolation. Clamp to the first fix."""
    if t <= times[0]:
        return float(values[0])
    return float(np.interp(t, times, values))


def storm_state_from_fixes_fn(fixes: pd.DataFrame, now: datetime, fix_source: str) -> dict[str, float]:
    """Compute the StormState features from the fixes at or before now.

    The function never reads a fix after now. It returns an empty dict if no fix exists.
    """
    f = fixes[(fixes["source"] == fix_source)]
    now_ts = pd.Timestamp(now)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    f = f[f["time"] <= now_ts].sort_values("time")
    if f.empty:
        return {}
    t = (f["time"].astype("int64").to_numpy() // 10**9) / 3600.0
    lat = f["lat"].to_numpy(dtype=float)
    lon = f["lon"].to_numpy(dtype=float)
    v = f["vmax_kt"].to_numpy(dtype=float)
    p = f["pmin_mb"].to_numpy(dtype=float)
    p = np.where(np.isnan(p), pressure_from_wind(v), p)
    tn = now_ts.value / 1e9 / 3600.0
    cur_lat, cur_lon, cur_v = _interp_at(t, lat, tn), _interp_at(t, lon, tn), _interp_at(t, v, tn)
    cur_p = _interp_at(t, p, tn)
    out: dict[str, float] = {"lat": cur_lat, "lon": cur_lon, "vmax_kt": cur_v, "pmin_mb": cur_p}
    for lag in (6, 12, 24):
        out[f"dlat_{lag}"] = cur_lat - _interp_at(t, lat, tn - lag)
        out[f"dlon_{lag}"] = cur_lon - _interp_at(t, lon, tn - lag)
        out[f"dv_{lag}"] = cur_v - _interp_at(t, v, tn - lag)
    dy = out["dlat_6"] * 60.0
    dx = out["dlon_6"] * 60.0 * math.cos(math.radians(cur_lat))
    out["heading_deg"] = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    out["speed_kt"] = math.hypot(dx, dy) / 6.0
    out["day_of_year"] = int(now_ts.dayofyear)
    out["hours_since_genesis"] = float(tn - t[0])
    return out


def storm_targets_fn(fixes: pd.DataFrame, time: datetime, fix_source: str) -> dict[str, float | None]:
    """Return the change over the next 6 h. This offline resolver reads the future fix."""
    f = fixes[fixes["source"] == fix_source].sort_values("time")
    ts = pd.Timestamp(time)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    now = f[f["time"] == ts]
    nxt = f[f["time"] == ts + pd.Timedelta(hours=6)]
    if now.empty or nxt.empty:
        return {"tgt_dlat_6": None, "tgt_dlon_6": None, "tgt_dv_6": None}
    return {
        "tgt_dlat_6": float(nxt["lat"].iloc[0] - now["lat"].iloc[0]),
        "tgt_dlon_6": float(nxt["lon"].iloc[0] - now["lon"].iloc[0]),
        "tgt_dv_6": float(nxt["vmax_kt"].iloc[0] - now["vmax_kt"].iloc[0]),
    }


def land_distance_km_fn(lat: float, lon: float) -> float:
    """Return the signed distance to the coast in km. The value is negative over land."""
    import sys

    sys.path.insert(0, str(ROOT))
    from landfall.ingest.geo import land_distance_km

    return float(land_distance_km(lon, lat))


# ----------------------------------------------------------------- Chalk decorators
def register_chalk_resolvers() -> dict[str, object]:
    """Wrap the plain functions with the Chalk decorators and return the resolvers.

    Chalk remote mode imports this module and calls this function. The function only
    builds decorator objects. It does not contact a Chalk server.
    """
    import features as fx  # the Chalk project root is chalk/

    from chalk import Now, offline, online
    from chalk.features import DataFrame, Features

    StormFix, StormState = fx.StormFix, fx.StormState

    @offline
    def load_storm_fixes() -> DataFrame[
        StormFix.id, StormFix.storm_id, StormFix.time, StormFix.lat, StormFix.lon,
        StormFix.vmax_kt, StormFix.pmin_mb, StormFix.status, StormFix.source,
    ]:
        return DataFrame(load_storm_fixes_fn())

    @online
    def storm_state_from_fixes(
        fixes: StormState.storm.fixes, fix_source: StormState.fix_source, now: Now
    ) -> Features[
        StormState.lat, StormState.lon, StormState.vmax_kt, StormState.pmin_mb,
        StormState.dlat_6, StormState.dlon_6, StormState.dv_6,
        StormState.dlat_12, StormState.dlon_12, StormState.dv_12,
        StormState.dlat_24, StormState.dlon_24, StormState.dv_24,
        StormState.heading_deg, StormState.speed_kt, StormState.day_of_year,
        StormState.hours_since_genesis,
    ]:
        out = storm_state_from_fixes_fn(fixes.to_pandas(), now, fix_source)
        return StormState(**out)

    @online
    def sst_proxy(lat: StormState.lat, lon: StormState.lon, now: Now) -> StormState.sst_proxy_c:
        return sst_proxy_c_fn(lat, lon, now)

    @online
    def land_distance(lat: StormState.lat, lon: StormState.lon) -> StormState.land_distance_km:
        return land_distance_km_fn(lat, lon)

    @offline
    def storm_targets(
        fixes: StormState.storm.fixes, fix_source: StormState.fix_source, time: StormState.time
    ) -> Features[StormState.tgt_dlat_6, StormState.tgt_dlon_6, StormState.tgt_dv_6]:
        return StormState(**storm_targets_fn(fixes.to_pandas(), time, fix_source))

    return {
        "load_storm_fixes": load_storm_fixes,
        "storm_state_from_fixes": storm_state_from_fixes,
        "sst_proxy": sst_proxy,
        "land_distance": land_distance,
        "storm_targets": storm_targets,
    }
