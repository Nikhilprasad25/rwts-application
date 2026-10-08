"""Algorithm registry — the single place the API and runner look algorithms up."""
from __future__ import annotations

from typing import Any

from app.algorithms.base import Scheduler
from app.algorithms.lrstf import LRSTF
from app.algorithms.lucf import LUCF
from app.algorithms.oracle import Oracle
from app.algorithms.rwts import RWTSExpectedRework, RWTSMultiplicative

ALGORITHMS: dict[str, type[Scheduler]] = {
    "LUCF": LUCF,
    "LRSTF": LRSTF,
    "RWTS-M": RWTSMultiplicative,
    "RWTS-ER": RWTSExpectedRework,
    "Oracle": Oracle,
}

DEFAULT_SELECTION = ["LUCF", "LRSTF", "RWTS-M", "RWTS-ER", "Oracle"]


def build(name: str, params: dict[str, Any] | None = None) -> Scheduler:
    if name not in ALGORITHMS:
        raise KeyError(f"Unknown algorithm '{name}'. Available: {list(ALGORITHMS)}")
    return ALGORITHMS[name](**(params or {}))


def catalogue() -> list[dict[str, Any]]:
    out = []
    for name, cls in ALGORITHMS.items():
        inst = cls()
        d = inst.describe()
        d["doc"] = (cls.__doc__ or "").strip().split("\n")[0]
        out.append(d)
    return out
