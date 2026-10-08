"""Experiment orchestration (spec sections 22, 24, 25, 29, 34).

An experiment is: one prepared dataset + one configuration -> R repetitions,
each repetition being one shared scenario replayed by every selected algorithm.
Sensitivity sweeps re-run the whole thing across a grid of variations.

Everything is persisted as JSON/CSV under ``storage/experiments/<id>/`` so the
project stays database-free (spec 38).
"""
from __future__ import annotations

import json
import threading
import traceback
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from app.algorithms.registry import build
from app import storage_io
from app.config import EXPERIMENT_DIR
from app.data.dataset_manager import load_processed
from app.evaluation import comparison, metrics as metrics_mod
from app.experiments.configuration import ExperimentConfig, SensitivityConfig
from app.experiments.reproducibility import environment, fingerprint
from app.models.contact import ContactRecord
from app.reliability.distributions import ReliabilityConfig, diversity_preset
from app.reliability.wrs import WRSConfig
from app.simulation.engine import SimulationEngine, build_scenario
from app.simulation.task_model import TaskConfig
from app.data.transformer import compute_contact_parameters

_LOCK = threading.Lock()
_CANCELLED: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dir(experiment_id: str) -> Path:
    d = EXPERIMENT_DIR / experiment_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(experiment_id: str, name: str, payload: Any) -> None:
    """Atomic write with retries.

    The status file is polled while the run is in progress, so a partially
    written file must never be visible to a reader — and on Windows a cloud
    sync client can transiently lock the target, which is why the rename is
    retried rather than allowed to abort the experiment.
    """
    storage_io.write_json(_dir(experiment_id) / name, payload)


def _read(experiment_id: str, name: str) -> Any:
    return storage_io.read_json(_dir(experiment_id) / name)


# --------------------------------------------------------------------------- #
def select_workers(params: dict[str, Any], selection) -> list[str]:
    ids = [w for w, p in params.items() if p.contact_count >= selection.min_contacts]
    ids.sort(key=lambda w: -params[w].contact_count)
    if selection.mode == "explicit" and selection.worker_ids:
        chosen = [w for w in selection.worker_ids if w in params]
        return chosen or ids
    if selection.mode == "top_n":
        return ids[: max(selection.count, 1)]
    return ids


# --------------------------------------------------------------------------- #
def create(config_dict: dict[str, Any]) -> dict[str, Any]:
    cfg = ExperimentConfig.from_dict(config_dict)
    experiment_id = f"EXP-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "experiment_id": experiment_id,
        "name": cfg.name,
        "description": cfg.description,
        "created_at": _now(),
        "status": "created",
        "config": cfg.to_dict(),
        "fingerprint": fingerprint(cfg.to_dict()),
        "environment": environment(),
    }
    _write(experiment_id, "experiment.json", record)
    _write(experiment_id, "status.json", {
        "experiment_id": experiment_id, "status": "created", "progress": 0.0,
        "per_algorithm": {a: 0.0 for a in cfg.algorithms},
        "message": "Configured, not yet started.",
    })
    return record


def list_experiments() -> list[dict[str, Any]]:
    out = []
    for d in sorted(EXPERIMENT_DIR.glob("EXP-*"), key=lambda p: p.stat().st_mtime,
                    reverse=True):
        rec = _read(d.name, "experiment.json")
        if not rec:
            continue
        status = _read(d.name, "status.json") or {}
        cfg = rec["config"]
        out.append({
            "experiment_id": rec["experiment_id"],
            "name": rec["name"],
            "created_at": rec["created_at"],
            "dataset_id": cfg["dataset_id"],
            "algorithms": cfg["algorithms"],
            "workers": cfg["workers"]["mode"],
            "tasks": cfg["tasks"]["n_tasks"],
            "reliability_distribution": cfg["reliability"]["distribution"],
            "seed": cfg["simulation"]["seed"],
            "repetitions": cfg["repetitions"],
            "status": status.get("status", rec.get("status")),
            "best_algorithm": (_read(d.name, "results.json") or {})
                .get("comparison", {}).get("best", {})
                .get(metrics_mod.CMS_METRIC),
        })
    return out


