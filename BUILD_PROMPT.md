# LANDFALL — Single-Shot Build Prompt

You are building **LANDFALL**: a hurricane prediction and response-logistics planner with a 3D globe timeline UI.
Read this whole file before you write any code. Then build the full system without stopping for approval.
When something is ambiguous, pick the option that makes the demo work in less time, write the choice in `docs/DECISIONS.md`, and continue.

Hard budget: **12 hours of agent time**. Section 11 gives the hour-by-hour plan. Do not exceed a phase budget by more than 30%; if you do, cut stretch scope from Section 12 and continue.

---

## 0. One paragraph

Given historical or live weather and storm-advisory data, LANDFALL (1) predicts where a hurricane goes and how strong it becomes, as a Monte Carlo ensemble of tracks; (2) converts each track into surge, wind, and damage impacts on one US county; (3) runs a second Monte Carlo over those scenarios to produce evacuation timing and routes, medical-supply demand and delivery routes, search-and-rescue (SAR) and medevac assignments, and debris-removal tasks; and (4) shows all of it on a photorealistic 3D globe with a scrubbable timeline, in the visual style of a satellite-operations console. Feature data flows through **Chalk** so that the prediction model can be trained and verified on point-in-time-correct history.

Demo scenario: **Hurricane Ian (AL092022), Lee County, Florida.** Replay clock starts at **2022-09-25 00:00 UTC** and runs to **2022-09-30 00:00 UTC**. Truth landfall: 2022-09-28 ~19:05 UTC near Cayo Costa, Category 4, 150 mph (130 kt) sustained.

---

## 1. Fixed decisions (do not re-open)

| Topic | Decision |
| --- | --- |
| Runtime | Python 3.12 backend (FastAPI). TypeScript frontend (React 18, Vite, CesiumJS via `resium`). |
| Globe | CesiumJS with Google Photorealistic 3D Tiles through a Cesium ion token (`CESIUM_ION_TOKEN`). Fall back to Cesium World Terrain + Esri imagery if the token is absent. |
| Feature platform | Chalk (`chalkpy`). Every feature used by the predictor is declared in `chalk/features.py`. `CHALK_MODE=remote` uses the real deployment; `CHALK_MODE=local` runs the same resolver functions in-process with pandas. The demo must work in both modes. |
| Compute | One NVIDIA GPU is available for training. Monte Carlo batches run on CPU with `joblib`; when `CHALK_MODE=remote`, also expose the batch as a `@chalkcompute.function` and prefer it. |
| Storm | Ian 2022. County: Lee County, FL (FIPS 12071). Bounding box: lon -82.40 to -81.55, lat 26.30 to 26.85. |
| Optimizer | `highspy` (HiGHS) through `scipy.optimize.linprog(method="highs")` or `pyomo` with the `appsi_highs` solver. No Gurobi. |
| Road graph | OSMnx `graph_from_place("Lee County, Florida, USA", network_type="drive")`, simplified, cached to `data/cache/lee_drive.graphml`. |
| Routing solver | OR-Tools (`ortools`) for vehicle routing. NetworkX for shortest paths. |
| Docs language | **ASD-STE100** for `README.md`, everything in `docs/`, all Python docstrings, all TypeScript JSDoc, and all UI strings. See Section 13. |
| Licence | MIT. |
| Persistence | Files on disk (`data/`, `out/`). No database. |
| Single command | `make demo` must: install, download/cache data, train or load the model, run both Monte Carlo stages, precompute every artifact the UI needs, and start backend + frontend. |

---

## 2. Users and screens

| User | Screen | What they get |
| --- | --- | --- |
| Emergency manager | **Command** view (default) | Storm ensemble on the globe, zone release times, shelter plan, supply plan, SAR board, "expected" vs "worst 10%" toggle |
| Logistics lead | **Supply** view | Depot inventory, truck routes animated on the globe, unmet-demand table per scenario |
| SAR / medevac lead | **Rescue** view | Rescue task heat map, team assignments, helo and boat routes, hospital capacity gauges |
| Analyst | **Model** view (stretch) | Forecast error vs truth over lead time, ensemble spread, comparison to CLIPER baseline |

All views share one globe, one timeline, and one scenario picker.

---

## 3. System architecture

```
                 ┌──────────────────────────────────────────────┐
  HURDAT2 ──────▶│  Chalk feature layer  (chalk/)               │
  ATCF a-deck ──▶│  Storm, Advisory, StormHistory features      │
  NHC advisories │  point-in-time resolvers, offline backfill   │
                 └───────────────┬──────────────────────────────┘
                                 │ feature frames
                 ┌───────────────▼──────────────────────────────┐
                 │  Stage 1 — Track/Intensity MC   (predict/)   │
                 │  model: 6 h step predictor + residual sampler│
                 │  output: N tracks × T steps → cone, p(land)  │
                 └───────────────┬──────────────────────────────┘
                                 │ scenarios (reduced to K)
                 ┌───────────────▼──────────────────────────────┐
                 │  Stage 2 — Impact model          (impact/)   │
                 │  wind field, surge proxy, damage, blocked rds│
                 └───────────────┬──────────────────────────────┘
                                 │ impact grids per scenario
                 ┌───────────────▼──────────────────────────────┐
                 │  Stage 3 — Logistics MC          (logistics/)│
                 │  evacuation flow, supply LP, SAR/medevac VRP,│
                 │  debris tasks, infrastructure scores         │
                 └───────────────┬──────────────────────────────┘
                                 │ plan.json per scenario + aggregate
                 ┌───────────────▼──────────────────────────────┐
                 │  FastAPI  (api/)   → static artifacts + rerun│
                 └───────────────┬──────────────────────────────┘
                                 │ JSON / CZML / GeoJSON
                 ┌───────────────▼──────────────────────────────┐
                 │  React + Cesium globe  (web/)                │
                 │  timeline, layers, HUD, scenario picker      │
                 └──────────────────────────────────────────────┘
```

