"""Give the predictor one interface to the Chalk feature layer in both modes.

CHALK_MODE=local uses chalk/local_runtime.py. CHALK_MODE=remote uses ChalkClient with
the credentials in the environment. If the remote query fails, the module logs a
WARNING, records a fallback, and uses the local runtime.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime
from functools import lru_cache
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

from landfall.config import CHALK_MODE, ROOT
from landfall.ingest import atcf, hurdat2
from landfall.log import get_logger, record_fallback

CHALK_DIR = ROOT / "chalk"


def chalk_module(name: str) -> ModuleType:
    """Import a module from the chalk/ project folder (features, resolvers, local_runtime)."""
    if str(CHALK_DIR) not in sys.path:
        sys.path.insert(0, str(CHALK_DIR))
    return importlib.import_module(name)


def ensure_fixes_cache(refresh: bool = False) -> pd.DataFrame:
    """Build data/cache/storm_fixes.parquet from HURDAT2 and the a-deck if necessary."""
    rz = chalk_module("resolvers")
    if rz.FIXES_PARQUET.exists() and not refresh:
        return pd.read_parquet(rz.FIXES_PARQUET)
    fixes = rz.build_storm_fixes(hurdat2.load(), atcf.load())
    fixes.to_parquet(rz.FIXES_PARQUET)
    if not rz.SST_FILE.exists():
        rz.build_sst_climatology()
    return fixes


def state_columns() -> list[str]:
    """Return the StormState input feature names in model order."""
    return list(chalk_module("features").STATE_FEATURES)


def target_columns() -> list[str]:
    """Return the StormState target feature names."""
    return list(chalk_module("features").TARGET_FEATURES)


@lru_cache(maxsize=2)
def get_client(mode: str = CHALK_MODE) -> Any:
    """Return a Chalk client for the mode: ChalkClient (remote) or LocalChalkClient (local)."""
    if mode == "remote":
        try:
            from chalk.client import ChalkClient

            return ChalkClient(
                client_id=os.environ.get("CHALK_CLIENT_ID"),
                client_secret=os.environ.get("CHALK_CLIENT_SECRET"),
                environment=os.environ.get("CHALK_ENVIRONMENT") or None,
            )
        except Exception as exc:  # noqa: BLE001
            record_fallback("chalk_remote", f"ChalkClient init failed; local runtime used: {exc}")
    ensure_fixes_cache()
    return chalk_module("local_runtime").LocalChalkClient()


def state_id(storm_id: str, fix_source: str, t: datetime) -> str:
    """Return the StormState primary key: storm id, fix source, and time."""
    return f"{storm_id}:{fix_source}:{pd.Timestamp(t).isoformat()}"


def _strip(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={c: str(c).split(".")[-1] for c in df.columns})


def storm_state_frame(
    storm_ids: list[str],
    times: list[datetime],
    fix_source: str | list[str] = "hurdat2",
    with_targets: bool = False,
    mode: str = CHALK_MODE,
) -> pd.DataFrame:
    """Return point-in-time StormState rows: one row for each (storm, time) input."""
    src = [fix_source] * len(storm_ids) if isinstance(fix_source, str) else list(fix_source)
    outputs = state_columns() + (target_columns() if with_targets else [])
    client = get_client(mode)
    if mode == "remote" and not hasattr(client, "resolve_row"):
        try:
            fx = chalk_module("features")
            ids = [state_id(s, f, t) for s, f, t in zip(storm_ids, src, times, strict=True)]
            ds = client.offline_query(
                input={fx.StormState.id: ids, fx.StormState.storm_id: storm_ids, fx.StormState.fix_source: src},
                input_times=list(times),
                output=[fx.StormState.id] + [getattr(fx.StormState, c) for c in outputs],
                recompute_features=True,
            )
            out = _strip(ds.get_data_as_pandas())
            # Put back the input columns, in the input order, through the primary key.
            keys = pd.DataFrame({"id": ids, "storm_id": storm_ids, "fix_source": src,
                                 "time": pd.to_datetime(list(times), utc=True)})
            out = keys.merge(out.drop(columns=[c for c in ("storm_id", "fix_source", "time") if c in out]),
                             on="id", how="left")
            if out[outputs[0]].isna().all():
                raise RuntimeError("offline query returned no feature values")
            return out
        except Exception as exc:  # noqa: BLE001
            record_fallback("chalk_remote", f"offline_query failed; local runtime used: {exc}")
            client = get_client("local")
    ds = client.offline_query(
        input={"storm_state.storm_id": storm_ids, "storm_state.fix_source": src},
        input_times=list(times),
        output=outputs,
    )
    return _strip(ds.to_pandas())


def online_state(storm_id: str, now: datetime, fix_source: str = "carq", mode: str = CHALK_MODE) -> dict[str, Any]:
    """Return the online StormState for one storm as of now (the replay input)."""
    client = get_client(mode)
    outputs = state_columns()
    if mode == "remote" and not hasattr(client, "resolve_row"):
        try:
            fx = chalk_module("features")
            res = client.query(
                input={fx.StormState.id: state_id(storm_id, fix_source, now),
                       fx.StormState.storm_id: storm_id, fx.StormState.fix_source: fix_source},
                output=[getattr(fx.StormState, c) for c in outputs],
                now=now,
            )
            if res.errors:
                raise RuntimeError("; ".join(str(getattr(e, "message", e)) for e in res.errors))
            return {str(k).split(".")[-1]: v for k, v in res.to_dict().items()}
        except Exception as exc:  # noqa: BLE001
            record_fallback("chalk_remote", f"online query failed; local runtime used: {exc}")
            client = get_client("local")
    return client.query(
        input={"storm_state.storm_id": storm_id, "storm_state.fix_source": fix_source},
        output=outputs,
        now=now,
    )


def feature_matrix(df: pd.DataFrame) -> np.ndarray:
    """Return the model input matrix from StormState rows.

    The function encodes the heading and the day of the year as sine and cosine.
    """
    cols = state_columns()
    x = df[cols].astype(float).copy()
    h = np.radians(x.pop("heading_deg"))
    d = 2 * np.pi * x.pop("day_of_year") / 365.25
    x["heading_sin"] = np.sin(h)
    x["heading_cos"] = np.cos(h)
    x["doy_sin"] = np.sin(d)
    x["doy_cos"] = np.cos(d)
    x["land_distance_km"] = np.clip(x["land_distance_km"], -300.0, 600.0)
    x["hours_since_genesis"] = np.clip(x["hours_since_genesis"], 0.0, 480.0)
    return x.to_numpy(dtype=np.float32)


def log_mode() -> None:
    """Log the Chalk mode in use."""
    get_logger().info("chalk mode", mode=CHALK_MODE)
