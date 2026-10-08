"""Canonical internal contact model (spec section 8)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class ContactRecord:
    """One observed encounter between two nodes of the mobile social network.

    ``timestamp`` and ``duration`` are expressed in the dataset's own time unit
    (seconds for the Cambridge Haggle traces). Worker identifiers are strings so
    that the simulation never depends on the source encoding.
    """
    timestamp: float
    source_worker: str
    destination_worker: str
    duration: float

    @property
    def end_time(self) -> float:
        return self.timestamp + self.duration

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkerContactParameters:
    """Per-worker inter-contact statistics (spec section 10)."""
    worker_id: str
    contact_count: int
    observation_start: float
    observation_end: float
    total_contact_time: float
    mean_inter_contact_time: float
    lam: float                      # lambda_j, contacts per time unit
    distinct_peers: int

    @property
    def observation_period(self) -> float:
        return max(self.observation_end - self.observation_start, 0.0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["observation_period"] = self.observation_period
        d["lambda"] = d.pop("lam")
        return d