One shared **scenario clock**: every artifact is indexed by `(scenario_id, t)` where `t` is a UTC timestamp on a 1-hour grid from T0 to T0+120 h.

---

## 4. Repository layout

```
landfall/
├── Makefile
├── README.md                    # STE
├── pyproject.toml               # uv or pip; pin versions
├── .env.example
├── docs/                        # STE
│   ├── ARCHITECTURE.md
│   ├── DATA_SOURCES.md
│   ├── MODEL_CARD.md
│   ├── DECISIONS.md
│   ├── RUNBOOK.md
│   └── STE_RULES.md
├── data/
│   ├── raw/                     # downloaded, gitignored
│   ├── cache/                   # graph, grids, gitignored
│   └── static/                  # small bundled files committed (zones, shelters, depots, hospitals)
├── chalk/
│   ├── chalk.yaml
│   ├── features.py
│   ├── resolvers.py
│   ├── local_runtime.py         # CHALK_MODE=local executor
│   └── compute.py               # @chalkcompute.function wrappers
├── landfall/                    # Python package
│   ├── config.py
│   ├── ingest/
│   │   ├── hurdat2.py
│   │   ├── atcf.py
│   │   ├── osm.py
│   │   ├── census.py
│   │   └── static_sites.py
│   ├── predict/
│   │   ├── features.py          # thin wrapper over chalk/
│   │   ├── model.py
│   │   ├── train.py
│   │   ├── sample.py            # Monte Carlo rollout
│   │   ├── reduce.py            # scenario reduction
│   │   └── verify.py            # backtest vs truth + CLIPER
│   ├── impact/
│   │   ├── wind.py
│   │   ├── surge.py
│   │   ├── damage.py
│   │   └── roads.py
│   ├── logistics/
│   │   ├── demand.py
│   │   ├── evacuation.py
│   │   ├── supply.py
│   │   ├── sar.py
│   │   ├── medevac.py
│   │   ├── debris.py
│   │   ├── infrastructure.py
│   │   └── aggregate.py
│   ├── export/
│   │   ├── czml.py
│   │   └── geojson.py
│   └── pipeline.py              # orchestrates stages, writes out/
├── api/
│   └── main.py
├── web/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── globe/               # Cesium viewer, layers, camera
│       ├── timeline/
│       ├── panels/              # Command, Supply, Rescue, Model
│       ├── hud/
│       ├── state/               # zustand store
│       ├── api/
│       └── styles/
├── scripts/
│   ├── download_data.py
│   ├── precompute.py
│   └── ste_lint.py
├── tests/
└── out/                         # generated artifacts, gitignored
```

---

## 5. Data sources

Download with `scripts/download_data.py`. Cache everything. If a download fails, write a clearly labelled synthetic fallback with the same schema and log a warning; the demo must not die on a network error.

| Need | Source | Notes |
| --- | --- | --- |
| Best-track history (training + truth) | NHC HURDAT2 Atlantic text file: `https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2023-051124.txt` (use the latest filename on `https://www.nhc.noaa.gov/data/#hurdat`) | Parse to a tidy frame: storm_id, name, time, lat, lon, vmax_kt, pmin_mb, status, wind radii |
| Official forecasts for Ian (what NHC knew at each advisory) | ATCF a-deck `aal092022.dat` from `https://ftp.nhc.noaa.gov/atcf/archive/2022/` (gzip) | Use tech `OFCL` as the official forecast and `CARQ` as the current state at advisory time. These are the "weather data in" for replay. |
| Evacuation zones, Lee County | Lee County GIS open data (ArcGIS REST, search "Lee County Evacuation Zones" feature service). Export GeoJSON to `data/static/zones.geojson` | Zones A–E. If unreachable: build 5 synthetic zones from distance-to-coast bands over the county polygon. |
| County boundary, census block groups, population, no-vehicle households | Census TIGER block groups 2022 for FL + ACS 5-year table B08201 via the Census API (no key needed below rate limit) | Clip to county. Fallback: uniform synthetic population by area. |
| Elevation | SRTM 1-arc-second or Copernicus DEM tiles for the bbox (`elevation` or `py3dep` package) | Used by the surge proxy. Fallback: distance-to-coast proxy. |
| Road network | OpenStreetMap via OSMnx | Drive network, simplified, with `maxspeed`, `lanes`, `bridge` tags |
| Shelters | Lee County / Florida Division of Emergency Management shelter list. Commit a curated CSV `data/static/shelters.csv` with name, lat, lon, capacity, is_special_needs. | ~12 sites is enough. Use real names and locations. |
| Hospitals | HIFLD hospitals (open) clipped to county → `data/static/hospitals.csv` with beds, has_helipad, trauma_level | Lee Memorial, Gulf Coast Medical Center, Cape Coral Hospital, HealthPark, NCH (Collier, for overflow) |
| Depots / staging | Curated CSV: 1 state logistics staging area (Orlando or Lakeland), 2 county warehouses, 3 big-box retail (water/food) | Include initial inventory per commodity |
| SAR assets | Curated CSV `data/static/assets.csv`: 4 helicopters (2 Coast Guard MH-60, 2 state), 12 high-water trucks, 10 boats, each with base, speed, capacity, endurance | Reasonable public-domain estimates; label as assumptions |

