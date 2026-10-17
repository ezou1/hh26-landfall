# LANDFALL in 2 minutes

This file is the spoken pitch and a plain description of the backend. Read it aloud in about 2 minutes. The text follows the STE rules in `docs/STE_RULES.md`.

## The problem (30 s)

A hurricane forecast tells a county where the storm can go. It does not tell the county what to do. An emergency manager must still decide 4 things, hours before landfall:

- When to order each evacuation zone to leave.
- Which shelters to open.
- Where to stage the water, the food, the fuel, and the medical kits.
- Where to send the rescue boats and helicopters after the storm.

Today, people make these decisions with a cone on a map, a clearance-time table, and experience. The cone has no plan inside it. If the track moves 50 km, the plan is wrong, and there is no time to make a new one.

## What LANDFALL does (30 s)

LANDFALL turns the forecast into a plan, and it gives the plan a probability. It replays Hurricane Ian over Lee County, Florida, from 2022-09-25 to 2022-09-30. At each advisory, it predicts 1,000 possible tracks. It converts each track into wind, surge, damage, and blocked roads. Then it plans the evacuation, the supplies, and the rescue work for all of them at once.

The result shows on a 3D globe with a timeline. The manager sees the expected case, the worst 10%, and the one plan that works best across all cases.

## How the backend works (60 s)

The backend is a Python pipeline with 5 steps. Each step writes files that the next step reads.

1. Chalk builds the storm features. It reads the NHC best tracks (HURDAT2) and the live advisory fixes (ATCF). For any time, it computes the position, the wind, the recent motion, the sea temperature, and the distance to land. Chalk only reads the data that existed at that time, so the model trains on honest history.
2. Stage 1 predicts the storm. A small neural network predicts the change in position and wind over the next 6 h. The sampler adds a real forecast error from past storms at each step. It rolls 1,000 tracks forward 5 days. Then k-medoids reduces them to 20 scenarios with probabilities. The official NHC forecast is always scenario 0.
3. Stage 2 computes the impact of each scenario on a 500 m grid. It uses a Holland wind profile, a surge proxy, elevation data, and census block groups. It gives the gust, the flood depth, the damage chance, the injuries, and the rescue requests. It also gives the blockage chance of each road segment.
4. Stage 3 plans the response. First, a search sets the release time of each zone. A flood rule picks the shelters. A HiGHS linear program stages the supplies. These decisions are the same in every scenario, because the county must decide before it knows the track. Then each scenario runs 5 draws of compliance, blocked roads, and rescue requests. Each draw runs the evacuation traffic, the truck deliveries, the OR-Tools rescue routing, and the debris crews. A baseline plan that follows the county category rules runs on the same draws.
5. FastAPI serves the files. The React and Cesium UI reads the JSON, GeoJSON, and CZML files and shows them on the globe. A rerun endpoint computes one advisory again in the background.

## Numbers you can say out loud

- The predictor trains on Atlantic storms from 1980 to 2014 and validates on 2015 to 2021. Ian is in neither set.
- On Ian, the ensemble beats the climatology baseline from 24 h to 96 h. It does not beat the NHC forecast, because NHC has dynamical models and LANDFALL does not.
- The median ensemble spread matches the median error at each lead time, so the cone is honest.
- With the 2022-09-27 advisory, the optimized plan leaves 1,358 persons not cleared before tropical-storm winds. The baseline leaves 2,049.
- In the worst scenario, debris and water block the Sanibel Causeway and the Matlacha Pass Bridge. The plan sends helicopters to 102 island tasks.
- `make check` runs ruff, 28 tests, tsc, eslint, and the STE linter. All pass.

## Where the data comes from

| Data | Source |
| --- | --- |
| Storm history and advisories | NHC HURDAT2 and the ATCF a-deck |
| Evacuation zones | Lee County GIS |
| Population | Census TIGER 2022 and ACS 5-year tables |
| Elevation | Copernicus GLO-30 DEM |
| Roads | OpenStreetMap through OSMnx |
| Shelters, hospitals, depots, assets | Curated files; the capacities are assumptions |

## Why Chalk

The predictor must never see the future. Chalk resolves each training row at its own fix time, so a row for 2004-09-01 06:00 only knows the fixes before that time. The same resolvers run online for the replay. In remote mode, Chalk runs them in its cloud. In local mode, the same functions run in the process with pandas. The remote query and the local query give the same 19 features.

## Limits to say if someone asks

- The surge model is a proxy, not SLOSH. We fit one constant so that the true Ian track gives 4 m at Fort Myers Beach.
- The predictor has no steering flow, so it cannot predict a turn that a trough causes.
- Shelter capacities, depot stocks, and rescue assets are assumptions.

WARNING: LANDFALL is a demonstration. Do not use it for operational emergency decisions.
