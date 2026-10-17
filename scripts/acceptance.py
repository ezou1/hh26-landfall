"""Check the artifact-based items of the acceptance checklist and print the results.

Run `python scripts/acceptance.py` after `make precompute`. The script reads out/ only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"

PLACES = {
    "Tampa Bay": (-82.64, 27.70),
    "Fort Myers": (-81.87, 26.64),
    "Charlotte Harbor": (-82.10, 26.90),
}


def cone_levels(key: str) -> dict[str, object]:
    """Return the cone polygons of one advisory by level."""
    fc = json.loads((OUT / "stage1" / key / "cone.geojson").read_text())
    return {f["properties"]["level"]: shape(f["geometry"]) for f in fc["features"]}


def covers(geom: object, place: str) -> bool:
    """Return True if a polygon covers a place."""
    lon, lat = PLACES[place]
    return bool(geom is not None and geom.buffer(0.05).contains(Point(lon, lat)))  # type: ignore[attr-defined]


def main() -> int:
    """Print one line for each check and return 1 if a check fails."""
    results: list[tuple[str, bool, str]] = []
    t0 = cone_levels("2022092500")
    ok = covers(t0.get("p90"), "Tampa Bay") and covers(t0.get("p90"), "Fort Myers")
    results.append(("4a T0 p90 cone covers Tampa Bay and Fort Myers", ok,
                    f"Tampa={covers(t0.get('p90'), 'Tampa Bay')} FortMyers={covers(t0.get('p90'), 'Fort Myers')}"))
    c27 = cone_levels("2022092700")
    narrow = covers(c27.get("p50"), "Fort Myers") or covers(c27.get("p50"), "Charlotte Harbor")
    area0 = t0["p90"].area if "p90" in t0 else 0.0  # type: ignore[attr-defined]
    area27 = c27["p90"].area if "p90" in c27 else 0.0  # type: ignore[attr-defined]
    results.append(("4b 09-27 00Z cone narrows to Charlotte Harbor - Fort Myers", narrow and area27 < area0,
                    f"p50 covers FM={covers(c27.get('p50'), 'Fort Myers')} CH={covers(c27.get('p50'), 'Charlotte Harbor')} "
                    f"Tampa p50={covers(c27.get('p50'), 'Tampa Bay')} p90 area {area0:.0f} -> {area27:.0f} deg2"))
    lf = json.loads((OUT / "stage1" / "2022092812" / "landfall.json").read_text())
    results.append(("4c 09-28 12Z p(landfall in Lee) > 0.5", lf["p_landfall_county"] > 0.5,
                    f"p={lf['p_landfall_county']:.3f}"))
    sm = json.loads((OUT / "verify" / "summary.json").read_text())
    i48 = sm["leads_h"].index(48)
    m48, c48, o48 = (sm["methods"][k]["track_km"][i48] for k in ("model", "cliper", "ofcl"))
    results.append(("5 48-h track error: model < CLIPER-lite", m48 < c48,
                    f"model={m48:.0f} km cliper={c48:.0f} km ofcl={o48:.0f} km"))
    meta = json.loads((OUT / "meta.json").read_text())
    for adv in meta["plan_advisories"]:
        key = adv[:13].replace("-", "").replace("T", "")
        agg = json.loads((OUT / "plan" / key / "aggregate.json").read_text())
        worst = agg["worst_case"]
        plan = json.loads((OUT / "plan" / key / f"s{worst}.json").read_text())
        crit = sorted({r["critical_name"] for r in plan["road_status"] if r["is_critical"] and r["critical_name"]
                       in ("Sanibel Causeway", "Matlacha Pass Bridge", "Pine Island Road")})
        helo = [t for t in plan["sar_tasks"] if t["asset_type"] == "helo" and t["on_barrier_island"] and t["asset_id"]]
        results.append((f"6 [{key}] worst case s{worst}: critical link blocked and helo on island task",
                        bool(crit) and bool(helo), f"blocked={crit} helo_island_tasks={len(helo)}"))
        cmp_ = json.loads((OUT / "plan" / key / "comparison.json").read_text())
        row = next(r for r in cmp_["rows"] if r["metric"] == "persons_not_cleared")
        results.append((f"7 [{key}] optimized persons not cleared < baseline", row["optimized"] < row["baseline"],
                        f"optimized={row['optimized']:.0f} baseline={row['baseline']:.0f}"))
    secs = [json.loads((p / "ensemble.json").read_text()).get("seconds", 0.0)
            for p in sorted((OUT / "stage1").iterdir()) if (p / "ensemble.json").exists()]
    results.append(("10a N=1000 Stage 1 rollout < 60 s", max(secs) < 60, f"max={max(secs):.1f} s over {len(secs)} advisories"))
    fails = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
        fails += 0 if ok else 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