Write `docs/DATA_SOURCES.md` listing every file, its origin, licence, and whether the demo uses real or fallback data.

---

## 6. Chalk feature layer (`chalk/`)

This is where Chalk lives in the app. It serves two roles: **the online feature source for prediction** and **the point-in-time store for model verification**.

### 6.1 Feature classes

```python
from chalk.features import features, DataFrame, FeatureTime, has_many
from datetime import datetime

@features
class StormFix:
    """One best-track or advisory fix for one storm."""
    id: str                      # f"{storm_id}:{time.isoformat()}"
    storm_id: str
    time: FeatureTime
    lat: float
    lon: float
    vmax_kt: float
    pmin_mb: float | None
    status: str                  # TD, TS, HU, EX, ...
    source: str                  # "hurdat2" | "carq" | "ofcl"

@features
class Storm:
    id: str                      # e.g. "AL092022"
    name: str
    basin: str
    fixes: DataFrame[StormFix] = has_many(lambda: StormFix.storm_id == Storm.id)

@features
class StormState:
    """Point-in-time predictor inputs for one storm at one time."""
    id: str                      # f"{storm_id}:{time}"
    storm_id: str
    time: FeatureTime
    lat: float
    lon: float
    vmax_kt: float
    pmin_mb: float
    # lagged motion (6, 12, 24 h)
    dlat_6: float; dlon_6: float; dv_6: float
    dlat_12: float; dlon_12: float; dv_12: float
    dlat_24: float; dlon_24: float; dv_24: float
    heading_deg: float
    speed_kt: float
    day_of_year: int
    sst_proxy_c: float           # climatological SST by lat/lon/month from a small bundled table
    land_distance_km: float      # distance to nearest coastline
    hours_since_genesis: float
    # targets (only populated for training rows)
    tgt_dlat_6: float | None
    tgt_dlon_6: float | None
    tgt_dv_6: float | None
```

### 6.2 Resolvers

- `@offline` resolver that loads HURDAT2 + ATCF into `StormFix` from parquet in `data/cache/`.
- `@online` resolver `storm_state_from_fixes(fixes: Storm.fixes, now: Now) -> StormState` that computes the lagged features from the fixes at or before `now`. This must be **point-in-time**: never read a fix after `now`.
- `@online` resolver for `sst_proxy_c` from a bundled monthly climatology grid (`data/static/sst_clim_2deg.npz`, generate it from a coarse formula if no download: `28 - 0.25*max(0, |lat|-10)` with a seasonal term; document that it is a proxy).
- Training set: `ChalkClient().offline_query(input=..., output=[StormState.*], ...)` over all Atlantic storms 1980–2021, with `now` set to each fix time. This gives point-in-time-correct training rows and is the reason Chalk is here. Write the result to `data/cache/train.parquet`.
- Verification: the same query for Ian at every advisory time, with `StormFix.source == "carq"` only. The predictor must not see HURDAT2 best-track for Ian during the replay.

### 6.3 Local mode

`chalk/local_runtime.py` registers the same resolver functions and runs them with pandas when `CHALK_MODE=local`. Keep one implementation: resolver bodies are plain functions; the Chalk decorators and the local runtime both call them. Test both modes with the same unit tests (`tests/test_features.py`).

### 6.4 Chalk Compute

In `chalk/compute.py`, wrap the Stage-1 sampler and the Stage-3 scenario solver as `@chalkcompute.function` so that `landfall/pipeline.py` can fan out K scenarios across sandboxes when `CHALK_MODE=remote`. If `chalkcompute` import fails or the call fails, fall back to `joblib` locally and log it. Do not block the demo on this.

Write `docs/ARCHITECTURE.md` with a section "Why Chalk" that states: one feature definition, point-in-time-correct training and verification, online serving for the live/replay predictor, and optional compute fan-out.

---

## 7. Stage 1 — Hurricane prediction Monte Carlo (`landfall/predict/`)

### 7.1 Model

A **6-hour step predictor** with residual sampling. This is intentionally small so it trains in minutes and is explainable.

