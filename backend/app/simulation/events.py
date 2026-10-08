"""Event queue primitives for the discrete-event engine."""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class EventType(IntEnum):
    TASK_CREATED = 0
    CONTACT = 1
    SERVICE_COMPLETE = 2
    DEADLINE_CHECK = 3
    END = 4


@dataclass(order=True)
class Event:
    time: float
    order: int
    etype: EventType = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)


class EventQueue:
    def __init__(self) -> None:
        self._heap: list[Event] = []
        self._counter = itertools.count()

    def push(self, time: float, etype: EventType, **payload: Any) -> None:
        heapq.heappush(self._heap, Event(time, next(self._counter), etype, payload))

    def pop(self) -> Event:
        return heapq.heappop(self._heap)

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
