"""Verify the ensemble, CLIPER-lite, and OFCL against the HURDAT2 truth for Ian.

The module uses the advisory times from 2022-09-23 to 2022-09-28, every 6 h.
For each advisory time, it does these steps:

1. Get the StormState from Chalk (CARQ fixes only).
2. Roll out N=500 members.
3. Measure the track and intensity error of the ensemble mean at 12, 24, 48, 72, and 96 h.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from landfall.config import (
    LAND_DECAY_PER_H,
    N_VERIFY_MEMBERS,
    OUT,
    SEED,
    STEP_H,
    STORM_ID,
    VERIFY_END,
    VERIFY_START,
    VMAX_MAX_KT,
    VMAX_MIN_KT,
)
from landfall.geoutil import haversine_km
from landfall.ingest import atcf
from landfall.ingest.geo import land_distance_km
from landfall.log import get_logger, metadata
from landfall.predict.features import ensure_fixes_cache, online_state
from landfall.predict.model import Predictor
from landfall.predict.sample import ensemble
from landfall.schemas import VerifySummary, write_model

LEADS = (12, 24, 48, 72, 96)
CLIMO_FILE = "cliper_climo"


def climatology(fixes: pd.DataFrame) -> dict[str, np.ndarray]:
    """Return the mean 6-h motion in 2.5-degree bins for August to October, 1980-2021."""
    h = fixes[(fixes["source"] == "hurdat2") & fixes["storm_id"].str.startswith("AL")].sort_values(["storm_id", "time"])
    h = h[(h["time"].dt.year >= 1980) & (h["time"].dt.year <= 2021)]
    h = h.assign(dlat=h.groupby("storm_id")["lat"].shift(-1) - h["lat"],
                 dlon=h.groupby("storm_id")["lon"].shift(-1) - h["lon"],
                 dt=(h.groupby("storm_id")["time"].shift(-1) - h["time"]).dt.total_seconds() / 3600)
    h = h[(h["dt"] == 6) & h["time"].dt.month.isin([8, 9, 10])]
    lat_bins = np.arange(0, 62.5, 2.5)
    lon_bins = np.arange(-110, 2.5, 2.5)
    i = np.clip(np.digitize(h["lat"], lat_bins) - 1, 0, len(lat_bins) - 2)
    j = np.clip(np.digitize(h["lon"], lon_bins) - 1, 0, len(lon_bins) - 2)
    s_lat = np.zeros((len(lat_bins) - 1, len(lon_bins) - 1))
    s_lon = np.zeros_like(s_lat)
    cnt = np.zeros_like(s_lat)
    np.add.at(s_lat, (i, j), h["dlat"].to_numpy())
    np.add.at(s_lon, (i, j), h["dlon"].to_numpy())
    np.add.at(cnt, (i, j), 1)
    glob_lat, glob_lon = h["dlat"].mean(), h["dlon"].mean()
    m_lat = np.where(cnt >= 5, s_lat / np.maximum(cnt, 1), glob_lat)
    m_lon = np.where(cnt >= 5, s_lon / np.maximum(cnt, 1), glob_lon)
    return {"lat_bins": lat_bins, "lon_bins": lon_bins, "dlat": m_lat, "dlon": m_lon}


def cliper_lite(state: dict[str, float], climo: dict[str, np.ndarray], n_steps: int) -> np.ndarray:
    """Return a CLIPER-lite track [step, (lat, lon, vmax)].

    The motion is the last 12-h motion (persistence) blended with the climatological drift.
    The weight of the drift grows from 0 to 1 over 72 h. The wind keeps the 12-h trend
    with an e-folding of 24 h, and it decays over land.
    """
    lat, lon, v = state["lat"], state["lon"], state["vmax_kt"]
    p_lat, p_lon = state["dlat_12"] / 2.0, state["dlon_12"] / 2.0
    dv = state["dv_12"] / 2.0
    out = [(lat, lon, v)]
    for k in range(n_steps):
        w = min(1.0, (k + 1) * STEP_H / 72.0)
        i = int(np.clip(np.digitize(lat, climo["lat_bins"]) - 1, 0, climo["dlat"].shape[0] - 1))
        j = int(np.clip(np.digitize(lon, climo["lon_bins"]) - 1, 0, climo["dlat"].shape[1] - 1))
        lat += (1 - w) * p_lat + w * climo["dlat"][i, j]
        lon += (1 - w) * p_lon + w * climo["dlon"][i, j]
        trend = dv * np.exp(-(k + 1) * STEP_H / 24.0)
        if land_distance_km(lon, lat) < 0:
            v = v * np.exp(-LAND_DECAY_PER_H * STEP_H) + min(trend, 0.0)
        else:
            v = v + trend
        v = float(np.clip(v, VMAX_MIN_KT, VMAX_MAX_KT))
        out.append((lat, lon, v))
    return np.array(out)


def _truth_at(truth: pd.DataFrame, t: pd.Timestamp) -> tuple[float, float, float] | None:
    if t in truth.index:
        r = truth.loc[t]
        return float(r["lat"]), float(r["lon"]), float(r["vmax_kt"])
    return None


def verify(n_members: int = N_VERIFY_MEMBERS) -> dict[str, object]:
    """Run the verification and write out/verify/errors.csv and out/verify/summary.json."""
    log = get_logger()
    pred = Predictor.load()
    fixes = ensure_fixes_cache()
    truth = fixes[(fixes["storm_id"] == STORM_ID) & (fixes["source"] == "hurdat2")].set_index("time")
    adeck = atcf.load()
    climo = climatology(fixes)
    carq_times = set(fixes[(fixes["storm_id"] == STORM_ID) & (fixes["source"] == "carq")]["time"])
    rows: list[dict[str, object]] = []
    ranks: list[int] = []
    spreads: dict[int, list[float]] = {ld: [] for ld in LEADS}
    t = VERIFY_START
    n_cases = 0
    while t <= VERIFY_END:
        ts = pd.Timestamp(t)
        if ts not in carq_times:
            t += timedelta(hours=6)
            continue
        n_cases += 1
        state = online_state(STORM_ID, t, "carq")
        ro = ensemble(pred, fixes, t, n_members, SEED)
        cl = cliper_lite(state, climo, max(LEADS) // STEP_H)
        of = atcf.ofcl(adeck, ts).set_index("tau")
        for ld in LEADS:
            vt = ts + pd.Timedelta(hours=ld)
            tr = _truth_at(truth, vt)
            if tr is None:
                continue
            k = ld // STEP_H
            alive = ~np.isnan(ro.lat[:, k])
            if alive.sum() >= n_members // 10:
                mlat, mlon = np.nanmean(ro.lat[:, k]), np.nanmean(ro.lon[:, k])
                mv = np.nanmean(ro.v[:, k])
                d_members = haversine_km(ro.lat[alive, k], ro.lon[alive, k], mlat, mlon)
                d_truth = float(haversine_km(tr[0], tr[1], mlat, mlon))
                ranks.append(int(np.sum(d_members < d_truth) * 10 // max(1, alive.sum())))
                spreads[ld].append(float(np.sqrt(np.mean(d_members**2))))
                rows.append({"advisory": ts, "lead_h": ld, "method": "model",
                             "track_km": float(haversine_km(mlat, mlon, tr[0], tr[1])),
                             "intensity_kt": abs(mv - tr[2])})
            rows.append({"advisory": ts, "lead_h": ld, "method": "cliper",
                         "track_km": float(haversine_km(cl[k, 0], cl[k, 1], tr[0], tr[1])),
                         "intensity_kt": abs(cl[k, 2] - tr[2])})
            if ld in of.index:
                o = of.loc[ld]
                rows.append({"advisory": ts, "lead_h": ld, "method": "ofcl",
                             "track_km": float(haversine_km(o["lat"], o["lon"], tr[0], tr[1])),
                             "intensity_kt": abs(float(o["vmax_kt"]) - tr[2])})
        t += timedelta(hours=6)
    err = pd.DataFrame(rows)
    (OUT / "verify").mkdir(parents=True, exist_ok=True)
    err.to_csv(OUT / "verify" / "errors.csv", index=False)
    methods: dict[str, dict[str, list[float | None]]] = {}
    for m in ("model", "cliper", "ofcl"):
        sub = err[err["method"] == m]
        methods[m] = {"track_km": [], "intensity_kt": [], "n": []}
        for ld in LEADS:
            s = sub[sub["lead_h"] == ld]
            methods[m]["track_km"].append(float(s["track_km"].mean()) if len(s) else None)
            methods[m]["intensity_kt"].append(float(s["intensity_kt"].mean()) if len(s) else None)
            methods[m]["n"].append(int(len(s)))
    hist = np.bincount(np.clip(ranks, 0, 9), minlength=10).tolist()
    summary = VerifySummary(
        metadata=metadata(),
        leads_h=list(LEADS),
        n_cases=n_cases,
        methods=methods,
        spread_km=[float(np.mean(spreads[ld])) if spreads[ld] else None for ld in LEADS],
        rank_hist={"bins": list(range(10)), "counts": hist},
        n_members=n_members,
    )
    write_model(OUT / "verify" / "summary.json", summary)
    log.info("verify", cases=n_cases,
             model_48=methods["model"]["track_km"][2], cliper_48=methods["cliper"]["track_km"][2],
             ofcl_48=methods["ofcl"]["track_km"][2])
    return json.loads(summary.model_dump_json())


def first_advisory() -> datetime:
    """Return the first CARQ time for the storm."""
    fixes = ensure_fixes_cache()
    return fixes[(fixes["storm_id"] == STORM_ID) & (fixes["source"] == "carq")]["time"].min().to_pydatetime()


if __name__ == "__main__":
    print(json.dumps(verify(), indent=1)[:3000])