- Inputs: the `StormState` feature vector (Section 6.1), standardised.
- Targets: `tgt_dlat_6`, `tgt_dlon_6`, `tgt_dv_6` (change over the next 6 h).
- Architecture: an MLP (3 × 256, GELU, dropout 0.1) in PyTorch trained on the GPU, **or** `lightgbm` with 3 regressors if the GPU path takes more than 45 minutes to get working. Pick one, document it in `docs/MODEL_CARD.md`.
- Residual model: fit the empirical residual distribution per lead-time bucket on a validation split. Store a **residual bank** (array of residual vectors) per bucket. Sampling draws from this bank with a small Gaussian jitter. Residuals must grow with lead time; verify this in the model card.
- Intensity constraints during rollout: `vmax` clipped to [15, 165] kt; over land (`land_distance_km < 0`) apply decay `vmax *= exp(-0.07 * 6h)` plus the model term; dissipate (stop the track) if `vmax < 20` for 12 h.
- Baseline: **CLIPER-lite** — persistence of the last 12-h motion vector plus climatological drift. Required for the verification panel.

### 7.2 Monte Carlo rollout (`sample.py`)

```
inputs : StormState at t0 (from Chalk, source=carq), N (default 1000), horizon H (default 120 h)
loop   : for each of N samples, for step in 0..H/6:
           pred = model(state) + residual_bank[bucket(step)].sample() + jitter
           state = advance(state, pred)            # update lat/lon/vmax, recompute lagged features
         record track
outputs: tracks.npz  (N × T × [lat, lon, vmax, pmin])
         cone.geojson (p50/p66/p90 polygons per lead time, via per-step 2D quantile hull)
         landfall.json: p(landfall in county), landfall time distribution (p10/p50/p90), category distribution at landfall
```

Seed with `LANDFALL_SEED`. N=1000 must run in under 60 s on CPU.

### 7.3 Scenario reduction (`reduce.py`)

Reduce N tracks to K=20 representative scenarios: k-medoids on a track distance (sum of great-circle distances at matched times, plus a weighted intensity term). Each scenario carries `probability = cluster_size / N`. Always include the official NHC forecast (`OFCL`) as scenario 0 with its cluster's probability for comparison.

### 7.4 Verification (`verify.py`)

For each Ian advisory time from 2022-09-23 to 2022-09-28 (every 6 h):
- Pull `StormState` as of that time from Chalk (carq only).
- Roll out N=500, take the ensemble mean track.
- Compute great-circle track error and absolute intensity error at 12/24/48/72/96 h vs HURDAT2 truth.
- Do the same for CLIPER-lite and for the official `OFCL` forecast.
- Write `out/verify/errors.csv` and `out/verify/summary.json` (mean error per lead time per method, ensemble spread, rank histogram for calibration).

The honest expected result: the model beats CLIPER-lite and loses to OFCL. Say that in the model card. Do not tune on Ian.

---

## 8. Stage 2 — Impact model (`landfall/impact/`)

All on a 500 m raster over the county bbox (`numpy` grids, stored as `.npz`, exported to GeoJSON contours for the UI).

- **Wind** (`wind.py`): for each scenario and hour, a Holland (1980) symmetric wind profile: `V(r) = Vmax * sqrt( (Rmax/r)^B * exp(1 - (Rmax/r)^B) )` with `Rmax = 35 km` for Cat 3+, 50 km otherwise, `B = 1.3`. Add 60% of forward motion on the right-hand side. Output per cell: peak gust, hours of ≥ 34 kt, ≥ 64 kt, and `t_ts_arrival` (first hour with ≥ 34 kt). Document the simplification.
- **Surge** (`surge.py`): a proxy, not SLOSH. Peak surge at the coast `S_coast = 0.0084 * Vmax_kt^1.7 * k_angle` metres where `k_angle = max(0.3, cos(approach angle))`, applied within `3 * Rmax` to the right of landfall, decaying linearly to 0 at `6 * Rmax`. Inland extent: cells with elevation (DEM) below `S_coast` and within 15 km of coast get `depth = S_coast - elevation`. Calibrate the constant so that Ian's truth track gives 3.5–4.5 m near Fort Myers Beach. State this calibration in the docs.
- **Damage** (`damage.py`): per block group, `p_major_damage = sigmoid(a * (gust - 95 mph)) * (1 + 0.5 * surge_depth)`; expected injuries = `population * p_major * 0.02 * (1 - evacuated_fraction)`; expected rescue requests = `population * (1 - evacuated_fraction) * p(surge_depth > 1 m) * 0.3`. These are documented assumptions, surfaced in the UI as "model assumptions".
- **Roads** (`roads.py`): per edge, `p_blocked = 1 - (1 - p_tree) * (1 - p_flood) * (1 - p_bridge)` where `p_tree = sigmoid(c*(gust - 80 mph)) * tree_cover_proxy`, `p_flood = 1 if surge_depth > 0.3 m else 0`, `p_bridge = 0.5 if bridge and gust > 120 mph`. Sample a blocked set per scenario with the seed. Barrier-island causeways (Sanibel Causeway, Matlacha Pass bridge, Pine Island Road) are flagged as **critical links**; this is what Ian actually destroyed and the demo should show it.

