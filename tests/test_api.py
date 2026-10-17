"""Test the FastAPI endpoints."""

from fastapi.testclient import TestClient

from api.main import OUT, app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/api/health").json() == {"ok": True}


def test_meta_and_static_files() -> None:
    r = client.get("/api/meta")
    if not (OUT / "meta.json").exists():
        assert r.status_code == 404
        return
    meta = r.json()
    assert meta["storm_id"] == "AL092022"
    assert meta["metadata"]["seed"] == 42
    key = meta["advisories"][0][:13].replace("-", "").replace("T", "")
    assert client.get(f"/out/stage1/{key}/ensemble.json").status_code == 200


def test_rerun_rejects_bad_advisory() -> None:
    assert client.post("/api/rerun?advisory=abc").status_code == 422
    assert client.get("/api/rerun/nope").status_code == 404
