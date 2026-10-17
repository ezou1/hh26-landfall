"""Build the point-in-time training frame with Chalk, train the MLP, and fit the residual bank.

The training frame holds one StormState row for each 6-hourly HURDAT2 fix of every
Atlantic storm from 1980 to 2021. Each row resolves with "now" equal to the fix time.
The model trains on 1980-2014 and the residual bank comes from rollouts on 2015-2021.
Ian (2022) is not in either split.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import torch
from torch import nn

from landfall.config import (
    CACHE,
    LEAD_BUCKETS_H,
    MLP_BAG,
    MLP_EPOCHS,
    MLP_INPUT_NOISE,
    SEED,
    TRAIN_YEARS,
)
from landfall.log import get_logger, stage
from landfall.predict.features import (
    ensure_fixes_cache,
    feature_matrix,
    storm_state_frame,
    target_columns,
)
from landfall.predict.model import MODEL_FILE, BaggedMLP, Predictor, StepMLP, bucket_of_step
from landfall.predict.sample import LAG_STEPS, History, rollout

TRAIN_FILE = CACHE / "train.parquet"
VAL_START_YEAR = 2015
N_STEPS = 20


def build_training_frame(refresh: bool = False) -> pd.DataFrame:
    """Return the training frame. Query Chalk and cache the result if necessary."""
    if TRAIN_FILE.exists() and not refresh:
        return pd.read_parquet(TRAIN_FILE)
    fixes = ensure_fixes_cache()
    h = fixes[(fixes["source"] == "hurdat2") & fixes["storm_id"].str.startswith("AL")]
    years = h["time"].dt.year
    h = h[(years >= TRAIN_YEARS[0]) & (years <= TRAIN_YEARS[1])]
    with stage("train.offline_query", rows=len(h)):
        df = storm_state_frame(h["storm_id"].tolist(), list(h["time"]), "hurdat2", with_targets=True)
    df = df.dropna(subset=target_columns())
    df["year"] = pd.to_datetime(df["time"], utc=True).dt.year
    df.to_parquet(TRAIN_FILE)
    return df


def _fit_bag(x_tr: np.ndarray, y_tr: np.ndarray, x_va: np.ndarray, y_va: np.ndarray) -> tuple[nn.Module, dict[str, object]]:
    """Train MLP_BAG members with different seeds and return their mean."""
    if MLP_BAG <= 1:
        return _fit(x_tr, y_tr, x_va, y_va, SEED)
    bag = BaggedMLP(x_tr.shape[1], MLP_BAG)
    infos = []
    for i in range(MLP_BAG):
        net, info = _fit(x_tr, y_tr, x_va, y_va, SEED + 1000 * i)
        bag.members[i].load_state_dict(net.state_dict())
        infos.append(info)
    bag.eval()
    with torch.no_grad():
        vl = float(nn.functional.mse_loss(bag(torch.from_numpy(x_va)), torch.from_numpy(y_va)))
    return bag, {"device": infos[0]["device"], "best_val_mse_std": vl, "epochs": MLP_EPOCHS,
                 "bag": MLP_BAG, "member_val_mse_std": [i["best_val_mse_std"] for i in infos],
                 "input_noise": MLP_INPUT_NOISE}


def _fit(x_tr: np.ndarray, y_tr: np.ndarray, x_va: np.ndarray, y_va: np.ndarray,
         seed: int = SEED) -> tuple[StepMLP, dict[str, object]]:
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, torch.get_num_threads()))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = StepMLP(x_tr.shape[1]).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=MLP_EPOCHS)
    loss_fn = nn.MSELoss()
    xt, yt = torch.from_numpy(x_tr).to(device), torch.from_numpy(y_tr).to(device)
    xv, yv = torch.from_numpy(x_va).to(device), torch.from_numpy(y_va).to(device)
    best, best_state, history = 1e9, None, []
    g = torch.Generator(device="cpu").manual_seed(seed)
    for _ in range(MLP_EPOCHS):
        net.train()
        perm = torch.randperm(len(xt), generator=g).to(device)
        for i in range(0, len(xt), 512):
            idx = perm[i : i + 512]
            opt.zero_grad()
            xb = xt[idx]
            if MLP_INPUT_NOISE > 0:
                xb = xb + MLP_INPUT_NOISE * torch.randn(xb.shape, generator=g).to(device)
            loss = loss_fn(net(xb), yt[idx])
            loss.backward()
            opt.step()
        sched.step()
        net.eval()
        with torch.no_grad():
            vl = float(loss_fn(net(xv), yv))
        history.append(vl)
        if vl < best:
            best = vl
            best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
    assert best_state is not None
    net = net.cpu()
    net.load_state_dict(best_state)
    net.eval()
    return net, {"device": device, "best_val_mse_std": best, "epochs": MLP_EPOCHS, "val_curve": history}


def validation_cases(fixes: pd.DataFrame, storms: list[str]) -> tuple[History, np.ndarray]:
    """Return the start histories and the truth tracks [case, step, 3] of the validation storms."""
    hist: list[History] = []
    truth: list[np.ndarray] = []
    for sid in storms:
        f = fixes[(fixes["storm_id"] == sid) & (fixes["source"] == "hurdat2")].sort_values("time")
        if len(f) < 3:
            continue
        lat, lon = f["lat"].to_numpy(float), f["lon"].to_numpy(float)
        v = f["vmax_kt"].to_numpy(float)
        p = f["pmin_mb"].to_numpy(float)
        p = np.where(np.isnan(p), 1010 - (np.maximum(v, 0) / 6.7) ** (1 / 0.644), p)
        t = (f["time"].astype("int64").to_numpy() // 10**9) / 3600.0
        if np.any(np.diff(t) != 6):
            # resample to a strict 6-h grid
            grid = np.arange(t[0], t[-1] + 0.1, 6.0)
            lat, lon, v, p = (np.interp(grid, t, a) for a in (lat, lon, v, p))
            t = grid
        for i in range(len(t) - 1):
            idx = np.maximum(np.arange(i - LAG_STEPS, i + 1), 0)
            hist.append(History(lat[idx][None], lon[idx][None], v[idx][None], p[idx][None],
                                np.array([t[i]]), np.array([t[0]])))
            tr = np.full((N_STEPS + 1, 3), np.nan)
            j = np.arange(i, min(len(t), i + N_STEPS + 1))
            tr[: len(j)] = np.stack([lat[j], lon[j], v[j]], axis=1)
            truth.append(tr)
    h = History(*(np.concatenate([getattr(x, a) for x in hist]) for a in
                  ("lat", "lon", "v", "p", "t_now_h", "genesis_h")))
    return h, np.stack(truth)


def residual_bank(pred: Predictor, h: History, tr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return rollout residuals [case, step, 3] and the rolled latitude [case, step].

    For each validation fix, the function rolls the model forward without noise. The
    residual of step k is the true 6-h change minus the model change at the rolled state.
    """
    ro = rollout(pred, h, N_STEPS, stochastic=False)
    true_step = tr[:, 1:] - tr[:, :-1]  # (C, N_STEPS, 3)
    res = true_step - ro.pred
    res[~ro.alive[:, 1:]] = np.nan
    return res.astype(np.float32), ro.lat[:, :-1].astype(np.float32)


