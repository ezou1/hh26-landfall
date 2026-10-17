"""Download and parse the ATCF a-deck for Ian (CARQ and OFCL records)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import requests

from landfall.config import CACHE, RAW
from landfall.log import get_logger

URL = "https://ftp.nhc.noaa.gov/atcf/archive/2022/aal092022.dat.gz"
PARQUET = CACHE / "atcf_al092022.parquet"


def download(dest_dir: Path = RAW) -> Path:
    """Download the gzip a-deck file and return the local path."""
    dest = dest_dir / "aal092022.dat.gz"
    if not dest.exists():
        get_logger().info("download", url=URL)
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def _coord(s: str) -> float:
    s = s.strip()
    v = float(s[:-1]) / 10.0
    return -v if s[-1] in "SW" else v


def parse(text: str, techs: tuple[str, ...] = ("CARQ", "OFCL")) -> pd.DataFrame:
    """Parse a-deck text into one row for each (tech, base time, tau)."""
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 11 or p[4] not in techs:
            continue
        base = pd.Timestamp(p[2][:8] + " " + p[2][8:10] + ":00", tz="UTC")
        tau = int(p[5])
        try:
            lat, lon = _coord(p[6]), _coord(p[7])
        except (ValueError, IndexError):
            continue
        vmax = float(p[8]) if p[8] else float("nan")
        mslp = float(p[9]) if p[9] and float(p[9]) > 0 else float("nan")
        rmw = float(p[19]) if len(p) > 19 and p[19] and float(p[19]) > 0 else float("nan")
        rows.append(
            {
                "storm_id": f"{p[0]}{p[1]}{p[2][:4]}",
                "tech": p[4],
                "base_time": base,
                "tau": tau,
                "time": base + pd.Timedelta(hours=tau),
                "lat": lat,
                "lon": lon,
                "vmax_kt": vmax,
                "pmin_mb": mslp,
                "status": p[10] if len(p) > 10 else "",
                "rmw_nm": rmw,
            }
        )
    df = pd.DataFrame(rows)
    return df.drop_duplicates(["tech", "base_time", "tau"]).sort_values(["tech", "base_time", "tau"])


def load(refresh: bool = False) -> pd.DataFrame:
    """Return the parsed a-deck frame. Download and cache it if necessary."""
    if PARQUET.exists() and not refresh:
        return pd.read_parquet(PARQUET)
    path = download()
    with gzip.open(path, "rt") as fh:
        df = parse(fh.read())
    df["storm_id"] = "AL092022"
    df.to_parquet(PARQUET)
    get_logger().info("atcf", rows=len(df), ofcl=int((df.tech == "OFCL").sum()))
    return df


def carq(df: pd.DataFrame) -> pd.DataFrame:
    """Return the CARQ tau-0 fixes: the storm state that NHC knew at each base time."""
    c = df[(df.tech == "CARQ") & (df.tau == 0)].copy()
    return c.sort_values("time").reset_index(drop=True)


def ofcl(df: pd.DataFrame, base_time: pd.Timestamp) -> pd.DataFrame:
    """Return the OFCL forecast issued at one base time."""
    o = df[(df.tech == "OFCL") & (df.base_time == base_time)].copy()
    return o.sort_values("tau").reset_index(drop=True)
