"""Run the LANDFALL resolvers in-process with pandas when CHALK_MODE=local.

The LocalChalkClient has the same two query methods that the predictor uses on the
real ChalkClient: offline_query for point-in-time training and verification frames,
and query for one online lookup at one time. It calls the plain resolver bodies in
chalk/resolvers.py, so both modes give the same values.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import pandas as pd
import resolvers as rz
from features import STATE_FEATURES, TARGET_FEATURES


def _bare(name: object) -> str:
    """Return the bare feature name, for example "lat" for "storm_state.lat"."""
    s = str(name)
    return s.split(".")[-1]


class LocalDataset:
    """The result of a local offline query."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def to_pandas(self) -> pd.DataFrame:
        """Return the result as a pandas frame."""
        return self._df.copy()

    def get_data_as_pandas(self) -> pd.DataFrame:
        """Return the result as a pandas frame (the name that chalkpy uses)."""
        return self.to_pandas()


class LocalChalkClient:
    """An in-process stand-in for ChalkClient that uses the same resolver bodies."""

    def __init__(self, fixes: pd.DataFrame | None = None) -> None:
        self.fixes = rz.load_storm_fixes_fn() if fixes is None else fixes
        self._groups = {
            k: g.sort_values("time") for k, g in self.fixes.groupby(["storm_id", "source"], sort=False)
        }

    def _fixes_for(self, storm_id: str, source: str) -> pd.DataFrame:
        return self._groups.get((storm_id, source), self.fixes.iloc[0:0])

    def resolve_row(
        self, storm_id: str, fix_source: str, now: datetime, outputs: Iterable[str]
    ) -> dict[str, object]:
        """Resolve the requested StormState features for one storm at one time."""
        outs = {_bare(o) for o in outputs}
        fixes = self._fixes_for(storm_id, fix_source)
        row: dict[str, object] = {
            "id": f"{storm_id}:{fix_source}:{pd.Timestamp(now).isoformat()}",
            "storm_id": storm_id,
            "fix_source": fix_source,
            "time": pd.Timestamp(now),
        }
        state = rz.storm_state_from_fixes_fn(fixes, now, fix_source)
        if not state:
            return row
        row.update(state)
        if "sst_proxy_c" in outs or "*" in outs:
            row["sst_proxy_c"] = rz.sst_proxy_c_fn(state["lat"], state["lon"], pd.Timestamp(now))
        if "land_distance_km" in outs or "*" in outs:
            row["land_distance_km"] = rz.land_distance_km_fn(state["lat"], state["lon"])
        if outs & set(TARGET_FEATURES):
            row.update(rz.storm_targets_fn(fixes, now, fix_source))
        return row

    def offline_query(
        self,
        input: dict[str, list[object]],  # noqa: A002 - same name as chalkpy
        output: list[object],
        input_times: list[datetime] | None = None,
        **_: object,
    ) -> LocalDataset:
        """Return point-in-time rows. Each input row resolves at its own input time."""
        cols = {_bare(k): list(v) for k, v in input.items()}
        n = len(cols["storm_id"])
        sources = cols.get("fix_source", ["hurdat2"] * n)
        times = input_times if input_times is not None else cols["time"]
        outs = [_bare(o) for o in output]
        rows = [self.resolve_row(cols["storm_id"][i], sources[i], times[i], outs) for i in range(n)]
        df = pd.DataFrame(rows)
        keep = ["id", "storm_id", "fix_source", "time"] + [
            c for c in outs if c in df.columns and c not in ("id", "storm_id", "fix_source", "time")
        ]
        return LocalDataset(df[keep])

    def query(
        self, input: dict[str, object], output: list[object], now: datetime, **_: object  # noqa: A002
    ) -> dict[str, object]:
        """Return the online StormState features for one storm as of now."""
        cols = {_bare(k): v for k, v in input.items()}
        return self.resolve_row(
            str(cols["storm_id"]), str(cols.get("fix_source", "carq")), now, [_bare(o) for o in output]
        )


ALL_OUTPUTS = STATE_FEATURES + TARGET_FEATURES