def get(experiment_id: str) -> dict[str, Any]:
    rec = _read(experiment_id, "experiment.json")
    if not rec:
        raise KeyError(f"Unknown experiment '{experiment_id}'")
    return rec


def status(experiment_id: str) -> dict[str, Any]:
    return _read(experiment_id, "status.json") or {"status": "unknown"}


def results(experiment_id: str) -> dict[str, Any]:
    r = _read(experiment_id, "results.json")
    if r is None:
        raise KeyError("Results are not available yet.")
    return r


def cancel(experiment_id: str) -> None:
    with _LOCK:
        _CANCELLED.add(experiment_id)


# --------------------------------------------------------------------------- #
def _run_condition(records: list[ContactRecord], params: dict[str, Any],
                   worker_ids: list[str], cfg: ExperimentConfig,
                   repetitions: int, label: str,
                   on_progress: Callable[[float, str, dict[str, float]], None],
                   experiment_id: str,
                   keep_details: bool = True) -> dict[str, Any]:
    lambdas = {w: params[w].lam for w in worker_ids}
    per_run: dict[str, list[dict[str, float]]] = {a: [] for a in cfg.algorithms}
    raw_runs: list[dict[str, Any]] = []
    last_detail: dict[str, Any] = {}
    per_algo_progress = {a: 0.0 for a in cfg.algorithms}

    total = repetitions * max(len(cfg.algorithms), 1)
    done = 0
    for rep in range(repetitions):
        if experiment_id in _CANCELLED:
            break
        scenario = build_scenario(records, lambdas, worker_ids, cfg.tasks,
                                  cfg.reliability, cfg.wrs, cfg.simulation, rep)
        for algo in cfg.algorithms:
            if experiment_id in _CANCELLED:
                break
            scheduler = build(algo, cfg.algorithm_params.get(algo))
            engine = SimulationEngine(scenario, scheduler, cfg.wrs, cfg.outcome,
                                      cfg.simulation)
            run = engine.run()
            m = metrics_mod.compute(run)
            per_run[algo].append(m)
            raw_runs.append({"condition": label, "repetition": rep,
                             "algorithm": algo, "seed": scenario.seed, **m})
            if keep_details and rep == 0:
                last_detail[algo] = {
                    "workers": run["workers"],
                    "wrs_history": run["wrs_history"],
                    "tasks": run["tasks"][:500],
                }
            done += 1
            per_algo_progress[algo] = (rep + 1) / repetitions
            on_progress(done / max(total, 1), label, dict(per_algo_progress))

    comp = comparison.aggregate({a: v for a, v in per_run.items() if v},
                                cfg.confidence)
    return {"label": label, "comparison": comp, "raw_runs": raw_runs,
            "details": last_detail, "repetitions": repetitions}


# --------------------------------------------------------------------------- #
def _sensitivity_conditions(cfg: ExperimentConfig
                            ) -> list[tuple[str, dict[str, Any]]]:
    s: SensitivityConfig = cfg.sensitivity
    out: list[tuple[str, dict[str, Any]]] = []
    for lvl in s.reliability_diversity:
        out.append((f"diversity={lvl}", {"reliability": diversity_preset(lvl)}))
    for dist in s.reliability_distributions:
        out.append((f"distribution={dist}", {"reliability": {"distribution": dist}}))
    for ratio in s.task_worker_ratios:
        out.append((f"task_worker_ratio={ratio}", {"ratio": ratio}))
    for noise in s.wrs_noise_levels:
        out.append((f"wrs_noise={noise}", {"wrs": {"noise_level": noise}}))
    for hist in s.cold_start_history:
        out.append((f"cold_start={hist}", {"simulation": {"cold_start_history": hist}}))
    return out