def _subset(h: History, idx: np.ndarray) -> History:
    return History(h.lat[idx], h.lon[idx], h.v[idx], h.p[idx], h.t_now_h[idx], h.genesis_h[idx])


def calibrate_scale(pred: Predictor, h: History, tr: np.ndarray, members: int = 48,
                    iterations: int = 6) -> list[dict[str, float]]:
    """Scale the residuals of each bucket so that the ensemble spread matches the error.

    The function uses only the validation storms (2015-2021). For a calibrated ensemble,
    the RMS spread about the ensemble mean equals the RMS error of the ensemble mean.
    """
    from landfall.geoutil import haversine_km

    rng = np.random.default_rng(SEED)
    idx = np.arange(0, h.size, 8)
    sub = _subset(h, idx).repeat(members)
    truth = tr[idx]
    rows: list[dict[str, float]] = []
    for it in range(iterations):
        ro = rollout(pred, sub, N_STEPS, rng=rng, stochastic=True)
        c = len(idx)
        lat = ro.lat.reshape(c, members, -1)
        lon = ro.lon.reshape(c, members, -1)
        errs: list[list[float]] = [[] for _ in LEAD_BUCKETS_H]
        sprs: list[list[float]] = [[] for _ in LEAD_BUCKETS_H]
        for k in range(1, N_STEPS + 1):
            b = bucket_of_step(k - 1)
            alive = (~np.isnan(lat[:, :, k])).sum(1) >= members // 2
            ok = alive & ~np.isnan(truth[:, k, 0])
            if ok.sum() < 10:
                continue
            mlat = np.nanmean(lat[ok, :, k], axis=1)
            mlon = np.nanmean(lon[ok, :, k], axis=1)
            e = haversine_km(mlat, mlon, truth[ok, k, 0], truth[ok, k, 1])
            s = haversine_km(lat[ok, :, k], lon[ok, :, k], mlat[:, None], mlon[:, None])
            errs[b] += e.tolist()
            sprs[b] += s[~np.isnan(s)].tolist()
        # Median distances: for a 2-D Gaussian, both medians equal 1.18 sigma.
        med_e = np.array([np.median(x) if x else np.nan for x in errs])
        med_s = np.array([np.median(x) if x else np.nan for x in sprs])
        ratio = np.where(np.isnan(med_e) | np.isnan(med_s), 1.0, med_e / np.maximum(med_s, 1e-6))
        rows = [{"lead_h": float(LEAD_BUCKETS_H[b]), "median_err_km": float(med_e[b]),
                 "median_spread_km": float(med_s[b]), "scale": float(pred.bucket_scale[b])}
                for b in range(len(LEAD_BUCKETS_H))]
        get_logger().info("calibrate", iteration=it, ratio=np.round(ratio, 3).tolist())
        pred.bucket_scale = np.clip(pred.bucket_scale * ratio**0.8, 0.05, 3.0).astype(np.float32)
    return rows


