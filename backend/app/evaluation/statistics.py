"""Aggregation across repetitions (spec section 24)."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from scipy import stats


def summarise(values: Iterable[float], confidence: float = 0.95) -> dict[str, float]:
    arr = np.asarray(list(values), dtype=float)
    n = len(arr)
    if n == 0:
        return {k: float("nan") for k in
                ("mean", "median", "std", "ci_low", "ci_high", "min", "max", "n")}
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    if n > 1 and std > 0:
        half = float(stats.t.ppf(0.5 + confidence / 2, n - 1)) * std / np.sqrt(n)
    else:
        half = 0.0
    return {
        "mean": mean,
        "median": float(np.median(arr)),
        "std": std,
        "ci_low": mean - half,
        "ci_high": mean + half,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "n": float(n),
    }


def paired_test(a: Iterable[float], b: Iterable[float]) -> dict[str, float]:
    """Paired t-test + Wilcoxon between two algorithms on common scenarios."""
    x, y = np.asarray(list(a), float), np.asarray(list(b), float)
    out: dict[str, float] = {"n": float(len(x))}
    if len(x) < 2 or len(x) != len(y):
        return out
    try:
        t, p = stats.ttest_rel(x, y)
        out["t_statistic"], out["t_p_value"] = float(t), float(p)
    except Exception:                                     # pragma: no cover
        pass
    try:
        if np.any(x - y):
            w, pw = stats.wilcoxon(x, y)
            out["wilcoxon_statistic"], out["wilcoxon_p_value"] = float(w), float(pw)
    except Exception:                                     # pragma: no cover
        pass
    diff = x - y
    pooled = np.std(diff, ddof=1) if len(diff) > 1 else 0.0
    out["mean_difference"] = float(diff.mean())
    out["cohens_d"] = float(diff.mean() / pooled) if pooled else 0.0
    return out
