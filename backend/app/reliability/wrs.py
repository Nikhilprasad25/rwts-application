"""Worker Reliability Score estimator (spec sections 15-16).

    WRS_j = w_c * completion_component
          + w_d * delay_component
          + w_r * rework_component            in [0, 1]

Every component is Bayesian-shrunk toward the prior mean so a cold-start worker
starts neutral (proposal, Phase 1). The estimate is the ONLY reliability signal
that RWTS may read; ``Worker.true_reliability`` stays with the simulator.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np

from app.models.worker import Worker
from app.reliability.bayesian import BayesianPrior, posterior_mean, shrunk_mean


@dataclass
class WRSConfig:
    completion_weight: float = 0.5
    delay_weight: float = 0.2
    rework_weight: float = 0.3
    alpha: float = 2.0
    beta: float = 2.0
    noise_level: float = 0.0        # additive N(0, noise_level) on the reported WRS
    floor: float = 0.05             # WRS never reported below this (avoids /0)

    def __post_init__(self) -> None:
        total = self.completion_weight + self.delay_weight + self.rework_weight
        if total <= 0:
            raise ValueError("WRS weights must sum to a positive number.")
        # spec 15: "Ensure the weights sum to 1"
        self.completion_weight /= total
        self.delay_weight /= total
        self.rework_weight /= total

    @property
    def prior(self) -> BayesianPrior:
        return BayesianPrior(self.alpha, self.beta)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "WRSConfig":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: float(v) for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WRSBreakdown:
    worker_id: str
    completion_component: float
    delay_component: float
    rework_component: float
    wrs_true_estimate: float        # noise-free estimate
    wrs: float                      # what the scheduler actually sees
    observations: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WRSEstimator:
    def __init__(self, config: WRSConfig, rng: np.random.Generator | None = None):
        self.cfg = config
        self.rng = rng or np.random.default_rng(0)

    # ------------------------------------------------------------------ #
    def components(self, w: Worker) -> tuple[float, float, float]:
        prior = self.cfg.prior
        completion = posterior_mean(w.observed_successes, w.observed_attempts, prior)
        delay = shrunk_mean(float(sum(w.delay_scores)), len(w.delay_scores), prior)
        rework_free = w.observed_attempts - w.observed_reworks
        rework = posterior_mean(max(rework_free, 0.0), w.observed_attempts, prior)
        return completion, delay, rework

    def estimate(self, w: Worker) -> WRSBreakdown:
        c, d, r = self.components(w)
        score = (self.cfg.completion_weight * c
                 + self.cfg.delay_weight * d
                 + self.cfg.rework_weight * r)
        score = float(np.clip(score, 0.0, 1.0))
        reported = score
        if self.cfg.noise_level > 0:
            reported = float(np.clip(score + self.rng.normal(0.0, self.cfg.noise_level),
                                     0.0, 1.0))
        reported = max(reported, self.cfg.floor)
        return WRSBreakdown(w.worker_id, c, d, r, score, reported, w.observed_attempts)

    def update(self, w: Worker, record: bool = True) -> float:
        """Recompute and store ``worker.wrs``; optionally append to its history."""
        b = self.estimate(w)
        w.wrs = b.wrs
        if record:
            w.wrs_history.append({
                "observations": float(w.observed_attempts),
                "wrs": b.wrs,
                "wrs_noise_free": b.wrs_true_estimate,
                "true_reliability": w.true_reliability,
            })
        return w.wrs

    # ------------------------------------------------------------------ #
    def observe(self, w: Worker, success: bool, reworked: bool,
                delay_score: float | None = None) -> None:
        """Fold one observed task outcome into the worker's visible history."""
        w.observed_attempts += 1
        if success:
            w.observed_successes += 1
        if reworked:
            w.observed_reworks += 1
        if delay_score is not None:
            w.delay_scores.append(float(np.clip(delay_score, 0.0, 1.0)))
        self.update(w)

    # ------------------------------------------------------------------ #
    def seed_cold_start(self, w: Worker, n_history: int,
                        rng: np.random.Generator) -> None:
        """Give a worker ``n_history`` synthetic prior observations.

        Used by the cold-start sensitivity analysis (spec 25). The synthetic
        history is drawn from the worker's hidden true reliability, so with
        ``n_history = 0`` the scheduler sees only the neutral prior.
        """
        for _ in range(max(int(n_history), 0)):
            success = bool(rng.random() < w.true_reliability)
            reworked = not success
            delay_score = float(np.clip(rng.beta(
                max(w.true_reliability * 6, 0.2),
                max((1 - w.true_reliability) * 6, 0.2)), 0.0, 1.0))
            w.observed_attempts += 1
            if success:
                w.observed_successes += 1
            if reworked:
                w.observed_reworks += 1
            w.delay_scores.append(delay_score)
        self.update(w)
