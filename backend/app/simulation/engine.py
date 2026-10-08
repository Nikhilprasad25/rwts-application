"""Discrete-event simulation engine (spec section 18).

One :class:`Scenario` is built per repetition and is then replayed *identically*
for every algorithm (spec section 22): same workers, same hidden reliability,
same tasks, same contact events, and common random numbers for task outcomes,
so any difference in the results is attributable to the scheduler alone.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.algorithms.base import (KNOWLEDGE_ESTIMATED, KNOWLEDGE_TRUE, Scheduler,
                                 WorkerView)
from app.models.contact import ContactRecord
from app.models.task import Task, TaskStatus
from app.models.worker import Worker
from app.reliability.distributions import ReliabilityConfig, generate_true_reliability
from app.reliability.wrs import WRSConfig, WRSEstimator
from app.simulation.contact_model import ContactEvent, ContactModel, choose_requester
from app.simulation.events import EventQueue, EventType
from app.simulation.outcome_model import OutcomeConfig, OutcomeModel
from app.simulation.task_model import TaskConfig, generate_tasks


# --------------------------------------------------------------------------- #
@dataclass
class SimulationConfig:
    duration: float | None = None          # None => span of the contact trace
    contact_mode: str = "trace"            # trace | exponential
    requester_id: str | None = None
    tasks_per_contact: int = 1
    cold_start_history: int = 0
    seed: int = 12345
    unassigned_penalty_factor: float = 1.0  # C_i for never-finished tasks = factor*horizon

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "SimulationConfig":
        d = dict(d or {})
        known = set(cls.__dataclass_fields__)
        out: dict[str, Any] = {}
        for k, v in d.items():
            if k not in known:
                continue
            if k in {"contact_mode", "requester_id"}:
                out[k] = v
            elif k in {"tasks_per_contact", "cold_start_history", "seed"}:
                out[k] = int(v)
            else:
                out[k] = None if v is None else float(v)
        return cls(**out)

    def to_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass
class Scenario:
    """A fully-specified, reproducible experimental scenario."""
    repetition: int
    seed: int
    workers: list[Worker]
    tasks: list[Task]
    contact_events: list[ContactEvent]
    horizon: float
    requester_id: str | None
    lambdas: dict[str, float] = field(default_factory=dict)

    def fresh_workers(self) -> list[Worker]:
        """Deep-ish copy so each algorithm starts from the same worker state."""
        out = []
        for w in self.workers:
            out.append(Worker(
                worker_id=w.worker_id, lam=w.lam, contact_count=w.contact_count,
                mean_inter_contact_time=w.mean_inter_contact_time,
                true_reliability=w.true_reliability,
                observed_attempts=w.observed_attempts,
                observed_successes=w.observed_successes,
                observed_reworks=w.observed_reworks,
                delay_scores=list(w.delay_scores),
                wrs=w.wrs,
            ))
        return out

    def fresh_tasks(self) -> list[Task]:
        out = []
        for t in self.tasks:
            out.append(Task(task_id=t.task_id, creation_time=t.creation_time,
                            expected_service_time=t.expected_service_time,
                            weight=t.weight, deadline=t.deadline,
                            priority=t.priority))
        return out


# --------------------------------------------------------------------------- #
def build_scenario(records: list[ContactRecord],
                   lambdas: dict[str, float],
                   worker_ids: list[str],
                   task_cfg: TaskConfig,
                   rel_cfg: ReliabilityConfig,
                   wrs_cfg: WRSConfig,
                   sim_cfg: SimulationConfig,
                   repetition: int) -> Scenario:
    seed = int(sim_cfg.seed) + repetition
    rng = np.random.default_rng(seed)

    horizon = sim_cfg.duration
    if horizon is None or horizon <= 0:
        horizon = max((r.end_time for r in records), default=1.0)

    requester = sim_cfg.requester_id
    if sim_cfg.contact_mode == "trace" and requester is None:
        requester = choose_requester(records)
    worker_ids = [w for w in worker_ids if w != requester] or worker_ids

    truths = generate_true_reliability(len(worker_ids), rel_cfg, rng)
    workers = [Worker(worker_id=wid,
                      lam=float(lambdas.get(wid, 1e-6)),
                      mean_inter_contact_time=(1.0 / lambdas[wid]) if lambdas.get(wid) else 0.0,
                      true_reliability=float(truths[i]))
               for i, wid in enumerate(worker_ids)]

    estimator = WRSEstimator(wrs_cfg, np.random.default_rng(seed + 7919))
    for w in workers:
        estimator.seed_cold_start(w, sim_cfg.cold_start_history,
                                  np.random.default_rng(seed + hash(w.worker_id) % 100000))

    tasks = generate_tasks(task_cfg, rng)

    cm = ContactModel(sim_cfg.contact_mode, worker_ids, lambdas, horizon,
                      records, requester)
    events = cm.events(np.random.default_rng(seed + 104729))

    return Scenario(repetition=repetition, seed=seed, workers=workers, tasks=tasks,
                    contact_events=events, horizon=horizon,
                    requester_id=requester, lambdas=lambdas)


# --------------------------------------------------------------------------- #
class SimulationEngine:
    """Runs one scheduler over one scenario."""

    def __init__(self, scenario: Scenario, scheduler: Scheduler,
                 wrs_cfg: WRSConfig, outcome_cfg: OutcomeConfig,
                 sim_cfg: SimulationConfig):
        self.sc = scenario
        self.scheduler = scheduler
        self.wrs_cfg = wrs_cfg
        self.outcome = OutcomeModel(outcome_cfg)
        self.outcome_cfg = outcome_cfg
        self.sim_cfg = sim_cfg

        self.workers = scenario.fresh_workers()
        self.tasks = scenario.fresh_tasks()
        self.by_id = {w.worker_id: w for w in self.workers}
        self.task_by_id = {t.task_id: t for t in self.tasks}
        self.estimator = WRSEstimator(wrs_cfg,
                                      np.random.default_rng(scenario.seed + 31337))
        for w in self.workers:
            self.estimator.update(w, record=False)

        self.queues: dict[str, list[str]] = {w.worker_id: [] for w in self.workers}
        self.busy_until: dict[str, float] = {w.worker_id: 0.0 for w in self.workers}
        self.progress: dict[str, Any] = {"completed": 0, "failed": 0, "reworked": 0,
                                         "expired": 0, "sim_time": 0.0}

    # ------------------------------------------------------------------ #
    def _views(self) -> list[WorkerView]:
        views = []
        for w in self.workers:
            if self.scheduler.knowledge == KNOWLEDGE_TRUE:
                rel: float | None = w.true_reliability
            elif self.scheduler.knowledge == KNOWLEDGE_ESTIMATED:
                rel = w.wrs
            else:
                rel = None
            views.append(WorkerView(w.worker_id, w.lam, w.mean_meeting_delay, rel))
        return views

    # ------------------------------------------------------------------ #
    def run(self) -> dict[str, Any]:
        t_start = _time.perf_counter()
        horizon = self.sc.horizon

        views = self._views()
        assignment = self.scheduler.plan(list(self.tasks), views)
        for task_id, wid in assignment.items():
            t = self.task_by_id[task_id]
            t.assigned_worker = wid
            t.status = TaskStatus.WAITING_FOR_CONTACT
            t.log(0.0, "assigned", worker=wid)
            self.queues[wid].append(task_id)

        q = EventQueue()
        for ev in self.sc.contact_events:
            q.push(ev.time, EventType.CONTACT, worker=ev.worker_id)
        q.push(horizon, EventType.END)

        while q:
            ev = q.pop()
            now = ev.time
            self.progress["sim_time"] = now
            if ev.etype is EventType.END:
                break
            if ev.etype is EventType.CONTACT:
                self._handle_contact(now, ev.payload["worker"], q)
            elif ev.etype is EventType.SERVICE_COMPLETE:
                self._handle_completion(now, ev.payload, q)

        self._finalise(horizon)
        runtime = _time.perf_counter() - t_start
        return {
            "algorithm": self.scheduler.name,
            "tasks": [t.to_dict() for t in self.tasks],
            "workers": [w.to_dict() for w in self.workers],
            "wrs_history": {w.worker_id: w.wrs_history for w in self.workers},
            "horizon": horizon,
            "runtime_seconds": runtime,
            "scheduler": self.scheduler.describe(),
        }

    # ------------------------------------------------------------------ #
    def _handle_contact(self, now: float, wid: str, q: EventQueue) -> None:
        if wid not in self.queues:
            return
        if self.busy_until[wid] > now:
            return
        handed = 0
        while handed < max(self.sim_cfg.tasks_per_contact, 1) and self.queues[wid]:
            task_id = self.queues[wid].pop(0)
            task = self.task_by_id[task_id]
            if task.status in (TaskStatus.COMPLETED, TaskStatus.EXPIRED):
                continue
            if task.creation_time > now:
                self.queues[wid].append(task_id)
                break
            worker = self.by_id[wid]
            task.attempt_count += 1
            task.status = TaskStatus.IN_PROGRESS
            task.assigned_worker = wid
            if task.first_assigned_time is None:
                task.first_assigned_time = now
            task.log(now, "handover", worker=wid, attempt=task.attempt_count)

            rng = np.random.default_rng(
                [self.sc.seed, abs(hash(task_id)) % (2 ** 31), task.attempt_count])
            outcome = self.outcome.draw(task, worker, rng)
            finish = now + outcome.service_time
            self.busy_until[wid] = finish
            worker.busy_time += outcome.service_time
            task.total_service_time += outcome.service_time
            q.push(finish, EventType.SERVICE_COMPLETE, task=task_id, worker=wid,
                   success=outcome.success, delay_score=outcome.delay_score)
            handed += 1
            break      # one hand-over starts service; the worker is now busy

    # ------------------------------------------------------------------ #
    def _handle_completion(self, now: float, payload: dict[str, Any],
                           q: EventQueue) -> None:
        task = self.task_by_id[payload["task"]]
        worker = self.by_id[payload["worker"]]
        success = bool(payload["success"])
        self.estimator.observe(worker, success, not success, payload["delay_score"])

        if success:
            task.status = TaskStatus.COMPLETED
            task.completion_time = now
            worker.completed += 1
            self.progress["completed"] += 1
            task.log(now, "completed", worker=worker.worker_id)
            return

        worker.failed += 1
        task.status = TaskStatus.FAILED
        task.log(now, "failed", worker=worker.worker_id, attempt=task.attempt_count)
        self.progress["failed"] += 1

        if (not self.outcome_cfg.rework_on_failure
                or task.attempt_count >= self.outcome_cfg.max_attempts):
            task.status = TaskStatus.EXPIRED
            self.progress["expired"] += 1
            task.log(now, "abandoned")
            return

        # rework: back to the scheduler
        task.rework_count += 1
        worker.reworked += 1
        self.progress["reworked"] += 1
        task.status = TaskStatus.REWORK
        views = self._views()
        for v in views:
            v.load = max(self.busy_until[v.worker_id], now)
        new_worker = self.scheduler.reassign(task, views, now)
        task.assigned_worker = new_worker
        task.status = TaskStatus.WAITING_FOR_CONTACT
        self.queues[new_worker].append(task.task_id)
        task.log(now, "reassigned", worker=new_worker)

    # ------------------------------------------------------------------ #
    def _finalise(self, horizon: float) -> None:
        """Charge unfinished tasks a documented, task-specific penalty.

        A flat ``horizon`` penalty would make the TMS objective tie between any
        two algorithms that leave at least one task open, so the penalty carries
        the task's own outstanding work: ``factor*horizon + tau*(1 + reworks)``.
        """
        base = horizon * max(self.sim_cfg.unassigned_penalty_factor, 1.0)
        for t in self.tasks:
            penalty = base + t.expected_service_time * (1 + t.rework_count)
            if t.completion_time is None:
                if t.status is not TaskStatus.EXPIRED:
                    t.status = TaskStatus.EXPIRED
                    self.progress["expired"] += 1
                t.completion_time = penalty
                t.log(horizon, "unfinished_at_horizon")
