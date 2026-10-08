"""Task generation (spec sections 13 and 17)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal

import numpy as np

from app.models.task import Task

ServiceDist = Literal["uniform", "exponential", "fixed"]


@dataclass
class TaskConfig:
    n_tasks: int = 100
    weight_min: float = 1.0
    weight_max: float = 10.0
    service_distribution: ServiceDist = "uniform"
    service_min: float = 300.0            # dataset time units (seconds for Haggle)
    service_max: float = 1800.0
    service_mean: float = 900.0
    arrival_window: float = 0.0           # 0 => all tasks exist at t = 0 (offline)
    deadline_factor: float = 100.0          # deadline = creation + factor * tau
    priority_levels: int = 3

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "TaskConfig":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        out = {}
        for k, v in d.items():
            if k not in known:
                continue
            out[k] = v if k == "service_distribution" else (
                int(v) if k in {"n_tasks", "priority_levels"} else float(v))
        return cls(**out)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_tasks(cfg: TaskConfig, rng: np.random.Generator) -> list[Task]:
    n = int(cfg.n_tasks)
    weights = rng.uniform(cfg.weight_min, cfg.weight_max, n)
    if cfg.service_distribution == "uniform":
        taus = rng.uniform(cfg.service_min, cfg.service_max, n)
    elif cfg.service_distribution == "exponential":
        taus = np.clip(rng.exponential(cfg.service_mean, n), cfg.service_min, cfg.service_max)
    else:
        taus = np.full(n, cfg.service_mean)
    arrivals = (rng.uniform(0, cfg.arrival_window, n) if cfg.arrival_window > 0
                else np.zeros(n))
    priorities = rng.integers(1, max(cfg.priority_levels, 1) + 1, n)

    tasks: list[Task] = []
    for i in range(n):
        tau = float(max(taus[i], 1e-6))
        created = float(arrivals[i])
        tasks.append(Task(
            task_id=f"T{i + 1:04d}",
            creation_time=created,
            expected_service_time=tau,
            weight=float(weights[i]),
            deadline=created + cfg.deadline_factor * tau,
            priority=int(priorities[i]),
        ))
    return tasks
