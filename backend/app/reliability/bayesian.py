"""Bayesian shrinkage used by the WRS estimator (spec section 16).

A worker with no history must not look perfectly reliable nor perfectly
unreliable: every component of the score is shrunk toward the prior mean
``alpha / (alpha + beta)`` with prior strength ``alpha + beta``.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class BayesianPrior:
    alpha: float = 2.0
    beta: float = 2.0

    @property
    def prior_mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def prior_strength(self) -> float:
        return self.alpha + self.beta

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "BayesianPrior":
        d = dict(d or {})
        return cls(alpha=float(d.get("alpha", 2.0)), beta=float(d.get("beta", 2.0)))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["prior_mean"] = self.prior_mean
        return d


def posterior_mean(successes: float, trials: float, prior: BayesianPrior) -> float:
    """Beta-Binomial posterior mean of a success probability."""
    return (prior.alpha + successes) / (prior.alpha + prior.beta + trials)


def shrunk_mean(observed_sum: float, n: float, prior: BayesianPrior) -> float:
    """Shrink an arbitrary [0,1] score mean toward the prior mean."""
    return ((prior.prior_mean * prior.prior_strength + observed_sum)
            / (prior.prior_strength + n))
