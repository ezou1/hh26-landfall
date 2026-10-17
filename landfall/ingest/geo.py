"""Build the elevation grid, the county land mask, and the basin land-distance grid.

The county grid has a 500 m cell size over the county bbox. The elevation source is
the Copernicus GLO-30 DEM. The basin grid gives the signed distance to the coast for
the predictor. The value is positive over water and negative over land.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import requests
from scipy import ndimage

from landfall.config import BBOX, CACHE, GRID_RES_M, RAW, STATIC
from landfall.log import clear_fallback, get_logger, record_fallback

COP_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM.tif"
)
NE_LAND_50 = "https://naciscdn.org/naturalearth/50m/physical/ne_50m_land.zip"
NE_LAND_10 = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"
COUNTY_GRID = CACHE / "county_grid.npz"
LAND_DIST = STATIC / "land_dist_0p1.npz"
BASIN = (-110.0, 0.0, 0.0, 60.0)  # west, south, east, north
BASIN_RES = 0.1


@dataclass
class CountyGrid:
    """The 500 m raster over the county bbox."""

    lon: np.ndarray  # (nx,) cell-centre longitudes
    lat: np.ndarray  # (ny,) cell-centre latitudes, south to north
    elev: np.ndarray  # (ny, nx) metres above sea level
    land: np.ndarray  # (ny, nx) bool
    coast_km: np.ndarray  # (ny, nx) distance from the coast in km (land cells)
    used_fallback: bool

    @property
    def shape(self) -> tuple[int, int]:
        """Return the grid shape as (ny, nx)."""
        return self.elev.shape


def _download(url: str, name: str) -> bytes:
    dest = RAW / name
    if not dest.exists():
        get_logger().info("download", url=url)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest.read_bytes()


def _ne_land(url: str, name: str) -> gpd.GeoDataFrame:
    data = _download(url, name)
    folder = RAW / name.replace(".zip", "")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(folder)
    shp = next(folder.glob("*.shp"))
    return gpd.read_file(shp).to_crs(4326)


def grid_axes() -> tuple[np.ndarray, np.ndarray]:
    """Return the cell-centre longitudes and latitudes of the county grid."""
    w, s, e, n = BBOX
    lat0 = 0.5 * (s + n)
    dlat = GRID_RES_M / 111_320.0
    dlon = GRID_RES_M / (111_320.0 * np.cos(np.radians(lat0)))
    lon = np.arange(w + dlon / 2, e, dlon)
    lat = np.arange(s + dlat / 2, n, dlat)
    return lon, lat


def _dem_on_grid(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    import rasterio
    from rasterio.warp import Resampling, reproject

    out = np.full((len(lat), len(lon)), np.nan, dtype=np.float32)
    dlon = lon[1] - lon[0]
    dlat = lat[1] - lat[0]
    from rasterio.transform import from_origin

    dst_tf = from_origin(lon[0] - dlon / 2, lat[-1] + dlat / 2, dlon, dlat)
    for tile_lon in (82, 83):
        url = COP_URL.format(lat=26, lon=tile_lon)
        data = _download(url, f"cop30_N26_W{tile_lon:03d}.tif")
        with rasterio.MemoryFile(data) as mf, mf.open() as src:
            tmp = np.full(out.shape, np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=tmp,
                dst_transform=dst_tf,
                dst_crs="EPSG:4326",
                resampling=Resampling.average,
                dst_nodata=np.nan,
            )
        tmp = tmp[::-1, :]  # north-up raster to south-to-north rows
        out = np.where(np.isnan(out), tmp, out)
    return out


def county_grid(refresh: bool = False) -> CountyGrid:
    """Return the county grid. Build and cache it if necessary."""
    if COUNTY_GRID.exists() and not refresh:
        z = np.load(COUNTY_GRID)
        return CountyGrid(z["lon"], z["lat"], z["elev"], z["land"], z["coast_km"], bool(z["fb"]))
    lon, lat = grid_axes()
    xx, yy = np.meshgrid(lon, lat)
    used_fallback = False
    try:
        land_gdf = _ne_land(NE_LAND_10, "ne_10m_land.zip")
        from shapely import contains_xy
        from shapely.ops import unary_union

        clip = land_gdf.clip(BBOX)
        poly = unary_union(clip.geometry.values)
        ne_land = contains_xy(poly, xx, yy)
    except Exception as exc:  # noqa: BLE001
        record_fallback("coastline", f"Natural Earth download failed: {exc}")
        ne_land = xx > -82.05
        used_fallback = True
    try:
        elev = _dem_on_grid(lon, lat)
        # Copernicus marks the sea with values near 0. Use the DEM and the coastline together.
        land = (elev > 0.05) | (ne_land & (elev > -1))
        land = ndimage.binary_opening(land, iterations=1) | (elev > 1.0)
        clear_fallback("elevation")
    except Exception as exc:  # noqa: BLE001
        record_fallback("elevation", f"Copernicus DEM download failed; elevation from coast distance: {exc}")
        land = ne_land
        used_fallback = True
        elev = None
    coast_km = ndimage.distance_transform_edt(land) * GRID_RES_M / 1000.0
    if elev is None:
        elev = np.where(land, 0.6 * coast_km + 0.5, -1.0).astype(np.float32)
    elev = np.where(np.isnan(elev), 0.0, elev).astype(np.float32)
    np.savez_compressed(
        COUNTY_GRID, lon=lon, lat=lat, elev=elev, land=land, coast_km=coast_km.astype(np.float32),
        fb=used_fallback,
    )
    get_logger().info("county grid", shape=elev.shape, land_cells=int(land.sum()), fallback=used_fallback)
    return CountyGrid(lon, lat, elev, land, coast_km.astype(np.float32), used_fallback)


def land_distance_grid(refresh: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (lon, lat, dist_km) for the basin. The distance is negative over land."""
    if LAND_DIST.exists() and not refresh:
        z = np.load(LAND_DIST)
        return z["lon"], z["lat"], z["dist_km"].astype(np.float32)
    w, s, e, n = BASIN
    lon = np.arange(w + BASIN_RES / 2, e, BASIN_RES)
    lat = np.arange(s + BASIN_RES / 2, n, BASIN_RES)
    xx, yy = np.meshgrid(lon, lat)
    try:
        land_gdf = _ne_land(NE_LAND_50, "ne_50m_land.zip")
        from shapely import contains_xy
        from shapely.ops import unary_union

        poly = unary_union(land_gdf.clip(BASIN).geometry.values)
        land = contains_xy(poly, xx, yy)
    except Exception as exc:  # noqa: BLE001
        record_fallback("land_mask", f"Natural Earth download failed; crude land mask: {exc}")
        land = ((xx < -97) & (yy > 18)) | ((xx < -81) & (yy > 30)) | ((xx > -82) & (xx < -80) & (yy > 25) & (yy < 30.5))
    km_y = BASIN_RES * 111.32
    km_x = BASIN_RES * 111.32 * np.cos(np.radians(25.0))
    d_water = ndimage.distance_transform_edt(~land, sampling=(km_y, km_x))
    d_land = ndimage.distance_transform_edt(land, sampling=(km_y, km_x))
    dist = np.where(land, -d_land, d_water).astype(np.float32)
    np.savez_compressed(LAND_DIST, lon=lon, lat=lat, dist_km=dist.astype(np.float16))
    return lon, lat, dist


_LD: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None


def land_distance_km(lon: np.ndarray | float, lat: np.ndarray | float) -> np.ndarray:
    """Return the signed distance to the coast in km. The value is negative over land."""
    global _LD
    if _LD is None:
        _LD = land_distance_grid()
    glon, glat, dist = _LD
    lon_a = np.asarray(lon, dtype=float)
    lat_a = np.asarray(lat, dtype=float)
    i = np.clip(((lat_a - glat[0]) / BASIN_RES).round().astype(int), 0, len(glat) - 1)
    j = np.clip(((lon_a - glon[0]) / BASIN_RES).round().astype(int), 0, len(glon) - 1)
    out = dist[i, j].astype(float)
    outside = (lon_a < BASIN[0]) | (lon_a > BASIN[2]) | (lat_a < BASIN[1]) | (lat_a > BASIN[3])
    return np.where(outside, 500.0, out)
