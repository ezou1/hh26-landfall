"""Copy the small data files that the deployed Chalk resolvers read into chalk/data/.

Run this script before `chalk apply`. The bundle holds the Atlantic HURDAT2 fixes from
1979 to 2022, the CARQ fixes of Ian, the land-distance grid, and the SST proxy grid.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from landfall.predict.features import ensure_fixes_cache  # noqa: E402

BUNDLE = ROOT / "chalk" / "data"


def main() -> None:
    """Write chalk/data/ and print the size of each file."""
    BUNDLE.mkdir(exist_ok=True)
    f = ensure_fixes_cache()
    years = f["time"].dt.year
    keep = ((f["source"] == "hurdat2") & f["storm_id"].str.startswith("AL") & (years >= 1979) & (years <= 2022)) | (
        f["source"] == "carq"
    )
    cols = ["id", "storm_id", "time", "lat", "lon", "vmax_kt", "pmin_mb", "status", "source"]
    f[keep][cols].reset_index(drop=True).to_parquet(BUNDLE / "storm_fixes.parquet", compression="zstd")
    for name in ("land_dist_0p1.npz", "sst_clim_2deg.npz"):
        shutil.copy(ROOT / "data" / "static" / name, BUNDLE / name)
    for p in sorted(BUNDLE.iterdir()):
        print(f"{p.relative_to(ROOT)}: {p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
