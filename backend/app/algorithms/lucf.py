"""LUCF — Least Unit Cost First (reliability-agnostic CMS baseline).

Zhang et al. (2025) order tasks by unit cost w_i/tau_i and greedily place each on
the worker that adds least to the total weighted completion time, where a
worker's expected occupancy for a task is the expected time to the next
encounter (1/lambda_j) plus the required service time. The scheduler receives
no reliability information at all.
"""
from __future__ import annotations

from app.algorithms.base import KNOWLEDGE_NETWORK, Scheduler


class LUCF(Scheduler):
    """Least Unit Cost First — reliability-agnostic CMS baseline."""

    name = "LUCF"
    label = "LUCF (baseline, CMS)"
    knowledge = KNOWLEDGE_NETWORK
    objective = "cms"
    uses_reliability = False
