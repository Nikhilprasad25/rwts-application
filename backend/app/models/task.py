"""Task model and lifecycle (spec section 17)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_FOR_CONTACT = "WAITING_FOR_CONTACT"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REWORK = "REWORK"
    EXPIRED = "EXPIRED"


@dataclass
class Task:
    task_id: str
    creation_time: float
    expected_service_time: float        # tau_i
    weight: float                       # w_i
    deadline: float
    priority: int = 1

    status: TaskStatus = TaskStatus.PENDING
    attempt_count: int = 0
    rework_count: int = 0
    assigned_worker: str | None = None

    completion_time: float | None = None
    first_assigned_time: float | None = None
    total_service_time: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)

    # ---- convenience -----------------------------------------------------
    @property
    def unit_cost(self) -> float:
        """w_i / tau_i — the LUCF ordering key."""
        return self.weight / self.expected_service_time if self.expected_service_time else float("inf")

    @property
    def deadline_violated(self) -> bool:
        return self.completion_time is not None and self.completion_time > self.deadline

    def log(self, time: float, event: str, **extra: Any) -> None:
        self.history.append({"time": time, "event": event, **extra})

    def reset_for_repetition(self) -> None:
        self.status = TaskStatus.PENDING
        self.attempt_count = 0
        self.rework_count = 0
        self.assigned_worker = None
        self.completion_time = None
        self.first_assigned_time = None
        self.total_service_time = 0.0
        self.history = []

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["deadline_violated"] = self.deadline_violated
        return d
