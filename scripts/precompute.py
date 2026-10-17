"""Precompute every artifact that the UI needs, unless the artifacts exist.

Run `python scripts/precompute.py` to write out/. Use --force to recompute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from landfall import config as C  # noqa: E402
from landfall.log import get_logger  # noqa: E402
from landfall.pipeline import main as pipeline_main  # noqa: E402


def complete() -> bool:
    """Return True if out/ holds a full set of artifacts for this seed and mode."""
    meta = C.OUT / "meta.json"
    if not meta.exists():
        return False
    m = json.loads(meta.read_text())
    if m.get("metadata", {}).get("seed") != C.SEED or m.get("chalk_mode") != C.CHALK_MODE:
        return False
    for a in m.get("plan_advisories", []):
        key = a[:13].replace("-", "").replace("T", "")
        if not (C.OUT / "plan" / key / "aggregate.json").exists():
            return False
    return len(m.get("advisories", [])) >= len(C.advisory_times()) and bool(m.get("plan_advisories"))


def main() -> None:
    """Run the pipeline if the artifacts are missing, or if --force is given."""
    force = "--force" in sys.argv
    if complete() and not force:
        get_logger().info("precompute skipped: out/ is complete (use FORCE=1 to recompute)")
        return
    pipeline_main(["--clean"])


if __name__ == "__main__":
    main()
