"""Cross-algorithm comparison, approximation ratios and rankings (spec 30/33)."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.evaluation.metrics import (CMS_METRIC, LOWER_IS_BETTER, METRIC_LABELS,
                                    TMS_METRIC)
from app.evaluation.statistics import paired_test, summarise

ORACLE = "Oracle"


def aggregate(per_run: dict[str, list[dict[str, float]]],
              confidence: float = 0.95) -> dict[str, Any]:
    """``per_run[algorithm] = [metrics_of_run_1, ...]`` -> aggregated statistics."""
    metrics = sorted({m for runs in per_run.values() for r in runs for m in r})
    agg: dict[str, dict[str, dict[str, float]]] = {}
    for algo, runs in per_run.items():
        agg[algo] = {m: summarise([r.get(m, float("nan")) for r in runs], confidence)
                     for m in metrics}

    ratios = approximation_ratios(per_run)
    return {
        "algorithms": list(per_run),
        "metrics": metrics,
        "metric_labels": {m: METRIC_LABELS.get(m, m) for m in metrics},
        "lower_is_better": sorted(LOWER_IS_BETTER & set(metrics)),
        "aggregate": agg,
        "approximation_ratios": ratios,
        "best": best_per_metric(agg, metrics),
        "significance": significance(per_run),
    }


def approximation_ratios(per_run: dict[str, list[dict[str, float]]]) -> dict[str, Any]:
    """Empirical approximation ratio of every algorithm against the Oracle."""
    if ORACLE not in per_run:
        return {}
    out: dict[str, Any] = {}
    for metric in (CMS_METRIC, TMS_METRIC, "total_cost"):
        base = np.array([r.get(metric, np.nan) for r in per_run[ORACLE]], float)
        per_metric: dict[str, dict[str, float]] = {}
        for algo, runs in per_run.items():
            vals = np.array([r.get(metric, np.nan) for r in runs], float)
            k = min(len(vals), len(base))
            if k == 0:
                continue
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(base[:k] > 0, vals[:k] / base[:k], np.nan)
            per_metric[algo] = summarise(ratio[~np.isnan(ratio)])
        out[metric] = per_metric
    return out


def best_per_metric(agg: dict[str, dict[str, dict[str, float]]],
                    metrics: list[str]) -> dict[str, str]:
    best: dict[str, str] = {}
    for m in metrics:
        candidates = {a: agg[a][m]["mean"] for a in agg if not np.isnan(agg[a][m]["mean"])}
        if not candidates:
            continue
        best[m] = (min(candidates, key=lambda a: candidates[a]) if m in LOWER_IS_BETTER
                   else max(candidates, key=lambda a: candidates[a]))
    return best


def significance(per_run: dict[str, list[dict[str, float]]]) -> dict[str, Any]:
    """Paired comparisons of every RWTS variant against every baseline."""
    rwts = [a for a in per_run if a.startswith("RWTS")]
    baselines = [a for a in per_run if a in ("LUCF", "LRSTF")]
    out: dict[str, Any] = {}
    for metric in (CMS_METRIC, TMS_METRIC):
        pairs = {}
        for r in rwts:
            for b in baselines:
                key = f"{r} vs {b}"
                pairs[key] = paired_test([x.get(metric, np.nan) for x in per_run[r]],
                                         [x.get(metric, np.nan) for x in per_run[b]])
        out[metric] = pairs
    return out
