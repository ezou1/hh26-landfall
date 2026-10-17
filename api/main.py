"""Serve the LANDFALL artifacts and the rerun endpoint with FastAPI.

Endpoints:

- GET /api/health returns the server status.
- GET /api/meta returns out/meta.json.
- GET /out/<path> returns a file from out/.
- POST /api/rerun?advisory=YYYYMMDDHH&full=0|1 starts a rerun job in the background.
- GET /api/rerun/<job_id> returns the status of a rerun job.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)

app = FastAPI(title="LANDFALL API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


@app.get("/api/health")
def health() -> dict[str, bool]:
    """Return the server status."""
    return {"ok": True}


@app.get("/api/meta")
def meta() -> FileResponse:
    """Return the index of the artifacts."""
    path = OUT / "meta.json"
    if not path.exists():
        raise HTTPException(404, "out/meta.json does not exist. Run make precompute.")
    return FileResponse(path, media_type="application/json")


def _run_job(job_id: str, advisory: str, full: bool) -> None:
    """Run the pipeline for one advisory in a subprocess and record the progress."""
    cmd = [sys.executable, "-m", "landfall.pipeline", "--advisory", advisory, "--skip-verify",
           "--plans", advisory if full else ""]
    job = JOBS[job_id]
    try:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
        assert proc.stdout is not None
        steps = ["stage1.ensemble", "stage1.reduce", "stage2", "stage3.first_stage", "stage3.monte_carlo",
                 "pipeline done"] if full else ["stage1.ensemble", "stage1.landfall", "stage1.reduce", "pipeline done"]
        for line in proc.stdout:
            for i, s in enumerate(steps):
                if s in line:
                    job["progress"] = max(job["progress"], (i + 1) / len(steps))
                    job["message"] = s
        rc = proc.wait()
        job["status"] = "done" if rc == 0 else "error"
        job["progress"] = 1.0 if rc == 0 else job["progress"]
        if rc != 0:
            job["message"] = f"pipeline exit code {rc}"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["message"] = str(exc)


@app.post("/api/rerun")
def rerun(advisory: str = Query(..., pattern=r"^\d{10}$"), full: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    """Start a rerun of Stage 1 for one advisory. With full=1, also run Stage 2 and Stage 3."""
    with _LOCK:
        if any(j["status"] == "running" for j in JOBS.values()):
            raise HTTPException(409, "A rerun job is in progress.")
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"job_id": job_id, "status": "running", "progress": 0.0, "message": "started",
                        "advisory": advisory, "full": bool(full)}
    threading.Thread(target=_run_job, args=(job_id, advisory, bool(full)), daemon=True).start()
    return {"job_id": job_id, "status": "started"}


@app.get("/api/rerun/{job_id}")
def rerun_status(job_id: str) -> dict[str, Any]:
    """Return the status of a rerun job."""
    if job_id not in JOBS:
        raise HTTPException(404, "unknown job")
    return JOBS[job_id]


app.mount("/out", StaticFiles(directory=str(OUT)), name="out")
