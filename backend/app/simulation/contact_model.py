"""Requester/worker contact process (spec section 18).

Two modes, both driven by the prepared dataset:

``trace``
    Replay the observed encounters. One node is designated the requester (by
    default the node with the most contacts, which for the Cambridge Haggle
    Exp1 trace is a real iMote); every observed encounter involving that node
    becomes a hand-over opportunity with the peer worker.

``exponential``
    Sample inter-meeting times from Exp(lambda_j) using the lambda estimated
    from the same trace — the analytical contact model of Zhang et al. (2025).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal

import numpy as np

from app.models.contact import ContactRecord

ContactMode = Literal["trace", "exponential"]


@dataclass(slots=True)
class ContactEvent:
    time: float
    worker_id: str
    duration: float


class ContactModel:
    def __init__(self, mode: ContactMode, worker_ids: list[str],
                 lambdas: dict[str, float], horizon: float,
                 records: list[ContactRecord] | None = None,
                 requester_id: str | None = None):
        self.mode = mode
        self.worker_ids = worker_ids
        self.lambdas = lambdas
        self.horizon = horizon
        self.records = records or []
        self.requester_id = requester_id

    # ------------------------------------------------------------------ #
    def events(self, rng: np.random.Generator) -> list[ContactEvent]:
        """All hand-over opportunities within the horizon, sorted by time."""
        if self.mode == "trace" and self.records:
            return self._trace_events()
        return self._exponential_events(rng)

    def _trace_events(self) -> list[ContactEvent]:
        wanted = set(self.worker_ids)
        req = self.requester_id
        out: list[ContactEvent] = []
        for r in self.records:
            if r.timestamp > self.horizon:
                continue
            if req is not None:
                if r.source_worker == req and r.destination_worker in wanted:
                    out.append(ContactEvent(r.timestamp, r.destination_worker, r.duration))
                elif r.destination_worker == req and r.source_worker in wanted:
                    out.append(ContactEvent(r.timestamp, r.source_worker, r.duration))
            else:
                if r.source_worker in wanted:
                    out.append(ContactEvent(r.timestamp, r.source_worker, r.duration))
                if r.destination_worker in wanted:
                    out.append(ContactEvent(r.timestamp, r.destination_worker, r.duration))
        out.sort(key=lambda e: e.time)
        return out

    def _exponential_events(self, rng: np.random.Generator) -> list[ContactEvent]:
        out: list[ContactEvent] = []
        for wid in self.worker_ids:
            lam = self.lambdas.get(wid, 0.0)
            if lam <= 0:
                continue
            t = 0.0
            while True:
                t += float(rng.exponential(1.0 / lam))
                if t > self.horizon:
                    break
                out.append(ContactEvent(t, wid, 0.0))
        out.sort(key=lambda e: e.time)
        return out


def choose_requester(records: list[ContactRecord]) -> str:
    """Pick the busiest node as the requester when replaying a trace."""
    counts: dict[str, int] = {}
    for r in records:
        counts[r.source_worker] = counts.get(r.source_worker, 0) + 1
        counts[r.destination_worker] = counts.get(r.destination_worker, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else "1"
