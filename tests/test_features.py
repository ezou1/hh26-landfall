"""Test the StormState lag features in both Chalk modes with the same fixtures.

Local mode runs chalk/local_runtime.py. Remote mode registers the chalkpy resolvers and
calls the decorated resolver functions without a server. Both must give the same values.
"""

from datetime import UTC, datetime

import pandas as pd
import pytest

from landfall.predict.features import chalk_module, feature_matrix, state_columns


def _fixes() -> pd.DataFrame:
    times = pd.date_range("2022-09-26 00:00", periods=6, freq="6h", tz="UTC")
    rows = []
    for i, t in enumerate(times):
        rows.append({"storm_id": "TEST01", "time": t, "lat": 20.0 + 0.5 * i, "lon": -80.0 - 0.2 * i,
                     "vmax_kt": 50.0 + 5 * i, "pmin_mb": 1000.0 - 3 * i, "status": "TS", "source": "carq"})
    # A future fix that the point-in-time resolver must not read.
    rows.append({"storm_id": "TEST01", "time": times[-1] + pd.Timedelta(hours=6), "lat": 99.0, "lon": 99.0,
                 "vmax_kt": 999.0, "pmin_mb": 1.0, "status": "HU", "source": "carq"})
    df = pd.DataFrame(rows)
    df["id"] = df["storm_id"] + ":" + df["source"] + ":" + df["time"].astype(str)
    return df


NOW = datetime(2022, 9, 27, 6, tzinfo=UTC)  # the 6th fix


def _expected() -> dict[str, float]:
    return {"lat": 22.5, "lon": -81.0, "vmax_kt": 75.0, "dlat_6": 0.5, "dlon_6": -0.2, "dv_6": 5.0,
            "dlat_12": 1.0, "dlon_12": -0.4, "dv_12": 10.0, "dlat_24": 2.0, "dlon_24": -0.8, "dv_24": 20.0,
            "hours_since_genesis": 30.0}


def _local_state() -> dict[str, object]:
    lr = chalk_module("local_runtime")
    client = lr.LocalChalkClient(_fixes())
    return client.query(input={"storm_state.storm_id": "TEST01", "storm_state.fix_source": "carq"},
                        output=state_columns(), now=NOW)


class _ChalkFrame:
    """A stand-in for a chalk DataFrame argument: the resolver calls to_pandas()."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def to_pandas(self) -> pd.DataFrame:
        return self.df


def _remote_state() -> dict[str, float]:
    rz = chalk_module("resolvers")
    resolvers = rz.register_chalk_resolvers()
    res = resolvers["storm_state_from_fixes"]
    out = res.fn(_ChalkFrame(_fixes()), "carq", NOW)
    # The decorated function returns a StormState feature object; read its attribute values.
    vals = {}
    for k in _expected():
        vals[k] = float(getattr(out, k))
    return vals


@pytest.mark.parametrize("mode", ["local", "remote"])
def test_storm_state_lag_features(mode: str) -> None:
    state = _local_state() if mode == "local" else _remote_state()
    for k, v in _expected().items():
        assert float(state[k]) == pytest.approx(v, abs=1e-9), k


def test_point_in_time_never_reads_future_fix() -> None:
    state = _local_state()
    assert state["lat"] != 99.0 and state["vmax_kt"] < 999


def test_offline_query_matches_online_query() -> None:
    lr = chalk_module("local_runtime")
    client = lr.LocalChalkClient(_fixes())
    ds = client.offline_query(input={"storm_state.storm_id": ["TEST01"], "storm_state.fix_source": ["carq"]},
                              input_times=[NOW], output=state_columns() + ["tgt_dlat_6"])
    row = ds.to_pandas().iloc[0]
    online = _local_state()
    for k in ("lat", "dlat_12", "dv_24", "sst_proxy_c", "land_distance_km"):
        assert row[k] == pytest.approx(online[k])
    assert row["tgt_dlat_6"] == pytest.approx(99.0 - 22.5)  # the label resolver reads the next fix


def test_rollout_features_match_resolver() -> None:
    from landfall.predict.sample import history_from_fixes, history_from_state, state_frame

    online = _local_state()
    a = state_frame(history_from_fixes(_fixes(), NOW, "carq")).iloc[0]
    b = state_frame(history_from_state(online, NOW)).iloc[0]
    for k in ("lat", "dlat_6", "dlat_24", "dv_12", "heading_deg", "speed_kt", "hours_since_genesis"):
        assert a[k] == pytest.approx(float(online[k]), abs=1e-6), k
        assert b[k] == pytest.approx(float(online[k]), abs=1e-6), k
    assert feature_matrix(pd.DataFrame([a])).shape[1] == len(state_columns()) + 2
