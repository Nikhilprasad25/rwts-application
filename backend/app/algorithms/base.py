"""Scheduler interface and the shared greedy assignment core.

Knowledge separation (spec section 42) is enforced structurally: the simulation
engine builds a :class:`WorkerView` list per scheduler and a scheduler can only
ever read what its ``knowledge`` level allows.

* ``KNOWLEDGE_NETWORK``   -> LUCF, LRSTF          (reliability is ``None``)
* ``KNOWLEDGE_ESTIMATED`` -> RWTS-M, RWTS-ER      (reliability is the WRS)
* ``KNOWLEDGE_TRUE``      -> Oracle               (reliability is the hidden truth)

All schedulers below are greedy list-scheduling algorithms with an O(n*m) bound,
matching the complexity of the original LUCF/LRSTF (proposal, Phase 2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from app.models.task import Task

KNOWLEDGE_NETWORK = "network_only"
KNOWLEDGE_ESTIMATED = "network_plus_wrs"
KNOWLEDGE_TRUE = "network_plus_true_reliability"

Objective = Literal["cms", "tms"]


@dataclass(slots=True)
class WorkerView:
    """The only worker information a scheduler is allowed to read."""
    worker_id: str
    lam: float
    mean_meeting_delay: float
    reliability: float | None = None      # None for reliability-agnostic schedulers
    load: float = 0.0                     # projected available time A_j


class Scheduler:
    name: str = "base"
    label: str = "Base"
    knowledge: str = KNOWLEDGE_NETWORK
    objective: Objective = "cms"
    uses_reliability: bool = False

    def __init__(self, objective: Objective | None = None, **params: float) -> None:
        if objective:
            self.objective = objective
        self.params = params

    # -- offline plan ---------------------------------------------------- #
    def plan(self, tasks: list[Task], workers: list[WorkerView]) -> dict[str, str]:
        raise NotImplementedError

    # -- online re-assignment of a failed/reworked task ------------------ #
    def reassign(self, task: Task, workers: list[WorkerView], now: float) -> str:
        best, best_score = None, float("inf")
        for w in workers:
            score = self.score(task, w, max(w.load, now))
            if score < best_score:
                best, best_score = w, score
        assert best is not None
        best.load = max(best.load, now) + self.effective_time(task, best)
        return best.worker_id

    # -- pieces the concrete algorithms override ------------------------- #
    def effective_time(self, task: Task, w: WorkerView) -> float:
        """p_ij: expected time worker j occupies for task i, meeting delay included."""
        return w.mean_meeting_delay + task.expected_service_time

    def score(self, task: Task, w: WorkerView, load: float) -> float:
        completion = load + self.effective_time(task, w)
        if self.objective == "tms":
            return completion
        return task.weight * completion

    def order(self, tasks: Iterable[Task]) -> list[Task]:
        if self.objective == "tms":
            # LRSTF-style: longest expected service time first
            return sorted(tasks, key=lambda t: (-t.expected_service_time, t.task_id))
        # LUCF-style: least unit cost first == highest w/tau handled first
        return sorted(tasks, key=lambda t: (-t.unit_cost, t.task_id))

    # -- shared greedy driver -------------------------------------------- #
    def greedy_plan(self, tasks: list[Task], workers: list[WorkerView]) -> dict[str, str]:
        for w in workers:
            w.load = 0.0
        assignment: dict[str, str] = {}
        for task in self.order(tasks):
            best, best_score = None, float("inf")
            for w in workers:
                s = self.score(task, w, w.load)
                if s < best_score:
                    best, best_score = w, s
            assert best is not None
            best.load += self.effective_time(task, best)
            assignment[task.task_id] = best.worker_id
        return assignment

    plan = greedy_plan       # default implementation

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label,
            "knowledge": self.knowledge,
            "objective": self.objective,
            "uses_reliability": self.uses_reliability,
            "params": self.params,
        }
