"""Record-level validation of a canonically-mapped contact table (spec section 7)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

INVALID_RULES = {
    "invalid_timestamp": "timestamp missing or not numeric/parseable",
    "invalid_source": "source worker id missing or empty",
    "invalid_destination": "destination worker id missing or empty",
    "self_contact": "source worker equals destination worker",
    "negative_duration": "contact duration is negative",
    "non_finite": "timestamp or duration is infinite/NaN after conversion",
    "end_before_start": "contact end time precedes its start time",
}


@dataclass
class ValidationReport:
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows: int = 0
    missing_values: dict[str, int] = field(default_factory=dict)
    rule_counts: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rule_descriptions"] = {k: v for k, v in INVALID_RULES.items()
                                  if self.rule_counts.get(k)}
        return d


def validate(df: pd.DataFrame, max_examples: int = 25) -> tuple[pd.Series, ValidationReport]:
    """Return ``(row_is_valid_mask, report)`` for a canonical frame.

    The frame must already contain ``timestamp``, ``source_worker``,
    ``destination_worker``, ``duration``.
    """
    rep = ValidationReport(total_rows=int(len(df)))
    rep.missing_values = {c: int(df[c].isna().sum()) for c in df.columns}

    flags: dict[str, pd.Series] = {}
    flags["invalid_timestamp"] = df["timestamp"].isna()
    flags["invalid_source"] = df["source_worker"].isna() | (
        df["source_worker"].astype(str).str.strip() == "")
    flags["invalid_destination"] = df["destination_worker"].isna() | (
        df["destination_worker"].astype(str).str.strip() == "")
    flags["self_contact"] = (df["source_worker"].astype(str)
                             == df["destination_worker"].astype(str))
    dur = pd.to_numeric(df["duration"], errors="coerce")
    flags["negative_duration"] = dur < 0
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    flags["non_finite"] = ~np.isfinite(ts.fillna(np.nan)) | ~np.isfinite(dur.fillna(0.0))
    if "end_time" in df.columns:
        et = pd.to_numeric(df["end_time"], errors="coerce")
        flags["end_before_start"] = et < ts
    else:
        flags["end_before_start"] = pd.Series(False, index=df.index)

    invalid = pd.Series(False, index=df.index)
    for name, mask in flags.items():
        mask = mask.fillna(False)
        rep.rule_counts[name] = int(mask.sum())
        invalid = invalid | mask

    rep.invalid_rows = int(invalid.sum())
    rep.valid_rows = rep.total_rows - rep.invalid_rows
    rep.duplicate_rows = int(df.duplicated().sum())

    bad = df[invalid].head(max_examples)
    for idx, row in bad.iterrows():
        reasons = [n for n, m in flags.items() if bool(m.fillna(False).loc[idx])]
        rec = {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
               for k, v in row.items()}
        rec["_row"] = int(idx)
        rec["_reasons"] = reasons
        rep.examples.append(rec)

    if rep.valid_rows == 0:
        rep.warnings.append("No valid contact records remain — check the column mapping.")
    if rep.rule_counts.get("self_contact", 0) > 0.3 * max(rep.total_rows, 1):
        rep.warnings.append(
            "More than 30% of rows are self-contacts; the source/destination "
            "mapping may be reversed or pointing at the wrong columns.")
    return ~invalid, rep
