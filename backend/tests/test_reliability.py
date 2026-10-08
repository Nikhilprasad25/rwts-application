"""WRS estimator, Bayesian cold start, synthetic reliability distributions."""
import numpy as np
import pytest

from app.models.worker import Worker
from app.reliability.bayesian import BayesianPrior, posterior_mean
from app.reliability.distributions import ReliabilityConfig, generate_true_reliability
from app.reliability.wrs import WRSConfig, WRSEstimator


def test_weights_are_normalised_to_one():
    cfg = WRSConfig(completion_weight=2, delay_weight=1, rework_weight=1)
    assert cfg.completion_weight + cfg.delay_weight + cfg.rework_weight == pytest.approx(1.0)
    assert cfg.completion_weight == pytest.approx(0.5)


def test_cold_start_worker_is_neutral():
    est = WRSEstimator(WRSConfig(alpha=2, beta=2))
    w = Worker("W1", 0.01, true_reliability=0.95)
    assert est.estimate(w).wrs == pytest.approx(0.5)
    w2 = Worker("W2", 0.01, true_reliability=0.05)
    assert est.estimate(w2).wrs == pytest.approx(0.5)


def test_asymmetric_prior_shifts_the_neutral_point():
    est = WRSEstimator(WRSConfig(alpha=8, beta=2))
    assert est.estimate(Worker("W", 0.01)).wrs == pytest.approx(0.8)


def test_posterior_mean_matches_beta_binomial():
    prior = BayesianPrior(2, 3)
    assert posterior_mean(4, 10, prior) == pytest.approx((2 + 4) / (2 + 3 + 10))


@pytest.mark.parametrize("truth", [0.15, 0.45, 0.9])
def test_wrs_converges_toward_truth_with_history(truth):
    rng = np.random.default_rng(7)
    est = WRSEstimator(WRSConfig(), rng)
    w = Worker("W", 0.01, true_reliability=truth)
    est.seed_cold_start(w, 5, np.random.default_rng(1))
    short = abs(w.wrs - truth)
    w2 = Worker("W", 0.01, true_reliability=truth)
    est.seed_cold_start(w2, 2000, np.random.default_rng(1))
    assert abs(w2.wrs - truth) < 0.12
    assert abs(w2.wrs - truth) <= short + 0.05


def test_noise_perturbs_only_the_reported_score():
    rng = np.random.default_rng(3)
    est = WRSEstimator(WRSConfig(noise_level=0.2), rng)
    w = Worker("W", 0.01, true_reliability=0.8)
    est.seed_cold_start(w, 200, np.random.default_rng(2))
    b = est.estimate(w)
    assert 0.0 <= b.wrs <= 1.0
    assert b.wrs_true_estimate != b.wrs or est.cfg.noise_level == 0


@pytest.mark.parametrize("dist", ["uniform", "normal", "skewed", "beta",
                                  "minority_unreliable", "fixed"])
def test_distributions_respect_bounds(dist):
    cfg = ReliabilityConfig(distribution=dist, mean=0.7, std=0.15,
                            minimum=0.1, maximum=0.95)
    vals = generate_true_reliability(500, cfg, np.random.default_rng(0))
    assert len(vals) == 500
    assert vals.min() >= 0.1 - 1e-9 and vals.max() <= 0.95 + 1e-9


def test_minority_unreliable_creates_two_groups():
    cfg = ReliabilityConfig(distribution="minority_unreliable", std=0.06,
                            unreliable_fraction=0.25, unreliable_mean=0.3,
                            reliable_mean=0.9, minimum=0.0, maximum=1.0)
    vals = generate_true_reliability(400, cfg, np.random.default_rng(1))
    assert 0.18 < (vals < 0.6).mean() < 0.32
