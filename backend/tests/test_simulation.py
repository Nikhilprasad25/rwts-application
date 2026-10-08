"""Scenario construction, engine lifecycle, fairness and metrics."""
import numpy as np
import pytest

from app.algorithms.registry import build
from app.data.dataset_manager import load_processed
from app.data.transformer import compute_contact_parameters
from app.evaluation.metrics import compute
from app.evaluation.statistics import summarise
from app.models.task import TaskStatus
from app.reliability.distributions import ReliabilityConfig
from app.reliability.wrs import WRSConfig
from app.simulation.engine import SimulationConfig, SimulationEngine, build_scenario
from app.simulation.outcome_model import OutcomeConfig, OutcomeModel
from app.simulation.task_model import TaskConfig, generate_tasks


@pytest.fixture(scope="module")
def scenario_parts(prepared_dataset):
    records, meta = load_processed(prepared_dataset)
    params = compute_contact_parameters(records)
    ids = [w for w, p in params.items() if p.contact_count >= 20][:8]
    return records, {w: params[w].lam for w in ids}, ids


def make(scenario_parts, **over):
    records, lambdas, ids = scenario_parts
    sim = SimulationConfig(seed=99, **over)
    return build_scenario(records, lambdas, ids, TaskConfig(n_tasks=30),
                          ReliabilityConfig(mean=0.7, std=0.2), WRSConfig(),
                          sim, repetition=0), sim


def test_task_generation_respects_configuration():
    cfg = TaskConfig(n_tasks=25, weight_min=2, weight_max=4, service_min=10,
                     service_max=20, deadline_factor=3)
    ts = generate_tasks(cfg, np.random.default_rng(0))
    assert len(ts) == 25
    assert all(2 <= t.weight <= 4 for t in ts)
    assert all(10 <= t.expected_service_time <= 20 for t in ts)
    assert all(t.deadline == pytest.approx(t.creation_time + 3 * t.expected_service_time)
               for t in ts)


def test_scenario_is_deterministic_for_a_seed(scenario_parts):
    a, _ = make(scenario_parts)
    b, _ = make(scenario_parts)
    assert [w.true_reliability for w in a.workers] == [w.true_reliability for w in b.workers]
    assert [t.expected_service_time for t in a.tasks] == [t.expected_service_time for t in b.tasks]
    assert len(a.contact_events) == len(b.contact_events)


def test_requester_is_excluded_from_the_worker_pool(scenario_parts):
    sc, _ = make(scenario_parts)
    assert sc.requester_id is not None
    assert sc.requester_id not in [w.worker_id for w in sc.workers]


def test_contact_events_come_from_the_real_trace(scenario_parts):
    sc, _ = make(scenario_parts)
    assert sc.contact_events, "trace mode produced no hand-over opportunities"
    assert all(e.time <= sc.horizon for e in sc.contact_events)
    assert all(e.worker_id in {w.worker_id for w in sc.workers} for e in sc.contact_events)


def test_exponential_mode_generates_events(scenario_parts):
    sc, _ = make(scenario_parts, contact_mode="exponential")
    assert len(sc.contact_events) > 0


def test_every_task_reaches_a_terminal_state(scenario_parts):
    sc, sim = make(scenario_parts)
    run = SimulationEngine(sc, build("LUCF"), WRSConfig(), OutcomeConfig(), sim).run()
    terminal = {TaskStatus.COMPLETED.value, TaskStatus.EXPIRED.value}
    assert {t["status"] for t in run["tasks"]} <= terminal
    assert all(t["completion_time"] is not None for t in run["tasks"])


def test_attempts_never_exceed_the_configured_maximum(scenario_parts):
    sc, sim = make(scenario_parts)
    out = OutcomeConfig(max_attempts=3)
    run = SimulationEngine(sc, build("LUCF"), WRSConfig(), out, sim).run()
    assert max(t["attempt_count"] for t in run["tasks"]) <= 3


def test_rework_can_be_switched_off(scenario_parts):
    sc, sim = make(scenario_parts)
    out = OutcomeConfig(rework_on_failure=False)
    run = SimulationEngine(sc, build("LUCF"), WRSConfig(), out, sim).run()
    assert all(t["rework_count"] == 0 for t in run["tasks"])


def test_baselines_never_see_a_reliability_value(scenario_parts):
    sc, sim = make(scenario_parts)
    eng = SimulationEngine(sc, build("LUCF"), WRSConfig(), OutcomeConfig(), sim)
    assert all(v.reliability is None for v in eng._views())
    eng2 = SimulationEngine(sc, build("RWTS-ER"), WRSConfig(), OutcomeConfig(), sim)
    assert all(v.reliability is not None for v in eng2._views())
    eng3 = SimulationEngine(sc, build("Oracle"), WRSConfig(), OutcomeConfig(), sim)
    truths = {w.worker_id: w.true_reliability for w in sc.workers}
    assert all(v.reliability == truths[v.worker_id] for v in eng3._views())


def test_all_algorithms_share_one_scenario(scenario_parts):
    """Fairness: the workers, tasks and events handed to each algorithm are equal."""
    sc, sim = make(scenario_parts)
    seen = []
    for name in ("LUCF", "RWTS-ER", "Oracle"):
        eng = SimulationEngine(sc, build(name), WRSConfig(), OutcomeConfig(), sim)
        seen.append(([w.true_reliability for w in eng.workers],
                     [t.expected_service_time for t in eng.tasks]))
    assert seen[0] == seen[1] == seen[2]


def test_repeated_run_is_reproducible(scenario_parts):
    sc, sim = make(scenario_parts)
    a = compute(SimulationEngine(sc, build("RWTS-ER"), WRSConfig(), OutcomeConfig(), sim).run())
    b = compute(SimulationEngine(sc, build("RWTS-ER"), WRSConfig(), OutcomeConfig(), sim).run())
    assert a["total_weighted_completion_time"] == pytest.approx(b["total_weighted_completion_time"])


def test_outcome_model_success_tracks_true_reliability():
    from app.models.task import Task
    from app.models.worker import Worker
    model = OutcomeModel(OutcomeConfig())
    t = Task("T", 0, 100, 1, 1e9)
    rng = np.random.default_rng(0)
    good = sum(model.draw(t, Worker("A", .1, true_reliability=0.9), rng).success
               for _ in range(2000)) / 2000
    bad = sum(model.draw(t, Worker("B", .1, true_reliability=0.3), rng).success
              for _ in range(2000)) / 2000
    assert good == pytest.approx(0.9, abs=0.03)
    assert bad == pytest.approx(0.3, abs=0.03)


def test_metrics_are_internally_consistent(scenario_parts):
    sc, sim = make(scenario_parts)
    run = SimulationEngine(sc, build("LUCF"), WRSConfig(), OutcomeConfig(), sim).run()
    m = compute(run)
    n = len(run["tasks"])
    completions = [t["completion_time"] for t in run["tasks"]]
    weights = [t["weight"] for t in run["tasks"]]
    assert m["maximum_completion_time"] == pytest.approx(max(completions))
    assert m["total_weighted_completion_time"] == pytest.approx(
        sum(w * c for w, c in zip(weights, completions)))
    assert m["average_completion_time"] == pytest.approx(sum(completions) / n)
    assert 0 <= m["completion_rate"] <= 1
    assert 0 <= m["rework_rate"] <= 1


def test_summarise_reports_a_confidence_interval():
    s = summarise([1, 2, 3, 4, 5])
    assert s["mean"] == pytest.approx(3.0)
    assert s["ci_low"] < 3.0 < s["ci_high"]
    assert s["n"] == 5