---

## 9. Stage 3 — Logistics Monte Carlo (`landfall/logistics/`)

Runs once per reduced scenario (K=20), each with `M=5` internal draws of behaviour and road-blockage (so 100 logistics samples). Solve time target: under 10 s per scenario sample on CPU. Precompute all of it in `make demo`.

### 9.1 First-stage decisions (shared across scenarios)

Solve one two-stage stochastic LP for these decisions, with the K scenarios and their probabilities:
- `release_time[zone]` — hours after T0 to issue the evacuation order for each zone (discretised to 6-h bins).
- `open[shelter]` — binary, which shelters to open.
- `stage[depot, commodity]` — units of water, food, medical kits, fuel, generators to pre-position.

Recourse per scenario: time-expanded evacuation flow and supply flow (Section 9.2–9.3). Objective: `sum_s p_s * ( W1 * persons_not_cleared_s + W2 * unmet_supply_s + W3 * rescue_demand_s ) + W4 * persons_evacuated_unnecessarily + W5 * transport_cost`, with `W1 = 1000, W2 = 50, W3 = 500, W4 = 1, W5 = 0.1`. Solve with HiGHS. If the full LP is too large, use a greedy heuristic over release times with the LP for supply only, and record this in `DECISIONS.md`.

### 9.2 Evacuation (`evacuation.py`)

- Demand per zone = population × compliance (default 0.7, sampled U(0.55, 0.85) per draw) + shadow evacuation from adjacent zones (0.15).
- Departure curve: logistic over 12 h after release.
- Time-expanded road graph on a 1-h grid; edge capacity = lanes × 1800 veh/h × 0.7; vehicles per household 1.3.
- Route assignment: iterative capacity-aware shortest path (5 rounds of incremental loading). Destinations: nearest open shelter with remaining capacity or the county's out-of-county exits (I-75 N, I-75 S, SR-80 E).
- Outputs per scenario: clearance time per zone, persons not cleared before `t_ts_arrival`, congestion per edge per hour, routes as polylines with vehicle counts.

### 9.3 Medical supply (`supply.py`)

- Demand per shelter and hospital per 12-h window: `water (L) = people * 4`, `food (meals) = people * 3`, `medical kits = injuries * 1.2 + people * 0.01`, `fuel (L) = generators * 24 * 10`, `generators = 1 per 200 sheltered + 2 per hospital without grid power` (grid outage sampled from gust > 100 mph).
- Min-cost flow / LP from depots to sites over the (post-landfall, blocked-edge) road graph with truck capacity (`3000 kg`), truck count, and travel times. Pre-landfall deliveries use the unblocked graph; post-landfall use the scenario's blocked set.
- Outputs: shipments (truck, from, to, commodity, qty, depart_t, arrive_t, path), unmet demand per site per window.

### 9.4 SAR and medevac (`sar.py`, `medevac.py`)

- Rescue requests per block group from the damage model, placed at random points within the block group, each with a priority (1 = life-threatening, 2 = urgent, 3 = routine) and a required asset type: `boat` if surge depth > 1 m, `high_water_truck` if 0.3–1 m, `helo` if the block group is on a barrier island with all causeways blocked or priority 1 with > 45 min ground ETA.
- Asset routing: OR-Tools VRP with time windows, per asset class, starting at landfall + 6 h (after winds drop below 34 kt in that cell). Helos route by great circle at cruise speed and must return to base before endurance expires.
- Medevac: priority-1 and 20% of priority-2 victims go to a hospital. Choose the nearest hospital with `beds_available > 0` and (for helo) `has_helipad`. Hospital capacity drains and recovers at 10%/day.
- Outputs: task list, assignment per asset with timed waypoints, persons rescued by hour, median time-to-rescue, unmet tasks at +72 h.

### 9.5 Debris and road clearing (`debris.py`)

- Tasks = blocked edges. Priority score = `betweenness_centrality * (1 + hospital_access_weight + shelter_access_weight)`.
- Crews: 8 county crews, 4 state crews with chainsaw/loader, each clears one edge in `max(1 h, 0.5 h per 100 m)`; bridge repairs are tasks with duration 30 days and are shown but not scheduled.
- Greedy schedule by priority with travel time; outputs a crew timeline and the hour each edge reopens. Supply and SAR routing in later hours use the reopened graph.

### 9.6 Infrastructure insight (`infrastructure.py`)

Across all scenarios: for each edge, `p_blocked_any = fraction of scenario samples where blocked` and `criticality = betweenness × population served`. Rank edges by `p_blocked_any × criticality`. The top 10 are the "harden these" list. Also report: zones whose clearance time exceeds `t_ts_arrival` in more than 30% of scenarios ("add road capacity or earlier release") and shelters that fill in more than 50% of scenarios ("add capacity").

### 9.7 Aggregate (`aggregate.py`)

Write `out/plan/aggregate.json` with expected values and p10/p50/p90 for every metric, plus a `worst_case` pointer to the scenario with the highest objective. Write `out/plan/baseline.json` from the baseline plan (release by storm category per the county study: zone A at Cat 1 forecast, B at Cat 2, etc.; supplies staged evenly by population) so the UI can show "optimized vs baseline".

