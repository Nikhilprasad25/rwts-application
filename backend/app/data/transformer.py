"""Cleaning + transformation pipeline: raw sheet -> canonical ContactRecord set.

Every stage records how many rows entered and left, so the Dataset
Transformation screen (spec section 27) can show a fully transparent funnel.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.data import validator as _validator
from app.data.mapper import apply_mapping
from app.models.contact import ContactRecord, WorkerContactParameters

MissingStrategy = Literal["remove_row", "default", "forward_fill", "ignore"]


@dataclass
class CleaningOptions:
    missing_strategy: MissingStrategy = "remove_row"
    missing_defaults: dict[str, float] = field(default_factory=dict)
    remove_duplicates: bool = True
    remove_invalid: bool = True
    remove_self_contacts: bool = True
    min_duration: float = 0.0
    time_unit: str = "seconds"
    normalise_time_origin: bool = True      # shift so the first contact is t=0
    treat_as_undirected: bool = True        # a contact a-b also counts for b

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "CleaningOptions":
        d = dict(d or {})
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StageCount:
    stage: str
    rows: int
    removed: int
    note: str = ""


@dataclass
class TransformResult:
    records: list[ContactRecord]
    frame: pd.DataFrame
    funnel: list[StageCount]
    validation: dict[str, Any]
    cleaning: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
def _coerce_time(series: pd.Series) -> tuple[pd.Series, bool]:
    """Return numeric seconds. Datetime-like input is converted to epoch seconds."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.9:
        return numeric.astype("float64"), False
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    if parsed.notna().mean() >= 0.5:
        return parsed.astype("int64") / 1e9, True
    return numeric.astype("float64"), False


def transform(df_raw: pd.DataFrame, mapping: dict[str, str | None],
              options: CleaningOptions) -> TransformResult:
    funnel: list[StageCount] = []
    warnings: list[str] = []
    n0 = len(df_raw)
    funnel.append(StageCount("Raw records", n0, 0, "as read from the workbook"))

    df = apply_mapping(df_raw, mapping)
    funnel.append(StageCount("After column mapping", len(df), n0 - len(df),
                             "canonical columns only"))

    # ---- type conversion -------------------------------------------------
    df["timestamp"], was_datetime = _coerce_time(df["timestamp"])
    if was_datetime:
        warnings.append("Timestamps were parsed as datetimes and converted to epoch seconds.")
    df["source_worker"] = df["source_worker"].map(
        lambda v: "" if pd.isna(v) else str(v).strip().rstrip(".0")
        if isinstance(v, float) and float(v).is_integer() else ("" if pd.isna(v) else str(v).strip()))
    df["destination_worker"] = df["destination_worker"].map(
        lambda v: "" if pd.isna(v) else (str(int(v)) if isinstance(v, float) and float(v).is_integer()
                                         else str(v).strip()))
    df["source_worker"] = df["source_worker"].map(
        lambda s: s[:-2] if s.endswith(".0") else s)

    if "duration" in df.columns:
        df["duration"] = pd.to_numeric(df["duration"], errors="coerce")
    elif "end_time" in df.columns:
        df["end_time"], _ = _coerce_time(df["end_time"])
        df["duration"] = df["end_time"] - df["timestamp"]
    else:                                                  # pragma: no cover
        df["duration"] = 0.0
    if "end_time" in df.columns and "duration" in df.columns:
        df["end_time"] = df["timestamp"] + df["duration"].fillna(0.0)

    # ---- missing values --------------------------------------------------
    missing_before = int(df.isna().sum().sum())
    if options.missing_strategy == "remove_row":
        df = df.dropna(subset=["timestamp", "source_worker", "destination_worker"])
        df = df[df["duration"].notna() | df["duration"].isna()]
        df["duration"] = df["duration"].fillna(0.0)
    elif options.missing_strategy == "default":
        for col, dflt in (("duration", options.missing_defaults.get("duration", 0.0)),
                          ("timestamp", options.missing_defaults.get("timestamp", np.nan))):
            if col in df.columns:
                df[col] = df[col].fillna(dflt)
        df = df.dropna(subset=["timestamp"])
    elif options.missing_strategy == "forward_fill":
        df = df.ffill()
    # "ignore" leaves them for the validator to flag
    removed_missing = 0
    funnel.append(StageCount("After missing-value handling", len(df),
                             removed_missing,
                             f"strategy={options.missing_strategy}, "
                             f"{missing_before} missing cells found"))

    # ---- duplicates ------------------------------------------------------
    n_before = len(df)
    if options.remove_duplicates:
        df = df.drop_duplicates()
    funnel.append(StageCount("After duplicate removal", len(df), n_before - len(df)))

    # ---- validation ------------------------------------------------------
    df = df.reset_index(drop=True)
    valid_mask, report = _validator.validate(df)
    n_before = len(df)
    if options.remove_invalid:
        df = df[valid_mask].reset_index(drop=True)
    if options.remove_self_contacts and len(df):
        df = df[df["source_worker"] != df["destination_worker"]].reset_index(drop=True)
    funnel.append(StageCount("After validation", len(df), n_before - len(df),
                             f"{report.invalid_rows} invalid rows detected"))

    # ---- final filters ---------------------------------------------------
    n_before = len(df)
    if len(df):
        df = df[df["duration"] >= options.min_duration].reset_index(drop=True)
    if options.normalise_time_origin and len(df):
        t0 = float(df["timestamp"].min())
        df["timestamp"] = df["timestamp"] - t0
        if "end_time" in df.columns:
            df["end_time"] = df["end_time"] - t0
    df = df.sort_values("timestamp").reset_index(drop=True)
    funnel.append(StageCount("Processed records", len(df), n_before - len(df),
                             "canonical ContactRecord set"))

    records = [
        ContactRecord(float(r.timestamp), str(r.source_worker),
                      str(r.destination_worker), float(r.duration))
        for r in df.itertuples(index=False)
    ]
    return TransformResult(records=records, frame=df, funnel=funnel,
                           validation=report.to_dict(),
                           cleaning=options.to_dict(), warnings=warnings)


