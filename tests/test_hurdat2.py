"""Test the HURDAT2 and ATCF parsers on bundled excerpts."""

from pathlib import Path

import numpy as np
import pandas as pd

from landfall.ingest import atcf, hurdat2

FIX = Path(__file__).parent / "fixtures"


def test_hurdat2_parse_ian_excerpt() -> None:
    df = hurdat2.parse((FIX / "hurdat2_ian_excerpt.txt").read_text())
    ian = df[df.storm_id == "AL092022"]
    assert ian["name"].iloc[0] == "IAN"
    assert len(ian) == 40
    lf = ian[(ian.record == "L") & (ian.time == pd.Timestamp("2022-09-28 19:05", tz="UTC"))].iloc[0]
    assert lf.lat == 26.7 and lf.lon == -82.2 and lf.vmax_kt == 130 and lf.pmin_mb == 941
    assert lf.r34_ne == 130 and lf.rmw_nm == 20
    assert set(ian.status) >= {"LO", "TS", "HU"}


def test_hurdat2_missing_values_are_nan() -> None:
    df = hurdat2.parse((FIX / "hurdat2_ian_excerpt.txt").read_text())
    old = df[df.storm_id == "AL011851"]
    assert old["pmin_mb"].isna().all()
    assert np.isnan(old["r34_ne"].iloc[0])


def test_atcf_parse_lines() -> None:
    text = (
        "AL, 09, 2022092700, 03, OFCL,   0, 208N,  833W,  85,  965, HU,  34, NEQ,  100,   80,   60,   90,\n"
        "AL, 09, 2022092700, 03, OFCL,   0, 208N,  833W,  85,  965, HU,  50, NEQ,   50,   40,   30,   40,\n"
        "AL, 09, 2022092700, 03, OFCL,  24, 245N,  829W, 115,    0, HU,  34, NEQ,  120,   90,   70,  100,\n"
        "AL, 09, 2022092700, 01, CARQ,   0, 208N,  833W,  85,  965, HU,  34, NEQ,  100,   80,   60,   90,\n"
        "AL, 09, 2022092700, 03, AVNO,   0, 208N,  833W,  85,  965, HU,  34, NEQ,  100,   80,   60,   90,\n"
    )
    df = atcf.parse(text)
    assert len(df) == 3  # one OFCL tau-0 row (duplicates removed), one OFCL tau-24 row, one CARQ row
    o24 = df[(df.tech == "OFCL") & (df.tau == 24)].iloc[0]
    assert o24.lat == 24.5 and o24.lon == -82.9 and o24.vmax_kt == 115 and np.isnan(o24.pmin_mb)
    assert o24.time == pd.Timestamp("2022-09-28 00:00", tz="UTC")
