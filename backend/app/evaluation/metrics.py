"""Per-run metric computation (spec section 23)."""
from __future__ import annotations

from typing import Any

import numpy as np

CMS_METRIC = "total_weighted_completion_time"
TMS_METRIC = "maximum_completion_time"

METRIC_LABELS: dict[str, str] = {
    "total_weighted_completion_time": "Total Weighted Completion Time (CMS)",
    "maximum_completion_time": "Maximum Completion Time (TMS)",
    "total_cost": "Total Cost",
    "average_completion_time": "Average Completion Time",
    "rework_rate": "Rework Rate (tasks reworked ≥ once)",
    "reworks_per_task": "Reworks per Task",
    "failure_rate": "Failure Rate",
    "deadline_violations": "Deadline Violations",
    "deadline_violation_rate": "Deadline Violation Rate",
    "average_attempts": "Average Attempts per Task",
    "worker_utilisation": "Mean Worker Utilisation",
    "completion_rate": "Completion Rate",
    "expired_tasks": "Abandoned / Unfinished Tasks",
    "runtime_seconds": "Scheduler + Simulation Runtime (s)",
}
LOWER_IS_BETTER = {
    "total_weighted_completion_time", "maximum_completion_time", "total_cost",
    "average_completion_time", "rework_rate", "reworks_per_task", "failure_rate",
    "deadline_violations", "deadline_violation_rate", "average_attempts",
    "expired_tasks", "runtime_seconds",
}


def compute(run: dict[str, Any]) -> dict[str, float]:
    tasks = run["tasks"]
    workers = run["workers"]
    horizon = float(run["horizon"]) or 1.0

    completions = np.array([t["completion_time"] for t in tasks], dtype=float)
    weights = np.array([t["weight"] for t in tasks], dtype=float)
    attempts = np.array([t["attempt_count"] for t in tasks], dtype=float)
    reworks = np.array([t["rework_count"] for t in tasks], dtype=float)
    n = max(len(tasks), 1)

    completed = sum(1 for t in tasks if t["status"] == "COMPLETED")
    expired = sum(1 for t in tasks if t["status"] == "EXPIRED")
    violations = sum(1 for t in tasks if t["deadline_violated"])
    total_attempts = float(attempts.sum())

    busy = np.array([w["busy_time"] for w in workers], dtype=float)
    utilisation = float(np.mean(busy / horizon)) if len(busy) else 0.0

    # "total cost" = realised weighted service effort actually consumed
    total_cost = float(sum(t["weight"] * t["total_service_time"] for t in tasks))

    return {
        "total_weighted_completion_time": float(np.sum(weights * completions)),
        "maximum_completion_time": float(np.max(completions)) if len(completions) else 0.0,
        "total_cost": total_cost,
        "average_completion_time": float(np.mean(completions)) if len(completions) else 0.0,
        # share of tasks that had to be sent back at least once
        "rework_rate": float((reworks > 0).sum() / n),
        "reworks_per_task": float(reworks.mean()) if len(reworks) else 0.0,
        "failure_rate": float((total_attempts - completed) / max(total_attempts, 1.0)),
        "deadline_violations": float(violations),
        "deadline_violation_rate": violations / n,
        "average_attempts": float(attempts.mean()) if len(attempts) else 0.0,
        "worker_utilisation": utilisation,
        "completion_rate": completed / n,
        "expired_tasks": float(expired),
        "runtime_seconds": float(run.get("runtime_seconds", 0.0)),
    }
