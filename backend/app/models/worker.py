"""Worker model.

Three strictly separated information layers (spec section 42):

* ``lam`` / contact statistics  -> observed, comes from the uploaded dataset
* ``true_reliability``          -> synthetic ground truth, simulator only
* ``observed_*`` counters / WRS -> scheduler-visible estimate
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Worker:
    worker_id: str
    lam: float                                  # observed contact rate
    contact_count: int = 0
    mean_inter_contact_time: float = 0.0

    # --- SYNTHETIC GROUND TRUTH: never visible to LUCF/LRSTF/RWTS ---------
    true_reliability: float = 1.0

    # --- observable history used by the WRS estimator ---------------------
    observed_attempts: int = 0
    observed_successes: int = 0
    observed_reworks: int = 0
    delay_scores: list[float] = field(default_factory=list)

    # --- realised simulation counters ------------------------------------
    completed: int = 0
    failed: int = 0
    reworked: int = 0
    busy_time: float = 0.0

    wrs: float = 0.5
    wrs_history: list[dict[str, float]] = field(default_factory=list)

    @property
    def mean_meeting_delay(self) -> float:
        """Expected wait until the next requester/worker encounter, 1/lambda."""
        return 1.0 / self.lam if self.lam > 0 else float("inf")

    def public_view(self) -> dict[str, Any]:
        """Everything a *reliability-aware but non-oracle* scheduler may see."""
        return {
            "worker_id": self.worker_id,
            "lam": self.lam,
            "mean_meeting_delay": self.mean_meeting_delay,
            "wrs": self.wrs,
            "observed_attempts": self.observed_attempts,
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("delay_scores", None)
        d["mean_meeting_delay"] = self.mean_meeting_delay
        d["estimation_error"] = self.true_reliability - self.wrs
        return d
