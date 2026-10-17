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

ACCEPTANCE_TABLE
