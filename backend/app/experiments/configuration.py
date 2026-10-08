"""Experiment configuration objects (spec section 13)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from app.algorithms.registry import ALGORITHMS, DEFAULT_SELECTION
from app.reliability.distributions import ReliabilityConfig
from app.reliability.wrs import WRSConfig
from app.simulation.engine import SimulationConfig
from app.simulation.outcome_model import OutcomeConfig
from app.simulation.task_model import TaskConfig


@dataclass
class WorkerSelection:
    mode: str = "all"                 # all | top_n | explicit
    count: int = 20                   # used when mode == "top_n"
    worker_ids: list[str] = field(default_factory=list)
    min_contacts: int = 2             # drop nodes seen almost never

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "WorkerSelection":
        d = dict(d or {})
        return cls(mode=str(d.get("mode", "all")),
                   count=int(d.get("count", 20)),
                   worker_ids=[str(x) for x in d.get("worker_ids", [])],
                   min_contacts=int(d.get("min_contacts", 2)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SensitivityConfig:
    """Sweeps executed by the experiment runner (spec section 25)."""
    enabled: bool = False
    reliability_diversity: list[str] = field(default_factory=list)      # low/medium/high
    reliability_distributions: list[str] = field(default_factory=list)
    task_worker_ratios: list[float] = field(default_factory=list)
    wrs_noise_levels: list[float] = field(default_factory=list)
    cold_start_history: list[int] = field(default_factory=list)
    repetitions: int | None = None      # override repetitions inside sweeps

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SensitivityConfig":
        d = dict(d or {})
        return cls(
            enabled=bool(d.get("enabled", False)),
            reliability_diversity=[str(x) for x in d.get("reliability_diversity", [])],
            reliability_distributions=[str(x) for x in d.get("reliability_distributions", [])],
            task_worker_ratios=[float(x) for x in d.get("task_worker_ratios", [])],
            wrs_noise_levels=[float(x) for x in d.get("wrs_noise_levels", [])],
            cold_start_history=[int(x) for x in d.get("cold_start_history", [])],
            repetitions=(int(d["repetitions"]) if d.get("repetitions") else None),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_SENSITIVITY = {
    "reliability_diversity": ["low", "medium", "high"],
    "reliability_distributions": ["uniform", "normal", "skewed", "minority_unreliable"],
    "task_worker_ratios": [0.5, 1, 2, 5, 10],
    "wrs_noise_levels": [0.0, 0.05, 0.10, 0.20, 0.30],
    "cold_start_history": [0, 1, 5, 10, 25, 50, 100],
}


@dataclass
class ExperimentConfig:
    dataset_id: str
    name: str = "Experiment"
    description: str = ""
    algorithms: list[str] = field(default_factory=lambda: list(DEFAULT_SELECTION))
    algorithm_params: dict[str, dict[str, Any]] = field(default_factory=dict)
    repetitions: int = 30
    confidence: float = 0.95
    workers: WorkerSelection = field(default_factory=WorkerSelection)
    tasks: TaskConfig = field(default_factory=TaskConfig)
    reliability: ReliabilityConfig = field(default_factory=ReliabilityConfig)
    wrs: WRSConfig = field(default_factory=WRSConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    outcome: OutcomeConfig = field(default_factory=OutcomeConfig)
    sensitivity: SensitivityConfig = field(default_factory=SensitivityConfig)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperimentConfig":
        if not d.get("dataset_id"):
            raise ValueError("dataset_id is required")
        algos = [a for a in d.get("algorithms") or DEFAULT_SELECTION]
        unknown = [a for a in algos if a not in ALGORITHMS]
        if unknown:
            raise ValueError(f"Unknown algorithms: {unknown}")
        return cls(
            dataset_id=str(d["dataset_id"]),
            name=str(d.get("name") or "Experiment"),
            description=str(d.get("description") or ""),
            algorithms=algos,
            algorithm_params=dict(d.get("algorithm_params") or {}),
            repetitions=max(int(d.get("repetitions", 30)), 1),
            confidence=float(d.get("confidence", 0.95)),
            workers=WorkerSelection.from_dict(d.get("workers")),
            tasks=TaskConfig.from_dict(d.get("tasks")),
            reliability=ReliabilityConfig.from_dict(d.get("reliability")),
            wrs=WRSConfig.from_dict(d.get("wrs")),
            simulation=SimulationConfig.from_dict(d.get("simulation")),
            outcome=OutcomeConfig.from_dict(d.get("outcome")),
            sensitivity=SensitivityConfig.from_dict(d.get("sensitivity")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "algorithms": self.algorithms,
            "algorithm_params": self.algorithm_params,
            "repetitions": self.repetitions,
            "confidence": self.confidence,
            "workers": self.workers.to_dict(),
            "tasks": self.tasks.to_dict(),
            "reliability": self.reliability.to_dict(),
            "wrs": self.wrs.to_dict(),
            "simulation": self.simulation.to_dict(),
            "outcome": self.outcome.to_dict(),
            "sensitivity": self.sensitivity.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)
