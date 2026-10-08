"""RWTS — Reliability-Weighted Task Scheduling (spec section 20).

Two independent variants, both taking the *estimated* WRS only.

RWTS-Multiplicative
    The proposal's reliability-adjusted unit cost ``(w_i / tau_i) * g(WRS_j)``.
    Implemented as a multiplicative penalty on the placement score:

        score_ij = w_i * (A_j + 1/lambda_j + tau_i) / g(WRS_j)

    with ``g(x) = x ** gamma`` (``gamma`` configurable, default 1.0).  A worker
    with low WRS therefore has to be much cheaper on time before it wins a
    high-unit-cost task.  ASSUMPTION: the proposal states the adjusted unit cost
    but not the exact placement rule; dividing the weighted completion cost by
    g(WRS) is the direct translation and is documented as an assumption.

RWTS-Expected-Rework
    Redefines expected workload to include the expected extra attempts an
    unreliable worker causes:

        p_ij = (1/lambda_j + tau_i) / WRS_j

    which is the expected total occupancy under geometric retries with success
    probability WRS_j.
"""
from __future__ import annotations

from app.algorithms.base import KNOWLEDGE_ESTIMATED, Scheduler, WorkerView
from app.models.task import Task

MIN_RELIABILITY = 1e-3


def _rel(w: WorkerView) -> float:
    if w.reliability is None:               # pragma: no cover - guarded by engine
        raise RuntimeError(
            "A reliability-aware scheduler was given a reliability-free worker view.")
    return max(float(w.reliability), MIN_RELIABILITY)


class RWTSMultiplicative(Scheduler):
    """RWTS with the reliability-adjusted unit cost (w/tau) x g(WRS)."""

    name = "RWTS-M"
    label = "RWTS Multiplicative"
    knowledge = KNOWLEDGE_ESTIMATED
    objective = "cms"
    uses_reliability = True

    def __init__(self, objective=None, gamma: float = 1.0, **params):
        super().__init__(objective, gamma=gamma, **params)
        self.gamma = float(gamma)

    def g(self, reliability: float) -> float:
        return max(reliability ** self.gamma, MIN_RELIABILITY)

    def score(self, task: Task, w: WorkerView, load: float) -> float:
        completion = load + self.effective_time(task, w)
        base = completion if self.objective == "tms" else task.weight * completion
        return base / self.g(_rel(w))


class RWTSExpectedRework(Scheduler):
    """RWTS with expected-rework workload tau/WRS."""

    name = "RWTS-ER"
    label = "RWTS Expected-Rework"
    knowledge = KNOWLEDGE_ESTIMATED
    objective = "cms"
    uses_reliability = True

    def effective_time(self, task: Task, w: WorkerView) -> float:
        return (w.mean_meeting_delay + task.expected_service_time) / _rel(w)
