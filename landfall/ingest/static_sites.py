"""Write and load the curated site files, and download the evacuation zones.

The curated files are shelters, hospitals, depots, and SAR assets. The coordinates are
estimates from public addresses. The capacities, speeds, and inventories are assumptions.
"""

from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, mapping
from shapely.ops import unary_union

from landfall.config import BBOX, STATIC, ZONES
from landfall.log import clear_fallback, get_logger, record_fallback

ZONES_URL = (
    "https://services2.arcgis.com/LvWGAAhHwbCJ2GMP/arcgis/rest/services/EvacuationZones/"
    "FeatureServer/0/query"
)
ZONES_FILE = STATIC / "zones.geojson"

SHELTERS = [
    # id, name, lat, lon, capacity, is_special_needs
    ("sh01", "Hertz Arena", 26.4268, -81.7716, 4000, False),
    ("sh02", "Estero Recreation Center", 26.4327, -81.7903, 1200, True),
    ("sh03", "Island Coast High School", 26.6834, -81.9958, 2000, False),
    ("sh04", "Ida S. Baker High School", 26.5938, -81.9866, 2000, False),
    ("sh05", "South Fort Myers High School", 26.5413, -81.8644, 1800, False),
    ("sh06", "Riverdale High School", 26.6537, -81.7562, 2000, False),
    ("sh07", "North Fort Myers High School", 26.6921, -81.8894, 1800, False),
    ("sh08", "Gateway High School", 26.5789, -81.7518, 1600, False),
    ("sh09", "Harns Marsh Middle School", 26.6378, -81.6439, 1400, False),
    ("sh10", "Lehigh Senior High School", 26.6181, -81.6555, 1800, True),
    ("sh11", "Treeline Elementary School", 26.5428, -81.7520, 1000, False),
    ("sh12", "Veterans Park Recreation Center", 26.6128, -81.6402, 900, False),
]

HOSPITALS = [
    # id, name, lat, lon, beds, has_helipad, trauma_level
    ("h01", "Lee Memorial Hospital", 26.6268, -81.8706, 415, True, 2),
    ("h02", "Gulf Coast Medical Center", 26.5520, -81.7976, 650, True, 0),
    ("h03", "Cape Coral Hospital", 26.6348, -81.9426, 291, True, 0),
    ("h04", "HealthPark Medical Center", 26.5068, -81.8538, 450, True, 0),
    ("h05", "Lehigh Regional Medical Center", 26.6014, -81.6434, 88, False, 0),
    ("h06", "NCH Baker Hospital (Collier, overflow)", 26.1547, -81.7986, 420, True, 0),
]

DEPOTS = [
    # id, name, kind, lat, lon, trucks, water L, food meals, med_kits, fuel L, generators
    ("d01", "State Logistics Response Center, Orlando", "state", 28.4466, -81.4019, 40,
     2_000_000, 1_500_000, 40_000, 400_000, 400),
    ("d02", "Lee County EOC Warehouse (assumed site)", "county", 26.6362, -81.8100, 12,
     150_000, 100_000, 6_000, 60_000, 40),
    ("d03", "Lee County Logistics Annex near RSW (assumed site)", "county", 26.5434, -81.7605, 10,
     120_000, 80_000, 4_000, 50_000, 30),
    ("d04", "Walmart Supercenter, Cape Coral", "retail", 26.6527, -81.9447, 3,
     40_000, 25_000, 500, 0, 5),
    ("d05", "Costco, Gulf Coast Town Center", "retail", 26.4870, -81.7842, 3,
     60_000, 30_000, 500, 0, 8),
    ("d06", "Home Depot, Lehigh Acres", "retail", 26.6114, -81.6588, 3,
     20_000, 5_000, 200, 0, 25),
]

ASSETS = [
    # id, kind, name, base_lat, base_lon, speed_kmh, capacity_persons, endurance_h
    ("a01", "helo", "USCG MH-60T 6001", 26.5862, -81.8633, 260, 6, 4.5),
    ("a02", "helo", "USCG MH-60T 6002", 26.5862, -81.8633, 260, 6, 4.5),
    ("a03", "helo", "State UH-60 101", 26.5362, -81.7552, 240, 8, 3.0),
    ("a04", "helo", "State UH-60 102", 26.5362, -81.7552, 240, 8, 3.0),
]
_BOAT_BASES = [
    (26.5400, -81.9570), (26.4830, -82.0100), (26.6450, -81.8700), (26.6330, -82.0670),
    (26.4560, -81.9520), (26.5650, -81.9800), (26.6900, -81.9100), (26.4000, -81.8500),
    (26.6100, -81.8800), (26.5100, -81.9200),
]
for _i, (_la, _lo) in enumerate(_BOAT_BASES, start=1):
    ASSETS.append((f"b{_i:02d}", "boat", f"Rescue boat {_i:02d}", _la, _lo, 30, 8, 10.0))
_TRUCK_BASES = [
    (26.6360, -81.8100), (26.5430, -81.7600), (26.6300, -81.9500), (26.6100, -81.6500),
    (26.6900, -81.8900), (26.4300, -81.7900), (26.5500, -81.8700), (26.6600, -81.7600),
    (26.5900, -81.9900), (26.4900, -81.8300), (26.6800, -81.9900), (26.6000, -81.7300),
]
for _i, (_la, _lo) in enumerate(_TRUCK_BASES, start=1):
    ASSETS.append((f"w{_i:02d}", "high_water_truck", f"High-water truck {_i:02d}", _la, _lo, 40, 12, 12.0))


