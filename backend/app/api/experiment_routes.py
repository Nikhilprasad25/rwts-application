"""Experiment endpoints (spec section 36)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from app.algorithms.registry import catalogue
from app.experiments import runner
from app.experiments.configuration import DEFAULT_SENSITIVITY, ExperimentConfig
from app.reliability.distributions import DISTRIBUTIONS

router = APIRouter(prefix="/api/experiment", tags=["experiment"])


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:                                 # pragma: no cover
        raise HTTPException(500, str(exc)) from exc


@router.get("/options")
def options() -> dict[str, Any]:
    return {
        "algorithms": catalogue(),
        "reliability_distributions": DISTRIBUTIONS,
        "sensitivity_defaults": DEFAULT_SENSITIVITY,
        "defaults": ExperimentConfig.from_dict({"dataset_id": "-"}).to_dict(),
    }


@router.get("")
def list_experiments() -> dict[str, Any]:
    return {"experiments": runner.list_experiments()}


@router.post("")
def create(body: dict[str, Any]) -> dict[str, Any]:
    return _guard(runner.create, body)


@router.get("/{experiment_id}")
def get(experiment_id: str) -> dict[str, Any]:
    return _guard(runner.get, experiment_id)


@router.post("/{experiment_id}/run")
def run(experiment_id: str, background: bool = Query(True)) -> dict[str, Any]:
    _guard(runner.get, experiment_id)
    if background:
        runner.run_async(experiment_id)
        return {"experiment_id": experiment_id, "status": "running"}
    return _guard(runner.run, experiment_id)


@router.get("/{experiment_id}/status")
def status(experiment_id: str) -> dict[str, Any]:
    return _guard(runner.status, experiment_id)


@router.post("/{experiment_id}/cancel")
def cancel(experiment_id: str) -> dict[str, Any]:
    runner.cancel(experiment_id)
    return {"experiment_id": experiment_id, "status": "cancelling"}


@router.get("/{experiment_id}/results")
def results(experiment_id: str) -> dict[str, Any]:
    return _guard(runner.results, experiment_id)


@router.get("/{experiment_id}/metrics")
def metrics(experiment_id: str) -> dict[str, Any]:
    res = _guard(runner.results, experiment_id)
    return {"comparison": res["comparison"],
            "conditions": [{"label": c["label"], "comparison": c["comparison"],
                            "config_overrides": c.get("config_overrides", {})}
                           for c in res["conditions"]]}


@router.get("/{experiment_id}/workers")
def workers(experiment_id: str, algorithm: str | None = None) -> dict[str, Any]:
    res = _guard(runner.results, experiment_id)
    details = res.get("details", {})
    algo = algorithm or next(iter(details), None)
    if algo not in details:
        raise HTTPException(404, "No worker detail stored for that algorithm.")
    return {"algorithm": algo, "workers": details[algo]["workers"],
            "wrs_history": details[algo]["wrs_history"],
            "note": "true_reliability is SYNTHETIC ground truth, visible only to "
                    "the simulator and the Oracle scheduler."}


@router.get("/{experiment_id}/tasks")
def tasks(experiment_id: str, algorithm: str | None = None,
          limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    res = _guard(runner.results, experiment_id)
    details = res.get("details", {})
    algo = algorithm or next(iter(details), None)
    if algo not in details:
        raise HTTPException(404, "No task detail stored for that algorithm.")
    return {"algorithm": algo, "tasks": details[algo]["tasks"][:limit]}
