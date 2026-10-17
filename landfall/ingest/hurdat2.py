"""Download and parse the HURDAT2 Atlantic best-track file."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from landfall.config import CACHE, RAW
from landfall.log import get_logger

INDEX_URL = "https://www.nhc.noaa.gov/data/hurdat/"
FALLBACK_NAME = "hurdat2-1851-2023-051124.txt"
PARQUET = CACHE / "hurdat2.parquet"

RADII_COLS = [
    f"r{kt}_{q}" for kt in (34, 50, 64) for q in ("ne", "se", "sw", "nw")
]


def latest_url() -> str:
    """Return the URL of the newest Atlantic HURDAT2 file on the NHC server."""
    html = requests.get(INDEX_URL, timeout=30).text
    names = sorted(set(re.findall(r"hurdat2-1851-(\d{4})-(\d{6,8})\.txt", html)))
    if not names:
        return INDEX_URL + FALLBACK_NAME
    # Sort by the last year of data, then by the release date.
    def key(n: tuple[str, str]) -> tuple[int, str]:
        d = n[1]
        rel = d[-4:] + d[:4] if len(d) == 8 else "20" + d[-2:] + d[:4]
        return int(n[0]), rel

    year, rel = max(names, key=key)
    return f"{INDEX_URL}hurdat2-1851-{year}-{rel}.txt"


def download(dest_dir: Path = RAW) -> Path:
    """Download the newest HURDAT2 file and return the local path."""
    url = latest_url()
    dest = dest_dir / url.rsplit("/", 1)[1]
    if not dest.exists():
        get_logger().info("download", url=url)
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def _coord(s: str) -> float:
    s = s.strip()
    v = float(s[:-1])
    return -v if s[-1] in "SW" else v


def parse(text: str) -> pd.DataFrame:
    """Parse HURDAT2 text into a tidy frame with one row for each fix."""
    rows: list[dict[str, object]] = []
    storm_id = name = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if re.match(r"^[A-Z]{2}\d{6}$", parts[0]):
            storm_id, name = parts[0], parts[1]
            continue
        date, hhmm, ident, status = parts[0], parts[1], parts[2], parts[3]
        vals = [float(p) if p not in ("", "-999") else np.nan for p in parts[6:20]]
        while len(vals) < 14:
            vals.append(np.nan)
        rmw = float(parts[20]) if len(parts) > 20 and parts[20] not in ("", "-999") else np.nan
        row: dict[str, object] = {
            "storm_id": storm_id,
            "name": name,
            "time": pd.Timestamp(f"{date} {hhmm[:2]}:{hhmm[2:]}", tz="UTC"),
            "record": ident,
            "status": status,
            "lat": _coord(parts[4]),
            "lon": _coord(parts[5]),
            "vmax_kt": vals[0],
            "pmin_mb": vals[1],
            "rmw_nm": rmw,
        }
        for c, v in zip(RADII_COLS, vals[2:14], strict=True):
            row[c] = v
        rows.append(row)
    df = pd.DataFrame(rows)
    df.loc[df["pmin_mb"] < 0, "pmin_mb"] = np.nan
    df["basin"] = df["storm_id"].str[:2]
    df["year"] = df["time"].dt.year
    return df


def load(refresh: bool = False) -> pd.DataFrame:
    """Return the parsed HURDAT2 frame. Download and cache it if necessary."""
    if PARQUET.exists() and not refresh:
        return pd.read_parquet(PARQUET)
    path = download()
    df = parse(path.read_text())
    df.to_parquet(PARQUET)
    get_logger().info("hurdat2", rows=len(df), storms=df["storm_id"].nunique(), file=path.name)
    return df