# --------------------------------------------------------------------------- #
def compute_contact_parameters(records: list[ContactRecord],
                               undirected: bool = True
                               ) -> dict[str, WorkerContactParameters]:
    """Estimate per-worker inter-contact parameters lambda_j (spec section 10).

    lambda_j is estimated as ``contacts_j / observation_period_j`` — the maximum
    likelihood rate of a homogeneous Poisson contact process, consistent with the
    exponential inter-meeting time model used by Zhang et al. (2025).
    """
    if not records:
        return {}
    t_min = min(r.timestamp for r in records)
    t_max = max(r.end_time for r in records)

    agg: dict[str, dict[str, Any]] = {}

    def touch(wid: str, rec: ContactRecord) -> None:
        e = agg.setdefault(wid, {"n": 0, "first": rec.timestamp, "last": rec.end_time,
                                 "dur": 0.0, "peers": set(), "times": []})
        e["n"] += 1
        e["first"] = min(e["first"], rec.timestamp)
        e["last"] = max(e["last"], rec.end_time)
        e["dur"] += rec.duration
        e["times"].append(rec.timestamp)

    for rec in records:
        touch(rec.source_worker, rec)
        agg[rec.source_worker]["peers"].add(rec.destination_worker)
        if undirected:
            touch(rec.destination_worker, rec)
            agg[rec.destination_worker]["peers"].add(rec.source_worker)

    out: dict[str, WorkerContactParameters] = {}
    for wid, e in agg.items():
        period = max(t_max - t_min, 1e-9)
        lam = e["n"] / period
        times = sorted(e["times"])
        if len(times) > 1:
            gaps = np.diff(times)
            mict = float(np.mean(gaps)) if len(gaps) else period
        else:
            mict = period
        out[wid] = WorkerContactParameters(
            worker_id=wid, contact_count=e["n"],
            observation_start=t_min, observation_end=t_max,
            total_contact_time=e["dur"],
            mean_inter_contact_time=mict,
            lam=lam, distinct_peers=len(e["peers"]),
        )
    return dict(sorted(out.items(), key=lambda kv: -kv[1].contact_count))
