"""End-to-end API workflow, matching the specification's endpoint list."""
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_home():
    assert client.get("/api/health").json()["status"] == "ok"
    assert "dataset_status" in client.get("/api/home").json()


def test_canonical_fields_exposed():
    d = client.get("/api/dataset/fields").json()
    fields = {f["field"] for f in d["fields"]}
    assert {"timestamp", "source_worker", "destination_worker"} <= fields
    assert ".xlsx" in d["allowed_extensions"]


def test_rejects_disallowed_extension():
    r = client.post("/api/dataset/upload",
                    files={"file": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")})
    assert r.status_code == 400
    assert "not allowed" in r.json()["detail"]


def test_rejects_unreadable_file():
    r = client.post("/api/dataset/upload",
                    files={"file": ("junk.xlsx", b"\x00\x01\x02\x03", "application/vnd.ms-excel")})
    assert r.status_code == 400


def test_full_workflow(sample_path):
    up = client.post("/api/dataset/upload",
                     files={"file": (sample_path.name, sample_path.read_bytes(),
                                     "application/vnd.ms-excel")})
    assert up.status_code == 200
    did = up.json()["dataset_id"]

    wb = client.get(f"/api/dataset/{did}").json()["workbook"]
    assert wb["physical_format"] == "delimited-text"

    mp = client.get(f"/api/dataset/{did}/mapping").json()
    mapping = {s["field"]: s["suggested_column"] for s in mp["suggestions"]}

    prep = client.post(f"/api/dataset/{did}/prepare",
                       json={"sheet": None, "mapping": mapping, "cleaning": None})
    assert prep.status_code == 200
    body = prep.json()
    assert body["summary"]["contacts"] > 1000
    assert len(body["funnel"]) >= 5

    val = client.get(f"/api/dataset/{did}/validation").json()
    assert val["validation"]["valid_rows"] > 0

    cfg = client.get(f"/api/dataset/{did}/configuration").json()
    assert cfg["column_mapping"]["source_worker"] == "col_1"

    exp = client.post("/api/experiment", json={
        "dataset_id": did, "name": "pytest", "repetitions": 3,
        "workers": {"mode": "top_n", "count": 6, "min_contacts": 5},
        "tasks": {"n_tasks": 25},
        "simulation": {"seed": 4242},
    })
    assert exp.status_code == 200
    eid = exp.json()["experiment_id"]

    run = client.post(f"/api/experiment/{eid}/run?background=false")
    assert run.status_code == 200
    assert client.get(f"/api/experiment/{eid}/status").json()["status"] == "completed"

    res = client.get(f"/api/experiment/{eid}/results").json()
    comp = res["comparison"]
    assert set(comp["algorithms"]) == {"LUCF", "LRSTF", "RWTS-M", "RWTS-ER", "Oracle"}
    for algo in comp["algorithms"]:
        s = comp["aggregate"][algo]["total_weighted_completion_time"]
        assert s["n"] == 3 and s["mean"] > 0 and s["ci_low"] <= s["mean"] <= s["ci_high"]
    assert comp["approximation_ratios"]["total_weighted_completion_time"]["Oracle"]["mean"] \
        == pytest.approx(1.0)

    ws = client.get(f"/api/experiment/{eid}/workers").json()["workers"]
    assert all("true_reliability" in w and "wrs" in w for w in ws)

    ts = client.get(f"/api/experiment/{eid}/tasks").json()["tasks"]
    assert all(t["status"] in ("COMPLETED", "EXPIRED") for t in ts)

    for kind, fmt in [("aggregated", "csv"), ("aggregated", "xlsx"), ("raw", "csv"),
                      ("config", "json"), ("summary", "md"), ("chart", "png"),
                      ("charts", "pdf"), ("bundle", "zip")]:
        r = client.get(f"/api/results/{eid}/export?kind={kind}&fmt={fmt}")
        assert r.status_code == 200 and len(r.content) > 100, (kind, fmt)

    for fmt in ("csv", "json", "xlsx"):
        assert client.get(f"/api/dataset/{did}/export?fmt={fmt}").status_code == 200

    hist = client.get("/api/experiment").json()["experiments"]
    assert any(e["experiment_id"] == eid for e in hist)


def test_unknown_algorithm_is_rejected(prepared_dataset):
    r = client.post("/api/experiment", json={"dataset_id": prepared_dataset,
                                             "algorithms": ["NOPE"]})
    assert r.status_code == 400


def test_missing_experiment_returns_404():
    assert client.get("/api/experiment/EXP-NOTREAL").status_code == 404
