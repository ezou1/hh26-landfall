"""Download and cache every data source. Write labelled fallbacks if a download fails.

Run this script from the repository root: `python scripts/download_data.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from landfall.config import STATIC  # noqa: E402
from landfall.ingest import atcf, census, geo, hurdat2, osm, static_sites  # noqa: E402
from landfall.log import clear_fallback, get_logger, record_fallback, stage  # noqa: E402

SNAP_HURDAT = STATIC / "hurdat2_1979_2022_snapshot.parquet"
SNAP_ATCF = STATIC / "atcf_al092022_snapshot.parquet"


def best_track() -> None:
    """Load HURDAT2. If the download fails, use the bundled snapshot."""
    try:
        df = hurdat2.load()
        clear_fallback("hurdat2")
        snap = df[(df["year"] >= 1979) & (df["year"] <= 2022) & (df["basin"] == "AL")]
        if not SNAP_HURDAT.exists():
            snap.to_parquet(SNAP_HURDAT, compression="zstd")
    except Exception as exc:  # noqa: BLE001
        if not SNAP_HURDAT.exists():
            raise
        record_fallback("hurdat2", f"download failed, bundled snapshot used: {exc}")
        pd.read_parquet(SNAP_HURDAT).to_parquet(hurdat2.PARQUET)


def adeck() -> None:
    """Load the Ian a-deck. If the download fails, use the bundled snapshot."""
    try:
        df = atcf.load()
        clear_fallback("atcf")
        if not SNAP_ATCF.exists():
            df.to_parquet(SNAP_ATCF, compression="zstd")
    except Exception as exc:  # noqa: BLE001
        if not SNAP_ATCF.exists():
            raise
        record_fallback("atcf", f"download failed, bundled snapshot used: {exc}")
        pd.read_parquet(SNAP_ATCF).to_parquet(atcf.PARQUET)


def main() -> None:
    """Download every data source in order."""
    log = get_logger()
    with stage("download.hurdat2"):
        best_track()
    with stage("download.atcf"):
        adeck()
    with stage("download.static_sites"):
        static_sites.write_curated()
        static_sites.ensure_zones()
    with stage("download.geo"):
        geo.land_distance_grid()
        geo.county_grid()
    with stage("download.census"):
        census.load()
    with stage("download.osm"):
        osm.build_routing_graph()
    log.info("download done")


if __name__ == "__main__":
    main()
