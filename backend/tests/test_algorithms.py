"""Scheduler behaviour and the knowledge separation the methodology requires."""
import pytest

from app.algorithms.base import (KNOWLEDGE_ESTIMATED, KNOWLEDGE_NETWORK,
                                 KNOWLEDGE_TRUE, WorkerView)
from app.algorithms.registry import ALGORITHMS, build, catalogue
from app.models.task import Task


def views(rels=(None, None)):
    return [WorkerView(f"W{i+1}", 0.01, 100.0, r) for i, r in enumerate(rels)]


def tasks(n=6):
    return [Task(f"T{i}", 0.0, 100.0 + 10 * i, 1.0 + i, 10_000.0) for i in range(n)]


def test_registry_declares_expected_knowledge_levels():
    k = {c["name"]: c["knowledge"] for c in catalogue()}
    assert k["LUCF"] == k["LRSTF"] == KNOWLEDGE_NETWORK
    assert k["RWTS-M"] == k["RWTS-ER"] == KNOWLEDGE_ESTIMATED
    assert k["Oracle"] == KNOWLEDGE_TRUE


@pytest.mark.parametrize("name", ["LUCF", "LRSTF"])
def test_baselines_never_read_reliability(name):
    sched = build(name)
    assert sched.uses_reliability is False
    plan = sched.plan(tasks(), views((None, None)))
    assert len(plan) == 6


@pytest.mark.parametrize("name", ["RWTS-M", "RWTS-ER", "Oracle"])
def test_reliability_aware_schedulers_refuse_blind_views(name):
    sched = build(name)
    with pytest.raises(RuntimeError):
        sched.plan(tasks(), views((None, None)))


def test_every_task_is_assigned_exactly_once():
    for name in ALGORITHMS:
        rels = (None, None) if name in ("LUCF", "LRSTF") else (0.9, 0.3)
        plan = build(name).plan(tasks(10), views(rels))
        assert len(plan) == 10
        assert set(plan) == {f"T{i}" for i in range(10)}


def test_rwts_prefers_the_more_reliable_worker():
    """Two identical workers apart from reliability: the dependable one gets
    the majority of the load under both RWTS variants."""
    for name in ("RWTS-M", "RWTS-ER"):
        plan = build(name).plan(tasks(20), views((0.95, 0.25)))
        share = sum(1 for w in plan.values() if w == "W1") / 20
        assert share > 0.6, f"{name} gave the reliable worker only {share:.0%}"


def test_baselines_split_identical_workers_evenly():
    plan = build("LUCF").plan(tasks(20), views((None, None)))
    share = sum(1 for w in plan.values() if w == "W1") / 20
    assert 0.35 <= share <= 0.65


def test_expected_rework_inflates_workload_by_one_over_wrs():
    sched = build("RWTS-ER")
    t = Task("T", 0.0, 100.0, 1.0, 1e9)
    v_good = WorkerView("A", 0.01, 100.0, 1.0)
    v_bad = WorkerView("B", 0.01, 100.0, 0.5)
    assert sched.effective_time(t, v_good) == pytest.approx(200.0)
    assert sched.effective_time(t, v_bad) == pytest.approx(400.0)


def test_multiplicative_gamma_controls_the_penalty():
    t = Task("T", 0.0, 100.0, 2.0, 1e9)
    v = WorkerView("A", 0.01, 100.0, 0.5)
    soft = build("RWTS-M", {"gamma": 0.0}).score(t, v, 0.0)
    hard = build("RWTS-M", {"gamma": 2.0}).score(t, v, 0.0)
    assert hard > soft


def test_ordering_differs_between_cms_and_tms():
    ts = [Task("A", 0, 10, 1, 1e9), Task("B", 0, 100, 1, 1e9)]
    assert [t.task_id for t in build("LUCF").order(ts)] == ["A", "B"]   # highest w/tau
    assert [t.task_id for t in build("LRSTF").order(ts)] == ["B", "A"]  # longest first


def test_complexity_stays_linear_in_tasks_times_workers():
    """A doubling of tasks roughly doubles the work: the greedy driver is O(nm)."""
    sched = build("LUCF")
    calls = {"n": 0}
    original = sched.score

    def counting(task, w, load):
        calls["n"] += 1
        return original(task, w, load)

    sched.score = counting
    sched.plan(tasks(50), views((None, None, None, None)))
    assert calls["n"] == 50 * 4
