# Architecture

LANDFALL has 5 parts. Data flows from the top to the bottom.

```
HURDAT2, ATCF a-deck  ->  Chalk feature layer (chalk/)         StormFix, Storm, StormState
                       ->  Stage 1: track and intensity MC      landfall/predict/
                       ->  Stage 2: impact model                landfall/impact/
                       ->  Stage 3: logistics MC                landfall/logistics/
                       ->  FastAPI (api/) -> React + Cesium UI   web/
```

## Scenario clock

Every artifact uses one clock. The clock has 1-h steps from T0 (2022-09-25 00:00 UTC) to T0 + 120 h. The index of an artifact is (scenario id, time).

## Stages

1. Stage 1 starts from the `StormState` of Chalk at an advisory time. It rolls out 1000 tracks with the 6-h step model and the residual bank. It writes the ensemble, the cone, the landfall summary, and K = 20 scenarios.
2. Stage 2 computes the wind field, the surge depth, the block-group damage, and the edge blockage probability for each scenario. It uses a 500 m grid over the county.
3. Stage 3 solves the first-stage decisions: the release times, the open shelters, and the supply staging. Then it runs M = 5 draws for each scenario: 100 samples for the optimized plan and 100 for the baseline.
4. The pipeline writes JSON, GeoJSON, CZML, and NPZ files to `out/`. Pydantic models in `landfall/schemas.py` validate each JSON file.
5. FastAPI serves `out/`. The UI reads the files and shows them on the globe and in the panels.

## Main modules

| Module | Task |
| --- | --- |
| `landfall/ingest/` | Download and parse the data. Write labelled fallbacks if a download fails. |
| `chalk/features.py` | Declare the feature classes. |
| `chalk/resolvers.py` | Hold the resolver bodies and the Chalk decorators. |
| `chalk/local_runtime.py` | Run the resolvers in-process when `CHALK_MODE=local`. |
| `chalk/compute.py` | Fan out batch work with Chalk Compute, or with joblib. |
| `landfall/predict/` | Train the model, roll out the ensemble, reduce the scenarios, and verify. |
| `landfall/impact/` | Compute wind, surge, damage, and road hazard. |
| `landfall/logistics/` | Solve evacuation, supply, SAR, medevac, and debris. Aggregate the results. |
| `landfall/export/` | Write GeoJSON bands and CZML movers. |
| `landfall/pipeline.py` | Run the stages in order and write `out/`. |
| `api/main.py` | Serve `out/` and the rerun endpoint. |
| `web/` | Show the globe, the timeline, and the panels. |

## Why Chalk

Chalk holds the feature layer of the predictor. It gives 4 benefits:

1. **One feature definition.** `chalk/features.py` declares every predictor input. Training, verification, and replay use the same resolver bodies.
2. **Point-in-time-correct training and verification.** The training frame comes from one offline query over all Atlantic fixes from 1980 to 2021. Each row resolves with "now" equal to its fix time. The resolver never reads a fix after "now". The verification query for Ian reads CARQ fixes only, so the predictor never sees the best track of Ian.
3. **Online serving for the replay predictor.** At each advisory, the pipeline asks Chalk for the online `StormState` of Ian with "now" equal to the advisory time. The ensemble starts from that state.
4. **Optional compute fan-out.** In remote mode, `chalk/compute.py` wraps the Stage 3 scenario solver as a `@chalkcompute.function`. The pipeline fans out the scenario samples to sandboxes. If the call fails, the pipeline uses joblib and logs a WARNING.

### Chalk modes

| Mode | Behaviour |
| --- | --- |
| `CHALK_MODE=local` | `LocalChalkClient` calls the plain resolver functions with pandas. No server is necessary. |
| `CHALK_MODE=remote` | `ChalkClient` uses `CHALK_CLIENT_ID`, `CHALK_CLIENT_SECRET`, and `CHALK_ENVIRONMENT`. If a query fails, the pipeline uses the local runtime and records a fallback. |

The tests in `tests/test_features.py` check the lag features in both modes with one fixture. In remote mode, the test calls the decorated chalkpy resolver without a server.

## Fallbacks

Each download has a fallback with the same schema. A fallback logs a WARNING and writes its name to `data/cache/fallbacks.json`. Each artifact copies the list to `metadata.fallback_items` and sets `metadata.used_fallback`. The HUD shows an amber "FALLBACK DATA" chip if an artifact used a fallback.

## Determinism

`LANDFALL_SEED` (default 42) seeds every random step. Each artifact carries the seed and the git SHA in its metadata.