def _apply_condition(cfg: ExperimentConfig, patch: dict[str, Any],
                     n_workers: int) -> ExperimentConfig:
    new = deepcopy(cfg)
    if "reliability" in patch:
        d = new.reliability.to_dict() | patch["reliability"]
        new.reliability = ReliabilityConfig.from_dict(d)
    if "wrs" in patch:
        d = new.wrs.to_dict() | patch["wrs"]
        new.wrs = WRSConfig.from_dict(d)
    if "simulation" in patch:
        d = new.simulation.to_dict() | patch["simulation"]
        from app.simulation.engine import SimulationConfig
        new.simulation = SimulationConfig.from_dict(d)
    if "ratio" in patch:
        d = new.tasks.to_dict()
        d["n_tasks"] = max(int(round(patch["ratio"] * n_workers)), 1)
        new.tasks = TaskConfig.from_dict(d)
    return new


# --------------------------------------------------------------------------- #
def run(experiment_id: str) -> dict[str, Any]:
    """Synchronously execute an experiment (called on a worker thread)."""
    rec = get(experiment_id)
    cfg = ExperimentConfig.from_dict(rec["config"])
    _CANCELLED.discard(experiment_id)

    def set_status(**kw: Any) -> None:
        cur = status(experiment_id)
        cur.update(kw)
        cur["updated_at"] = _now()
        _write(experiment_id, "status.json", cur)

    set_status(status="running", progress=0.0, started_at=_now(),
               message="Loading prepared dataset…")
    try:
        records, meta = load_processed(cfg.dataset_id)
        params = compute_contact_parameters(
            records, undirected=meta.get("cleaning", {}).get("treat_as_undirected", True))
        worker_ids = select_workers(params, cfg.workers)
        if len(worker_ids) < 2:
            raise ValueError("At least two workers are required after filtering.")

        conditions = ([("baseline", {})] +
                      (_sensitivity_conditions(cfg) if cfg.sensitivity.enabled else []))
        n_cond = len(conditions)

        def progress_cb(frac: float, label: str, per_algo: dict[str, float]) -> None:
            set_status(progress=round((cond_index + frac) / n_cond, 4),
                       message=f"Running {label}", condition=label,
                       per_algorithm=per_algo)

        all_conditions: list[dict[str, Any]] = []
        baseline_result: dict[str, Any] = {}
        for cond_index, (label, patch) in enumerate(conditions):
            ccfg = _apply_condition(cfg, patch, len(worker_ids)) if patch else cfg
            reps = (cfg.sensitivity.repetitions if (patch and cfg.sensitivity.repetitions)
                    else cfg.repetitions)
            res = _run_condition(records, params, worker_ids, ccfg, reps, label,
                                 progress_cb, experiment_id,
                                 keep_details=(label == "baseline"))
            res["config_overrides"] = patch
            all_conditions.append(res)
            if label == "baseline":
                baseline_result = res
            if experiment_id in _CANCELLED:
                break

        if experiment_id in _CANCELLED:
            set_status(status="cancelled", message="Cancelled by the user.")
            return {"status": "cancelled"}

        raw = [r for c in all_conditions for r in c["raw_runs"]]
        pd.DataFrame(raw).to_csv(_dir(experiment_id) / "raw_runs.csv", index=False)

        payload = {
            "experiment_id": experiment_id,
            "dataset": {
                "dataset_id": cfg.dataset_id,
                "filename": meta["original_filename"],
                "summary": meta["summary"],
            },
            "worker_ids": worker_ids,
            "n_workers": len(worker_ids),
            "config": cfg.to_dict(),
            "comparison": baseline_result.get("comparison", {}),
            "details": baseline_result.get("details", {}),
            "conditions": [{k: v for k, v in c.items() if k != "details"}
                           for c in all_conditions],
            "completed_at": _now(),
            "environment": rec["environment"],
            "fingerprint": rec["fingerprint"],
        }
        _write(experiment_id, "results.json", payload)
        rec["status"] = "completed"
        _write(experiment_id, "experiment.json", rec)
        set_status(status="completed", progress=1.0, message="Finished.",
                   finished_at=_now())
        return payload
    except Exception as exc:                                  # pragma: no cover
        set_status(status="failed", message=str(exc),
                   traceback=traceback.format_exc())
        raise


def run_async(experiment_id: str) -> None:
    t = threading.Thread(target=run, args=(experiment_id,), daemon=True)
    t.start()
