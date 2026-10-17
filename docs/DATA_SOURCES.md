# Data sources

`scripts/download_data.py` downloads and caches every source. If a download fails, the script writes a labelled fallback with the same schema. Then it logs a WARNING.

## Files

| File | Origin | Licence | Demo uses |
| --- | --- | --- | --- |
| `data/raw/hurdat2-1851-2025-*.txt` | NHC HURDAT2 Atlantic best track, newest file on `https://www.nhc.noaa.gov/data/hurdat/` | US Government work, public domain | real |
| `data/cache/hurdat2.parquet` | Parsed HURDAT2 | public domain | real |
| `data/static/hurdat2_1979_2022_snapshot.parquet` | Bundled copy of the Atlantic HURDAT2 rows from 1979 to 2022 | public domain | fallback only |
| `data/raw/aal092022.dat.gz` | ATCF a-deck of Ian, `https://ftp.nhc.noaa.gov/atcf/archive/2022/` | public domain | real |
| `data/static/atcf_al092022_snapshot.parquet` | Bundled copy of the parsed CARQ and OFCL rows | public domain | fallback only |
| `data/static/zones.geojson` | Lee County GIS, ArcGIS feature service "EvacuationZones" (LeeCountyFLGIS), dissolved by zone | Lee County open data | real |
| `data/raw/tl_2022_12_bg.zip` | Census TIGER/Line 2022 block groups for Florida | public domain | real |
| `data/raw/acsdt5y2022-b01003.dat` | ACS 5-year 2022 table B01003 (population), keyless summary file | public domain | real |
| `data/raw/acsdt5y2022-b08201.dat` | ACS 5-year 2022 table B08201 (households and vehicles), keyless summary file | public domain | real |
| `data/cache/block_groups.parquet` | 579 Lee County block groups with population (772,902 persons) | public domain | real |
| `data/raw/cop30_N26_W082.tif`, `cop30_N26_W083.tif` | Copernicus GLO-30 DEM tiles on AWS | Copernicus DEM licence (free use with attribution) | real |
| `data/cache/county_grid.npz` | 500 m grid of elevation, land mask, and distance to the coast | derived | real |
| `data/raw/ne_10m_land.zip`, `ne_50m_land.zip` | Natural Earth land polygons | public domain | real |
| `data/static/land_dist_0p1.npz` | Signed distance to the coast on a 0.1-degree basin grid | derived from Natural Earth | real |
| `data/static/sst_clim_2deg.npz` | SST proxy: 28 - 0.25 max(0, abs(lat) - 10) degC with a seasonal term | formula, not data | proxy |
| `data/cache/lee_drive.graphml` | OpenStreetMap drive network of Lee County from OSMnx | ODbL | real |
| `data/cache/routing_graph.pkl` | Routing graph: tertiary and higher roads, bridges, causeways | derived from OSM, ODbL | real |
| `data/static/shelters.csv` | 12 Lee County shelter sites, curated | names are public; capacities are assumptions | curated |
| `data/static/hospitals.csv` | 6 hospitals, curated from public addresses (HIFLD-style fields) | names are public; bed counts are estimates | curated |
| `data/static/depots.csv` | 1 state staging area, 2 county warehouses, 3 retail stores | inventories are assumptions | curated |
| `data/static/assets.csv` | 4 helicopters, 10 boats, 12 high-water trucks | speeds and capacities are public-domain estimates | curated |

## Fallbacks

| Item | Fallback |
| --- | --- |
| HURDAT2 | Bundled snapshot of the 1979-2022 Atlantic rows |
| ATCF a-deck | Bundled snapshot of the Ian CARQ and OFCL rows |
| Evacuation zones | 5 synthetic zones from bands of distance to the coast |
| Census geometry | A synthetic grid of block groups with a uniform population |
| Census population | A uniform population by land area |
| Elevation | An elevation proxy from the distance to the coast |
| Coastline | A crude land mask |
| Road network | A labelled synthetic grid network |

## Status of this build

The demo of this build uses real data for every downloaded item. No fallback was necessary. The pipeline wrote no entry to `data/cache/fallbacks.json`. Census data comes from the keyless summary files because the Census API now needs a key.

## Notes on the curated files

- The shelter, hospital, depot, and asset coordinates are estimates from public addresses. Check them before operational use.
- The capacities, inventories, truck counts, speeds, and endurances are assumptions.
- The hospital list includes NCH Baker Hospital in Collier County for overflow.
