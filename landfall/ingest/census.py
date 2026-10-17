"""Load the Lee County block groups with population and households without a vehicle.

The geometry comes from Census TIGER 2022. The counts come from ACS 5-year tables
B01003 and B08201. If CENSUS_API_KEY is set, the module uses the Census API. If not,
it reads the keyless ACS summary-file tables. If both fail, it makes a labelled
synthetic population.
"""

from __future__ import annotations

import io
import os
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box

from landfall.config import BBOX, CACHE, COUNTY_CODE, RAW, STATE_FIPS
from landfall.log import clear_fallback, get_logger, record_fallback

TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2022/BG/tl_2022_12_bg.zip"
SF_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData/"
API = "https://api.census.gov/data/2022/acs/acs5"
OUT = CACHE / "block_groups.parquet"
COUNTY_POP_2022 = 790_000  # used only by the synthetic fallback


def _download(url: str, name: str) -> bytes:
    dest = RAW / name
    if not dest.exists():
        get_logger().info("download", url=url)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest.read_bytes()


def tiger_block_groups() -> gpd.GeoDataFrame:
    """Return the TIGER block groups of Lee County in EPSG:4326."""
    data = _download(TIGER_URL, "tl_2022_12_bg.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(RAW / "tl_2022_12_bg")
    gdf = gpd.read_file(RAW / "tl_2022_12_bg" / "tl_2022_12_bg.shp")
    gdf = gdf[gdf["COUNTYFP"] == COUNTY_CODE].to_crs(4326)
    return gdf[["GEOID", "ALAND", "AWATER", "geometry"]].reset_index(drop=True)


def _acs_api(key: str) -> pd.DataFrame:
    params = {
        "get": "B01003_001E,B08201_001E,B08201_002E",
        "for": "block group:*",
        "in": f"state:{STATE_FIPS} county:{COUNTY_CODE} tract:*",
        "key": key,
    }
    r = requests.get(API, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    return pd.DataFrame(
        {
            "GEOID": df["GEOID"],
            "population": df["B01003_001E"].astype(float),
            "households": df["B08201_001E"].astype(float),
            "hh_no_vehicle": df["B08201_002E"].astype(float),
        }
    )


def _acs_summary_file() -> pd.DataFrame:
    prefix = f"1500000US{STATE_FIPS}{COUNTY_CODE}"
    out = {}
    for table, cols in (("b01003", ["B01003_E001"]), ("b08201", ["B08201_E001", "B08201_E002"])):
        raw = _download(SF_BASE + f"acsdt5y2022-{table}.dat", f"acsdt5y2022-{table}.dat")
        lines = raw.decode("utf-8", errors="replace").splitlines()
        header = lines[0].split("|")
        keep = [ln for ln in lines[1:] if ln.startswith(prefix)]
        df = pd.DataFrame([ln.split("|") for ln in keep], columns=header)
        df["GEOID"] = df["GEO_ID"].str.replace("1500000US", "", regex=False)
        for c in cols:
            out[c] = df.set_index("GEOID")[c].astype(float)
    df = pd.DataFrame(out).reset_index().rename(columns={"index": "GEOID"})
    return pd.DataFrame(
        {
            "GEOID": df["GEOID"],
            "population": df["B01003_E001"],
            "households": df["B08201_E001"],
            "hh_no_vehicle": df["B08201_E002"],
        }
    )


def synthetic_block_groups() -> gpd.GeoDataFrame:
    """Return a labelled synthetic population on a regular grid over the county bbox."""
    w, s, e, n = BBOX
    rows = []
    xs = np.linspace(w, e, 15)
    ys = np.linspace(s, n, 10)
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            rows.append({"GEOID": f"SYN{i:02d}{j:02d}", "geometry": box(xs[i], ys[j], xs[i + 1], ys[j + 1])})
    gdf = gpd.GeoDataFrame(rows, crs=4326)
    gdf["ALAND"] = 1.0
    gdf["AWATER"] = 0.0
    gdf["population"] = COUNTY_POP_2022 / len(gdf)
    gdf["households"] = gdf["population"] / 2.4
    gdf["hh_no_vehicle"] = gdf["households"] * 0.05
    return gdf


def load(refresh: bool = False) -> gpd.GeoDataFrame:
    """Return the Lee County block groups with population and vehicle counts."""
    if OUT.exists() and not refresh:
        return gpd.read_parquet(OUT)
    try:
        gdf = tiger_block_groups()
        clear_fallback("census_geometry")
    except Exception as exc:  # noqa: BLE001
        record_fallback("census_geometry", f"TIGER download failed: {exc}")
        record_fallback("census_population", "no geometry, synthetic population")
        gdf = synthetic_block_groups()
        gdf.to_parquet(OUT)
        return gdf
    counts = None
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if key:
        try:
            counts = _acs_api(key)
        except Exception as exc:  # noqa: BLE001
            get_logger().warning("census api failed", error=str(exc))
    if counts is None:
        try:
            counts = _acs_summary_file()
        except Exception as exc:  # noqa: BLE001
            get_logger().warning("census summary file failed", error=str(exc))
    if counts is None or counts.empty:
        record_fallback("census_population", "ACS download failed; population is uniform by land area")
        gdf["population"] = COUNTY_POP_2022 * gdf["ALAND"] / gdf["ALAND"].sum()
        gdf["households"] = gdf["population"] / 2.4
        gdf["hh_no_vehicle"] = gdf["households"] * 0.05
    else:
        clear_fallback("census_population")
        gdf = gdf.merge(counts, on="GEOID", how="left").fillna(
            {"population": 0, "households": 0, "hh_no_vehicle": 0}
        )
    gdf = gdf.reset_index(drop=True)
    pts = gdf.geometry.representative_point()
    gdf["lon"] = pts.x
    gdf["lat"] = pts.y
    gdf.to_parquet(OUT)
    get_logger().info("census", block_groups=len(gdf), population=int(gdf["population"].sum()))
    return gdf
