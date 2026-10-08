"""Synthetic worker reliability generation (spec section 14).

The uploaded contact trace is REAL observed data. Worker dependability is not
recorded by any public MSN dataset, so true reliability is generated here and
is clearly labelled SYNTHETIC throughout the application.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Literal

import numpy as np

DistributionName = Literal["uniform", "normal", "skewed", "minority_unreliable", "beta", "fixed"]

DISTRIBUTIONS: dict[str, str] = {
    "uniform": "Uniform over [minimum, maximum] — maximal diversity, no central mass.",
    "normal": "Truncated normal with the configured mean and standard deviation.",
    "skewed": "Beta distribution skewed toward high reliability (most workers dependable).",
    "minority_unreliable": "A configurable minority of clearly unreliable workers "
                           "inside an otherwise dependable population.",
    "beta": "Beta(a, b) parameterised directly by the configured mean and std.",
    "fixed": "Every worker receives exactly the configured mean reliability.",
}


@dataclass
class ReliabilityConfig:
    distribution: DistributionName = "normal"
    mean: float = 0.75
    std: float = 0.15
    minimum: float = 0.05
    maximum: float = 1.0
    unreliable_fraction: float = 0.2       # used by "minority_unreliable"
    unreliable_mean: float = 0.35
    reliable_mean: float = 0.9

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "ReliabilityConfig":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _beta_from_moments(mean: float, std: float) -> tuple[float, float]:
    mean = min(max(mean, 1e-3), 1 - 1e-3)
    var = max(min(std ** 2, mean * (1 - mean) * 0.999), 1e-6)
    common = mean * (1 - mean) / var - 1
    return max(mean * common, 1e-3), max((1 - mean) * common, 1e-3)


def generate_true_reliability(n: int, cfg: ReliabilityConfig,
                              rng: np.random.Generator) -> np.ndarray:
    """Draw ``n`` hidden ground-truth reliability values in [minimum, maximum]."""
    lo, hi = cfg.minimum, cfg.maximum
    if cfg.distribution == "uniform":
        vals = rng.uniform(lo, hi, n)
    elif cfg.distribution == "normal":
        vals = rng.normal(cfg.mean, cfg.std, n)
    elif cfg.distribution == "skewed":
        a, b = _beta_from_moments(max(cfg.mean, 0.6), max(cfg.std, 0.05))
        vals = rng.beta(a, b, n)
    elif cfg.distribution == "beta":
        a, b = _beta_from_moments(cfg.mean, cfg.std)
        vals = rng.beta(a, b, n)
    elif cfg.distribution == "minority_unreliable":
        n_bad = int(round(cfg.unreliable_fraction * n))
        idx = rng.permutation(n)
        vals = np.empty(n)
        vals[idx[:n_bad]] = rng.normal(cfg.unreliable_mean, cfg.std / 2, n_bad)
        vals[idx[n_bad:]] = rng.normal(cfg.reliable_mean, cfg.std / 2, n - n_bad)
    elif cfg.distribution == "fixed":
        vals = np.full(n, cfg.mean)
    else:                                                     # pragma: no cover
        raise ValueError(f"Unknown reliability distribution '{cfg.distribution}'")
    return np.clip(vals, lo, hi)


def diversity_preset(level: str) -> dict[str, float]:
    """Reliability-diversity presets used by the sensitivity runner (spec 25)."""
    return {
        "low": {"std": 0.05},
        "medium": {"std": 0.15},
        "high": {"std": 0.30},
    }[level]
