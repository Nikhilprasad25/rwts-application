"""Probabilistic task-outcome step (spec section 18, proposal Phase 3).

Once a worker has taken a task on, the outcome is drawn from that worker's
hidden TRUE reliability. This is the piece the original CMS/TMS framework
assumes away.

ASSUMPTIONS (configurable, not part of the published methodology):

* success probability = ``true_reliability ** difficulty_exponent``
* actual service time = ``tau * (1 + Gamma-distributed overrun)``; the overrun
  mean scales with ``(1 - true_reliability)`` so unreliable workers are also
  slower, matching the delay component of the WRS
* a failed attempt still consumes ``partial_effort`` of the service time before
  the failure is discovered
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from app.models.task import Task
from app.models.worker import Worker


@dataclass
class OutcomeConfig:
    difficulty_exponent: float = 1.0
    delay_scale: float = 0.8            # mean overrun fraction at reliability 0
    delay_shape: float = 2.0            # Gamma shape of the overrun
    partial_effort: float = 1.0         # fraction of tau burned on a failed attempt
    max_attempts: int = 5               # after this the task is abandoned/expired
    rework_on_failure: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "OutcomeConfig":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: (int(v) if k == "max_attempts" else
                          (bool(v) if k == "rework_on_failure" else float(v)))
                      for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Outcome:
    success: bool
    service_time: float
    delay_score: float          # 1.0 = on time or better, -> 0 as it overruns


class OutcomeModel:
    def __init__(self, cfg: OutcomeConfig):
        self.cfg = cfg

    def draw(self, task: Task, worker: Worker, rng: np.random.Generator) -> Outcome:
        r = float(np.clip(worker.true_reliability, 1e-6, 1.0))
        p_success = r ** self.cfg.difficulty_exponent
        success = bool(rng.random() < p_success)

        overrun_mean = self.cfg.delay_scale * (1.0 - r)
        shape = max(self.cfg.delay_shape, 1e-3)
        scale = overrun_mean / shape if overrun_mean > 0 else 0.0
        overrun = float(rng.gamma(shape, scale)) if scale > 0 else 0.0

        service = task.expected_service_time * (1.0 + overrun)
        if not success:
            service *= self.cfg.partial_effort
        delay_score = float(np.clip(1.0 / (1.0 + overrun), 0.0, 1.0))
        return Outcome(success, max(service, 1e-9), delay_score)
