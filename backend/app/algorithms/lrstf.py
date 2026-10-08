"""LRSTF — Least Remaining Service Time First (reliability-agnostic TMS baseline).

Tasks are ordered by decreasing expected service time and each is placed on the
worker whose projected finishing time would be smallest, which is the standard
list-scheduling rule for minimising the maximum completion time. No reliability
information is provided.
"""
from __future__ import annotations

from app.algorithms.base import KNOWLEDGE_NETWORK, Scheduler


class LRSTF(Scheduler):
    """Least Remaining Service Time First — reliability-agnostic TMS baseline."""

    name = "LRSTF"
    label = "LRSTF (baseline, TMS)"
    knowledge = KNOWLEDGE_NETWORK
    objective = "tms"
    uses_reliability = False
