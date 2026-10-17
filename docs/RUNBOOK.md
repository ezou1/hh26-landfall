# Runbook

This runbook gives the procedures to operate LANDFALL and the results of the acceptance checklist.

## Start the demo

1. Copy `.env.example` to `.env`.
2. Set `CESIUM_ION_TOKEN` if you have a token.
3. Run `make demo`.
4. Open `http://localhost:5173` if the browser does not open.

The first run takes about 25 min on a 12-core CPU. The precompute step takes about 23 min of that time. Later runs skip the precompute step if `out/` is complete.

## Compute the artifacts again

1. Run `make precompute FORCE=1`.
2. Run `make serve`.

## Use the remote Chalk deployment

1. Set `CHALK_MODE=remote` in `.env`.
2. Set `CHALK_CLIENT_ID`, `CHALK_CLIENT_SECRET`, and `CHALK_ENVIRONMENT`.
3. Run `make precompute FORCE=1`.

If a remote query fails, the pipeline uses the local runtime. It logs a WARNING, and the HUD shows the "FALLBACK DATA" chip.

## Rerun one advisory from the UI or the API

1. Send `POST /api/rerun?advisory=2022092712` to run Stage 1 again for one advisory.
2. Add `&full=1` to run Stage 2 and Stage 3 too.
3. Read the status with `GET /api/rerun/<job_id>`.

## Check the build

1. Run `make check`.
2. Run `PYTHONPATH=. .venv/bin/python scripts/acceptance.py` to check the artifacts.

## Troubleshooting

- If the Overpass server is busy, the OSM download tries 4 servers. If all fail, the pipeline uses a synthetic road grid and records a fallback.
- If port 8000 or port 5173 is in use, stop the other process or set `API_PORT` or `WEB_PORT`.
- If the globe shows no imagery, check the network access to `server.arcgisonline.com`.

CAUTION: `make clean-all` deletes the data cache. The next run downloads about 150 MB again.

## Acceptance checklist results

The results come from this build on 2026-10-17. The machine had 12 CPU cores, 15 GB of memory, and no GPU. The runs used no Cesium ion token and no Chalk credentials.

| Item | Result | Details |
| --- | --- | --- |
| 1. `make demo` from a clean clone | ITEM1 | ITEM1D |
| 2. `CHALK_MODE=local make demo` | PASS | Local mode is the default mode, so item 1 also covers it. Remote mode without credentials falls back to local and records the fallback. |
| 3. `make check` | PASS | ruff: all checks passed. pytest: 28 passed. tsc --noEmit and eslint (0 warnings allowed): passed. STE lint: 0 errors in 103 files. |
| 4a. The p90 cone at T0 covers Tampa Bay and Fort Myers | PASS | `scripts/acceptance.py` |
| 4b. At 2022-09-27 00Z the cone narrows to Charlotte Harbor and Fort Myers | FAIL | The p50 cone covers Fort Myers and Charlotte Harbor, but it also covers Tampa Bay. The p90 cone is wider than at T0, because more members live to 120 h and some recurve east. |
| 4c. At 2022-09-28 12Z, p(landfall in Lee County) > 0.5 | FAIL | p = 0.20. The model moves Ian north too fast: the 6-h ensemble mean is at 26.9 N, but the truth is at 26.6 N. The median first landfall is at 27.0 N, about 25 km north of the county line. We did not tune the model on Ian to change this. |
| 5. The 48-h mean track error of the model is less than CLIPER-lite | PASS | Model 432 km, CLIPER-lite 449 km, OFCL 118 km. `docs/MODEL_CARD.md` gives the full table. |
| 6. Worst case: a critical link is blocked and a helicopter has a barrier-island task | PASS | Default plan 2022-09-27 00Z, worst scenario 4: the Sanibel Causeway, the Matlacha Pass Bridge, and Pine Island Road are blocked. Helicopters serve 102 island tasks. The 2022-09-28 00Z plan also passes. In the 2022-09-25 00Z plan, the worst scenario has no island task for a helicopter. |
| 7. Optimized persons not cleared < baseline | PASS | Default plan: 1,358 against 2,049 persons. At 2022-09-28 00Z the two plans are equal (24,774), because no order can clear a zone before the tropical-storm wind. At 2022-09-25 00Z the optimized plan has 37 against 24, because it orders fewer zones to cut unnecessary evacuation. |
| 8. Dragging the timeline moves trucks, helicopters, and the storm; shelters fill; roads change colour | PASS | `web/scripts/motion_check.mjs` sets the clock to fractional hours and checks that the storm, truck tr001, and helicopter a01 move (PASS for all 3). The screenshots show the shelter fill and the road status. A truck trip in Lee County takes only 10 min to 40 min, so each truck is visible for a short time. |
| 9. A click on a shipment row flies the camera to the truck | PASS | `web/scripts/screenshot.mjs` clicks a row and checks that the camera moved near the truck. |
| 10. Stage 1 N = 1000 in less than 60 s; Stage 3 K = 20, M = 5 in less than 15 min | PASS | Stage 1: 13 s or less for each of the 17 advisories. Stage 3: 58 s to 107 s of Monte Carlo for each plan advisory (200 samples on 12 cores). The full precompute took 9 min. |
| 11. No API key in the repository; `.env.example` lists every variable | PASS | `.env` is in `.gitignore`. A search for key patterns found no key. |
| 12. `README.md` has the required parts in STE | PASS | The STE linter reports 0 errors. |

### Notes

- The demo used real data for every source. No fallback was necessary.
- The UI ran without a Cesium ion token, so it used Esri imagery on an ellipsoid. We could not test Google Photorealistic 3D Tiles.
- We could not test `CHALK_MODE=remote` against a real deployment, because no credentials were available.