---

## 10. UI (`web/`)

Style target: a satellite-operations console. Dark background, thin monospace HUD text, green/amber/red status colours, scan-line-free (keep it readable). Think "the globe from God's Eye View, repurposed for emergency operations". Do not copy their code; build fresh.

### 10.1 Layout

```
┌───────────────────────────────────────────────────────────────────┐
│ HUD strip: UTC clock · scenario · p(landfall) · ETA TS winds · ▶ ⏸ │
├────────┬──────────────────────────────────────────┬───────────────┤
│ Layer  │                                          │ Right panel   │
│ rail   │              Cesium globe                │ (view-specific│
│ (left) │                                          │  tables)      │
│        │                                          │               │
├────────┴──────────────────────────────────────────┴───────────────┤
│ Timeline: T0 ───────●──────── landfall ────────────── T0+120 h    │
│ scenario strip: ▢ OFCL ▢ s1 ▢ s2 … ▢ worst · [Expected] [Worst 10%]│
└───────────────────────────────────────────────────────────────────┘
```

Views (tabs in the HUD strip): **Command**, **Supply**, **Rescue**, **Model**.

### 10.2 Globe layers

Each layer is a module in `web/src/globe/layers/` with `init(viewer)`, `update(t, scenario)`, `setVisible(bool)`. Data comes from the API as CZML where motion is involved, GeoJSON otherwise.

| Layer | Representation |
| --- | --- |
| Storm ensemble | N=200 thin polylines (subsample) at 15% opacity, the selected scenario at 100%; current storm position as a rotating disc with radius `Rmax` and a vertical column whose height encodes `vmax`; cone polygons p50/p66/p90 as translucent fills draped on terrain |
| Wind field | For the selected scenario and hour: a colour-ramped contour fill (34/50/64/96 kt) draped on terrain |
| Surge | Contour fill of depth (0.3/1/2/3 m) in blue ramp, draped |
| Evacuation zones | Zone polygons, colour = release status at `t` (grey = not ordered, amber = ordered, red = ordered and not cleared by TS arrival in this scenario) |
| Evacuation flow | Edge polylines with width ∝ vehicles/h at `t`, colour by congestion ratio; animated dash to show direction |
| Shelters | Cylinders at shelter sites, height ∝ capacity, fill ∝ occupancy at `t`; label with name and % |
| Hospitals | Red-cross billboards; column height = beds available |
| Depots and trucks | Depot billboards; trucks as CZML point entities moving along paths with `SampledPositionProperty`; trails on |
| Road status | Edges coloured clear / blocked / reopened at `t`; critical links drawn thicker |
| SAR | Rescue requests as heat-ramp points (priority colour), assets (helo/boat/truck) as CZML entities with trails; a line from asset to its current task |
| Debris crews | Crew entities moving; edge turns from red to green when cleared |
| Infrastructure insight | Top-10 harden-list edges in pulsing magenta, togglable |

Camera: default home is an oblique view of Lee County from the south-west at ~60 km altitude. "Follow storm" mode keeps the storm centre in frame. Fly-to on click of any table row.

### 10.3 Timeline

