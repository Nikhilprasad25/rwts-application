"""RWTS research simulation platform — FastAPI application entry point."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import dataset_routes, experiment_routes, result_routes
from app.config import (APP_VERSION, FRONTEND_DIR, STORAGE_DIR,
                        STORAGE_NOTICE, SYNC_CLIENT)
from app.data import dataset_manager as dm
from app.experiments import runner
from app.evaluation.metrics import CMS_METRIC

app = FastAPI(
    title="Reliability-Weighted Task Scheduling — Research Simulation Platform",
    description="CS427 project: RWTS for crowdsourcing in mobile social networks.",
    version=APP_VERSION,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

app.include_router(dataset_routes.router)
app.include_router(experiment_routes.router)
app.include_router(result_routes.router)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "storage_dir": str(STORAGE_DIR),
        "sync_client": SYNC_CLIENT,
        "storage_notice": STORAGE_NOTICE,
    }


@app.get("/api/home")
def home() -> dict[str, Any]:
    """Dashboard home summary (spec section 26)."""
    datasets = dm.list_datasets()
    experiments = runner.list_experiments()
    prepared = [d for d in datasets if d["prepared"]]
    active = prepared[0] if prepared else (datasets[0] if datasets else None)
    summary = None
    if active and active.get("summary"):
        summary = active["summary"]
    last = experiments[0] if experiments else None
    best = None
    if last and last.get("status") == "completed":
        try:
            comp = runner.results(last["experiment_id"])["comparison"]
            best = comp.get("best", {}).get(CMS_METRIC)
        except Exception:                                    # pragma: no cover
            best = None
    return {
        "dataset_status": ("prepared" if prepared else
                           "uploaded" if datasets else "none"),
        "active_dataset": active,
        "dataset_summary": summary,
        "n_datasets": len(datasets),
        "n_experiments": len(experiments),
        "last_experiment": last,
        "best_algorithm": best,
        "version": APP_VERSION,
        "storage_dir": str(STORAGE_DIR),
        "storage_notice": STORAGE_NOTICE,
    }


# The dashboard is served from the same origin as the API, so the frontend needs
# no CORS handling and no separate web server. Mounted last so /api/* wins.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:                                                        # pragma: no cover
    @app.get("/")
    def index() -> FileResponse:
        raise RuntimeError("frontend directory is missing")