def write_curated() -> None:
    """Write the curated CSV files to data/static/."""
    pd.DataFrame(
        SHELTERS, columns=["id", "name", "lat", "lon", "capacity", "is_special_needs"]
    ).to_csv(STATIC / "shelters.csv", index=False)
    pd.DataFrame(
        HOSPITALS, columns=["id", "name", "lat", "lon", "beds", "has_helipad", "trauma_level"]
    ).to_csv(STATIC / "hospitals.csv", index=False)
    pd.DataFrame(
        DEPOTS,
        columns=["id", "name", "kind", "lat", "lon", "trucks", "water", "food", "med_kits", "fuel", "generators"],
    ).to_csv(STATIC / "depots.csv", index=False)
    pd.DataFrame(
        ASSETS,
        columns=["id", "kind", "name", "base_lat", "base_lon", "speed_kmh", "capacity_persons", "endurance_h"],
    ).to_csv(STATIC / "assets.csv", index=False)


def shelters() -> pd.DataFrame:
    """Return the shelter table."""
    return pd.read_csv(STATIC / "shelters.csv")


def hospitals() -> pd.DataFrame:
    """Return the hospital table."""
    return pd.read_csv(STATIC / "hospitals.csv")


def depots() -> pd.DataFrame:
    """Return the depot table."""
    return pd.read_csv(STATIC / "depots.csv")


def assets() -> pd.DataFrame:
    """Return the SAR asset table."""
    return pd.read_csv(STATIC / "assets.csv")


def download_zones() -> bool:
    """Download the Lee County evacuation zones and dissolve them by zone letter."""
    params = {
        "where": "1=1", "outFields": "CountyZone,County,EvacZone", "outSR": "4326",
        "f": "geojson", "returnGeometry": "true", "geometryPrecision": "5",
    }
    r = requests.get(ZONES_URL, params=params, timeout=120)
    r.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(r.json()["features"], crs=4326)
    if "County" in gdf.columns:
        lee = gdf[gdf["County"].astype(str).str.lower().str.contains("lee")]
        gdf = lee if len(lee) else gdf
    gdf = gdf[gdf["CountyZone"].isin(ZONES)]
    if gdf.empty:
        raise ValueError("zone service returned no A-E zones")
    gdf["geometry"] = gdf.geometry.buffer(0)
    feats = []
    for z in ZONES:
        part = gdf[gdf["CountyZone"] == z]
        if part.empty:
            continue
        geom = unary_union(part.geometry.values).simplify(0.0008, preserve_topology=True)
        feats.append({"type": "Feature", "properties": {"zone": z, "source": "Lee County GIS"},
                      "geometry": mapping(geom)})
    ZONES_FILE.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return True


def synthetic_zones() -> None:
    """Write 5 labelled synthetic zones from bands of distance to the coast."""
    from landfall.ingest.geo import county_grid

    g = county_grid()
    from rasterio import features as rfeatures
    from rasterio.transform import from_origin

    dlon = g.lon[1] - g.lon[0]
    dlat = g.lat[1] - g.lat[0]
    tf = from_origin(g.lon[0] - dlon / 2, g.lat[-1] + dlat / 2, dlon, dlat)
    bands = [(0, 1.5), (1.5, 3), (3, 5), (5, 8), (8, 12)]
    feats = []
    for z, (a, b) in zip(ZONES, bands, strict=True):
        mask = (g.land & (g.coast_km > a) & (g.coast_km <= b))[::-1, :].astype(np.uint8)
        polys = [
            __import__("shapely.geometry", fromlist=["shape"]).shape(geom)
            for geom, v in rfeatures.shapes(mask, mask=mask.astype(bool), transform=tf)
            if v == 1
        ]
        geom = unary_union(polys).simplify(0.002)
        feats.append({"type": "Feature", "properties": {"zone": z, "source": "synthetic"},
                      "geometry": mapping(geom)})
    ZONES_FILE.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def ensure_zones(refresh: bool = False) -> gpd.GeoDataFrame:
    """Return the zone polygons. Download them, or build the fallback zones."""
    if refresh or not ZONES_FILE.exists():
        try:
            download_zones()
            clear_fallback("zones")
        except Exception as exc:  # noqa: BLE001
            record_fallback("zones", f"Lee County zone service failed; distance-to-coast bands: {exc}")
            synthetic_zones()
    gdf = gpd.read_file(ZONES_FILE)
    if (gdf.get("source") == "synthetic").any():
        record_fallback("zones", "zones.geojson holds synthetic zones")
    return gdf


def zone_of_points(zones: gpd.GeoDataFrame, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Return the zone letter of each point, or an empty string outside all zones.

    If zones overlap, the lowest letter wins (A is the most exposed zone).
    """
    from shapely import contains_xy

    out = np.full(len(lon), "", dtype=object)
    for z in reversed(ZONES):
        part = zones[zones["zone"] == z]
        if part.empty:
            continue
        inside = contains_xy(part.geometry.values[0], lon, lat)
        out[inside] = z
    return out


def in_bbox(lon: float, lat: float) -> bool:
    """Return True if a point is inside the county bbox."""
    w, s, e, n = BBOX
    return w <= lon <= e and s <= lat <= n


def point(lon: float, lat: float) -> Point:
    """Return a shapely point."""
    return Point(lon, lat)


if __name__ == "__main__":
    write_curated()
    z = ensure_zones(refresh=True)
    get_logger().info("zones", n=len(z))