- 1-hour steps, drag scrubber, play at 1×/4×/16× (1 h per 0.5 s at 1×).
- Markers: each NHC advisory time, p50 landfall, truth landfall (shown only after the replay clock passes it, labelled "observed").
- The Cesium `Clock` is the single source of truth; every layer reads `viewer.clock.currentTime`.
- When the clock crosses an advisory time, the storm ensemble re-fetches the precomputed MC for that advisory (so the cone narrows as the storm approaches — this is the demo's hero moment). Precompute Stage 1 for every advisory time; precompute Stage 2–3 for the advisory at T0+48 h (2022-09-27 00Z) and, if time permits, for T0 and T0+72 h.

### 10.4 Right panel per view

- **Command**: KPI cards (persons at risk, expected unmet supply, expected rescues, clearance margin), zone table (release time, clearance time, margin), optimized-vs-baseline bar pairs, "harden these" list.
- **Supply**: depot inventory table, shipments table (filterable by commodity), unmet-demand table per site per window, with a scenario column.
- **Rescue**: task board (priority, type, status at `t`), asset board (status, current task, fuel/endurance remaining), hospital gauges, time-to-rescue histogram.
- **Model** (stretch): error-vs-lead-time chart for model / CLIPER / OFCL; ensemble spread; calibration rank histogram.

Charts: `recharts`. Tables: plain React, virtualised if > 500 rows.

### 10.5 UI copy

All visible strings in `web/src/i18n/en-ste.json`, written in STE. Example: "Select a scenario." not "Pick whichever scenario you'd like to explore."

---

## 11. Build plan (12 h)

Work in this order. Commit at the end of every phase with the phase name in the message. Run `make check` (lint, tests, STE lint) before each commit.

| Hour | Phase | Done when |
| --- | --- | --- |
| 0.0–0.5 | Scaffold | Repo layout, `pyproject.toml`, `web/` Vite+React+Cesium hello-globe with ion token, `Makefile` targets `install`, `data`, `train`, `precompute`, `serve`, `demo`, `check`, `.env.example`, `docs/STE_RULES.md`, `scripts/ste_lint.py` |
| 0.5–1.5 | Ingest | HURDAT2 and ATCF parsers with tests; OSMnx graph cached; zones/shelters/hospitals/depots/assets static files committed; census fallback |
| 1.5–3.0 | Chalk + Stage 1 | Features and resolvers in both modes; training frame; model trained; sampler produces 1000 tracks for Ian at 2022-09-25 00Z in < 60 s; cone GeoJSON; `verify.py` produces `summary.json` for all advisories |
| 3.0–4.0 | Stage 2 | Wind, surge, damage, road grids for K=20 scenarios at one advisory; GeoJSON contours exported |
| 4.0–6.5 | Stage 3 | Evacuation, supply LP, SAR/medevac VRP, debris, infrastructure, aggregate; `out/plan/*.json` complete for the T0+48 h advisory |
| 6.5–7.0 | API | FastAPI serving `out/` plus `POST /rerun` (re-runs Stage 1 for a given advisory; Stage 2–3 only if `?full=1`); CZML export |
| 7.0–10.0 | UI | Layout, timeline, all globe layers, Command/Supply/Rescue panels, scenario picker, follow-storm camera |
| 10.0–11.0 | Polish + precompute | Stage 1 for all advisories; `make demo` end-to-end from a clean clone; home camera; HUD; screenshots in `docs/media/` |
| 11.0–12.0 | Docs + verification | `README.md`, `docs/*`, model card with real numbers from `verify.py`, STE lint clean, `tests/` green, Section 14 acceptance checklist run and recorded in `docs/RUNBOOK.md` |

If you are behind at hour 6.5, drop Section 9.5 (debris crews) to a static blocked-edge list and drop the Model view; keep SAR.

---

## 12. Stretch (only after Section 14 passes)

1. Model view with verification charts.
2. Stage 2–3 precomputed for three advisories so the plan visibly changes as the forecast changes.
3. `POST /rerun?full=1` with a progress stream and a "re-plan" button in the HUD.
4. Chalk Compute fan-out actually used for the K-scenario batch.
5. A "what-if" slider for compliance rate that re-runs evacuation only.
6. Export a PDF briefing (one page per view) with `playwright` screenshots.
7. Replace the surge proxy with precomputed SLOSH MOM rasters if downloadable in under 20 minutes.

Not in scope: live traffic, multi-county, crowd-sourced photos, 3D reconstruction from user video, floods and wildfire. Leave hooks (`hazard_type` field) but do not build them.

---

## 13. Documentation rules — ASD-STE100

All human-readable documentation must follow ASD-STE100 (Simplified Technical English). This applies to `README.md`, every file in `docs/`, every Python docstring, every TypeScript JSDoc block, and every string in `web/src/i18n/en-ste.json`. Code identifiers, commit messages, log lines, and this prompt are exempt.

Write `docs/STE_RULES.md` with the rules below, and implement `scripts/ste_lint.py` to check the mechanical ones. `make check` fails if the linter fails.

### 13.1 Writing rules (apply all)

1. Use only approved words, or technical names and technical verbs. If a word is not in the STE dictionary, use it only if it is a technical name (for example "Monte Carlo", "FastAPI", "Cesium", "HiGHS") or a technical verb specific to the domain.
2. Use the approved meaning of a word. Example: "close" is a verb only ("close the valve"), not an adjective ("close to the coast" → "near the coast").
3. Keep to one topic per sentence.
4. Procedural sentences: maximum 20 words. Descriptive sentences: maximum 25 words.
5. Paragraphs: maximum 6 sentences in descriptive text.
6. Use the active voice. Say who does what. "The model predicts the track." not "The track is predicted."
7. Use the imperative in procedures. "Run `make demo`." not "You should run `make demo`."
8. Use simple verb forms: infinitive, imperative, simple present, simple past, future with "will". Do not use the present participle as a verb ("is running" → "runs") or gerunds as nouns ("after training" → "after you train the model").
9. Do not use the passive voice in procedures. In descriptive text, use the passive only when the agent is unknown.
10. Use an article ("a", "an", "the") or a demonstrative ("this", "these") before a noun where possible.
11. Do not use noun clusters of more than three nouns. "hurricane track prediction model output" → "the output of the track prediction model".
12. Write one instruction per sentence, unless two actions must occur at the same time.
13. Start a safety instruction with a clear condition and a command. "If the download fails, use the fallback data."
14. Use "that" for restrictive clauses and avoid "which" where possible.
15. Do not use slang, idioms, humour, or marketing language.
16. Numbers: use digits for all numbers except at the start of a sentence. Give units in SI with the US unit in parentheses where the source data is in US units (kt, mph, ft).
17. Warnings and cautions are set off on their own line and start with the word WARNING: or CAUTION:.
18. Use consistent terminology. One concept, one term. Keep a glossary in `docs/STE_RULES.md`: scenario, advisory, track, fix, zone, release time, clearance time, shelter, depot, asset, task, blocked edge, critical link.
19. Use vertical lists for sequences of more than two items.
20. Avoid these words and use the replacement: "utilize" → "use"; "leverage" → "use"; "in order to" → "to"; "prior to" → "before"; "subsequent to" → "after"; "a number of" → "some" or a digit; "ensure" → "make sure"; "robust" → delete or "strong"; "seamless" → delete; "optimal" → "best"; "perform" → "do"; "commence" → "start"; "terminate" → "stop"; "facilitate" → "help"; "approximately" → "about"; "additional" → "more"; "assist" → "help"; "indicate" → "show".

### 13.2 `scripts/ste_lint.py` checks

- Sentence length over 25 words (error) and over 20 words inside a numbered procedure (error).
- Any word from the Section 13.1 rule-20 list (error, with the replacement).
- Passive-voice heuristic: a form of "be" followed within 2 tokens by a past participle ending in "-ed" or a bundled irregular list (warning).
- Present participle as a main verb: a form of "be" followed by a "-ing" word (warning).
- Paragraphs over 6 sentences (warning).
- Noun clusters: 4+ consecutive capitalised or dictionary-noun tokens (warning; keep the dictionary small and bundled).
- Scope: `README.md`, `docs/**/*.md`, Python docstrings (parse with `ast`), TypeScript JSDoc (regex for `/** ... */`), `web/src/i18n/en-ste.json` values. Code blocks and tables are skipped.
- Exit non-zero on any error. Print file:line and the rule.

Document every linter limitation in `docs/STE_RULES.md`.

---

## 14. Acceptance checklist

Run these from a clean clone with a valid `.env`. Record the result of each line in `docs/RUNBOOK.md`.

1. `make demo` completes with no manual step and opens `http://localhost:5173`.
2. `CHALK_MODE=local make demo` also completes.
3. `make check` passes: `ruff`, `pytest`, `tsc --noEmit`, `eslint`, `scripts/ste_lint.py`.
4. At T0 (2022-09-25 00Z) the p90 cone covers both Tampa Bay and Fort Myers. At 2022-09-27 00Z it has narrowed to the Charlotte Harbor–Fort Myers area. At 2022-09-28 12Z, p(landfall in Lee County) > 0.5.
5. `out/verify/summary.json` shows the model's 48-h mean track error lower than CLIPER-lite for Ian. Values are quoted in `docs/MODEL_CARD.md`.
6. In the selected worst-case scenario, at least one of Sanibel Causeway, Matlacha Pass bridge, or the Pine Island Road is blocked, and the Rescue view assigns a helicopter to a barrier-island task.
7. The Command view shows optimized vs baseline, and the optimized plan has lower "persons not cleared" in expectation.
8. Dragging the timeline moves trucks, helicopters, and the storm continuously; shelters fill; roads change colour.
9. Clicking a shipment row flies the camera to the truck.
10. N=1000 Stage-1 rollout completes in under 60 s; the full Stage 3 for K=20, M=5 completes in under 15 minutes on CPU (precomputed, not at demo time).
11. No file in the repo contains an API key. `.env.example` lists every variable: `CESIUM_ION_TOKEN`, `CHALK_MODE`, `CHALK_CLIENT_ID`, `CHALK_CLIENT_SECRET`, `CHALK_ENVIRONMENT`, `LANDFALL_SEED`, `CENSUS_API_KEY` (optional).
12. `README.md` has: what it is (3 sentences), quick start (5 commands max), a screenshot, the data and assumptions table, the licence. All in STE.

---

## 15. Engineering conventions

- Python: `ruff` (line length 100), type hints everywhere, `pydantic` models for every JSON artifact in `landfall/schemas.py`. Every stage reads and writes only through those models.
- Tests: `pytest` with small fixtures. Required tests: HURDAT2 parser on a bundled excerpt; `StormState` lag features in both Chalk modes; sampler determinism with a seed; wind profile value at `r = Rmax` equals `Vmax`; evacuation clearance on a 3-node toy graph; supply LP feasibility on a toy instance; SAR assignment on 5 tasks and 2 assets; STE linter on a fixture with known violations.
- TypeScript: strict mode, no `any`. Zustand for state. One file per globe layer.
- Logging: `structlog` to stdout, one line per stage with timings.
- Determinism: everything seeded from `LANDFALL_SEED` (default 42). Artifacts carry the seed and the git SHA in their metadata.
- Every modelling assumption appears in three places: the code (as a named constant in `landfall/config.py`), `docs/MODEL_CARD.md`, and the UI "Assumptions" drawer in the HUD.
- Never silently fall back. Every fallback logs a `WARNING` and sets `metadata.used_fallback = true` in the artifact, and the HUD shows a small amber "FALLBACK DATA" chip when any artifact used one.

---

## 16. What to tell the user at the end

Finish with a short report in the terminal, in this order: what works, what used fallback data, the verification numbers (48-h track error for model vs CLIPER vs OFCL), which stretch items were done, and the exact command to start the demo. Keep it under 30 lines.

Begin.
