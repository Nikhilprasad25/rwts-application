"""Oracle scheduler (spec section 21).

Identical machinery to RWTS-Expected-Rework, but the engine hands it the hidden
ground-truth reliability instead of the estimated WRS. It is a theoretical
benchmark only — never a deployable scheduler — and gives the denominator for
the empirical approximation ratio required by the proposal's Phase 4.
"""
from __future__ import annotations

from app.algorithms.base import KNOWLEDGE_TRUE
from app.algorithms.rwts import RWTSExpectedRework


class Oracle(RWTSExpectedRework):
    """Theoretical benchmark scheduler with access to true hidden reliability."""

    name = "Oracle"
    label = "Oracle (true reliability)"
    knowledge = KNOWLEDGE_TRUE
    objective = "cms"
    uses_reliability = True