def validation_skill(pred: Predictor, h: History, tr: np.ndarray, fixes: pd.DataFrame,
                     members: int = 32) -> list[dict[str, float]]:
    """Return the mean track error of the model and of CLIPER-lite on the validation storms."""
    from landfall.geoutil import haversine_km
    from landfall.predict.sample import state_frame
    from landfall.predict.verify import climatology, cliper_lite

    idx = np.arange(0, h.size, 4)
    sub = _subset(h, idx)
    truth = tr[idx]
    det = rollout(pred, sub, 12, stochastic=False)
    ens = rollout(pred, sub.repeat(members), 12, rng=np.random.default_rng(SEED), stochastic=True)
    elat = np.nanmean(ens.lat.reshape(len(idx), members, -1), axis=1)
    elon = np.nanmean(ens.lon.reshape(len(idx), members, -1), axis=1)
    climo = climatology(fixes)
    states = state_frame(sub).to_dict("records")
    cl = np.stack([cliper_lite(s, climo, 12) for s in states])
    rows = []
    for lead in (24, 48, 72):
        k = lead // 6
        ok = ~np.isnan(truth[:, k, 0]) & ~np.isnan(det.lat[:, k]) & ~np.isnan(elat[:, k])
        rows.append({
            "lead_h": float(lead), "n": float(ok.sum()),
            "model_det_km": float(np.mean(haversine_km(det.lat[ok, k], det.lon[ok, k], truth[ok, k, 0], truth[ok, k, 1]))),
            "model_ens_km": float(np.mean(haversine_km(elat[ok, k], elon[ok, k], truth[ok, k, 0], truth[ok, k, 1]))),
            "cliper_km": float(np.mean(haversine_km(cl[ok, k, 0], cl[ok, k, 1], truth[ok, k, 0], truth[ok, k, 1]))),
        })
    return rows


def train(refresh: bool = False) -> Predictor:
    """Train the predictor and save it to data/cache/model.pt."""
    log = get_logger()
    if MODEL_FILE.exists() and not refresh:
        return Predictor.load()
    t_start = time.perf_counter()
    df = build_training_frame()
    x = feature_matrix(df)
    y = df[target_columns()].to_numpy(np.float32)
    tr = (df["year"] < VAL_START_YEAR).to_numpy()
    x_mean, x_std = x[tr].mean(0), x[tr].std(0) + 1e-6
    y_mean, y_std = y[tr].mean(0), y[tr].std(0) + 1e-6
    xs = ((x - x_mean) / x_std).astype(np.float32)
    ys = ((y - y_mean) / y_std).astype(np.float32)
    with stage("train.fit", rows=int(tr.sum()), val_rows=int((~tr).sum())):
        net, info = _fit_bag(xs[tr], ys[tr], xs[~tr], ys[~tr])
    pred = Predictor(net, x_mean, x_std, y_mean, y_std, info=info)
    pv = pred.predict(x[~tr])
    one_step_mae = np.abs(pv - y[~tr]).mean(0)
    fixes = ensure_fixes_cache()
    val_storms = sorted(df.loc[~tr, "storm_id"].unique())
    with stage("train.residual_bank", storms=len(val_storms)):
        vh, vtr = validation_cases(fixes, val_storms)
        res, res_lat = residual_bank(pred, vh, vtr)
        pred.residual_lat = res_lat
    bucket_std = np.ones((len(LEAD_BUCKETS_H), 3), np.float32)
    bucket_rows = []
    for b in range(len(LEAD_BUCKETS_H)):
        steps = [k for k in range(res.shape[1]) if bucket_of_step(k) == b]
        r = res[:, steps].reshape(-1, 3)
        r = r[~np.isnan(r).any(axis=1)]
        if len(r):
            bucket_std[b] = r.std(0)
        bucket_rows.append({"lead_h": LEAD_BUCKETS_H[b], "n": len(r),
                            "std_dlat": float(bucket_std[b, 0]), "std_dlon": float(bucket_std[b, 1]),
                            "std_dv": float(bucket_std[b, 2])})
    pred.residuals = res
    pred.bucket_std = bucket_std
    pred._pools = None
    with stage("train.calibrate"):
        calib = calibrate_scale(pred, vh, vtr)
    with stage("train.validation_skill"):
        skill = validation_skill(pred, vh, vtr, fixes)
    for row in skill:
        log.info("validation skill", **row)
    pred.info.update({
        "validation_skill": skill,
        "calibration": calib,
        "bucket_scale": [float(s) for s in pred.bucket_scale],
        "train_rows": int(tr.sum()), "val_rows": int((~tr).sum()),
        "one_step_mae": {"dlat": float(one_step_mae[0]), "dlon": float(one_step_mae[1]), "dv": float(one_step_mae[2])},
        "residual_buckets": bucket_rows, "n_cases": int(res.shape[0]),
        "train_seconds": round(time.perf_counter() - t_start, 1),
    })
    pred.save()
    log.info("model trained", **{k: v for k, v in pred.info.items() if k not in ("val_curve", "residual_buckets")})
    for row in bucket_rows:
        log.info("residual bucket", **row)
    return pred


if __name__ == "__main__":
    train(refresh=True)
