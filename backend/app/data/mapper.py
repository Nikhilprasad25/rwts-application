"""Column mapping between arbitrary source columns and the canonical schema.

Nothing downstream of :mod:`app.data.transformer` ever sees a source column
name: the simulation only interacts with the canonical model in
:mod:`app.models.contact` (spec section 8).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

# canonical field -> (required?, human label, synonyms)
CANONICAL_FIELDS: dict[str, dict[str, Any]] = {
    "timestamp": {
        "required": True,
        "label": "Contact Timestamp",
        "kind": "numeric_or_datetime",
        "synonyms": ["timestamp", "time", "start_time", "starttime", "start",
                     "contact_time", "begin", "t_start", "first_seen"],
    },
    "source_worker": {
        "required": True,
        "label": "Source Worker",
        "kind": "id",
        "synonyms": ["source", "source_node", "src", "node_a", "node1", "id",
                     "id1", "a", "from", "source_worker", "device", "node"],
    },
    "destination_worker": {
        "required": True,
        "label": "Destination Worker",
        "kind": "id",
        "synonyms": ["destination", "destination_node", "dst", "node_b",
                     "node2", "id2", "b", "to", "peer", "seen", "seen_id",
                     "destination_worker"],
    },
    "end_time": {
        "required": False,
        "label": "Contact End Time",
        "kind": "numeric_or_datetime",
        "synonyms": ["end_time", "endtime", "end", "stop", "t_end", "last_seen"],
    },
    "duration": {
        "required": False,
        "label": "Contact Duration",
        "kind": "numeric",
        "synonyms": ["duration", "contact_duration", "length", "dur",
                     "contact_time", "elapsed"],
    },
}

REQUIRED_FIELDS = [f for f, m in CANONICAL_FIELDS.items() if m["required"]]

# Column layout of the CRAWDAD / Cambridge Haggle ``contacts.ExpN`` traces.
# Recognised only when the file has a synthetic header and exactly 6 numeric
# columns; the researcher can still override every entry.
HAGGLE_LAYOUT = {
    "source_worker": "col_1",
    "destination_worker": "col_2",
    "timestamp": "col_3",
    "end_time": "col_4",
}


class MappingError(Exception):
    pass


@dataclass
class MappingSuggestion:
    field: str
    label: str
    required: bool
    suggested_column: str | None
    confidence: float
    reason: str


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def _score(column: str, synonyms: list[str]) -> tuple[float, str]:
    c = _norm(column)
    if c in synonyms:
        return 1.0, "exact name match"
    best, reason = 0.0, "no match"
    for s in synonyms:
        if c == s:
            return 1.0, "exact name match"
        if s in c or c in s:
            score = 0.85
            if score > best:
                best, reason = score, f"contains '{s}'"
        ratio = difflib.SequenceMatcher(None, c, s).ratio()
        if ratio > best:
            best, reason = ratio, f"similar to '{s}'"
    return best, reason


def suggest_mapping(df: pd.DataFrame, synthetic_header: bool = False
                    ) -> list[MappingSuggestion]:
    """Suggest a canonical mapping. Suggestions are advisory only."""
    columns = [str(c) for c in df.columns]
    numeric_cols = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]

    haggle = (synthetic_header and len(columns) == 6
              and len(numeric_cols) == 6
              and all(f"col_{i}" in columns for i in range(1, 7)))

    out: list[MappingSuggestion] = []
    for field, meta in CANONICAL_FIELDS.items():
        if haggle and field in HAGGLE_LAYOUT:
            out.append(MappingSuggestion(
                field, meta["label"], meta["required"], HAGGLE_LAYOUT[field],
                0.9, "recognised CRAWDAD/Haggle contact-trace layout"))
            continue
        if haggle:
            out.append(MappingSuggestion(field, meta["label"], meta["required"],
                                         None, 0.0,
                                         "derived from start/end time"))
            continue
        best_col, best_score, best_reason = None, 0.0, "no match"
        for col in columns:
            s, r = _score(col, meta["synonyms"])
            if s > best_score:
                best_col, best_score, best_reason = col, s, r
        if best_score < 0.55:
            best_col, best_reason = None, "no confident match — please choose"
        out.append(MappingSuggestion(field, meta["label"], meta["required"],
                                     best_col, round(best_score, 3), best_reason))

    # never map two canonical fields onto the same column by accident
    seen: dict[str, MappingSuggestion] = {}
    for s in out:
        if s.suggested_column is None:
            continue
        prev = seen.get(s.suggested_column)
        if prev is None:
            seen[s.suggested_column] = s
        elif s.confidence > prev.confidence:
            prev.suggested_column, prev.reason = None, "column already used"
            seen[s.suggested_column] = s
        else:
            s.suggested_column, s.reason = None, "column already used"
    return out


def validate_mapping(mapping: dict[str, str | None], columns: list[str]) -> None:
    for field in REQUIRED_FIELDS:
        if not mapping.get(field):
            raise MappingError(
                f"Required field '{CANONICAL_FIELDS[field]['label']}' is not mapped.")
    for field, col in mapping.items():
        if field not in CANONICAL_FIELDS:
            raise MappingError(f"Unknown canonical field '{field}'.")
        if col and col not in columns:
            raise MappingError(f"Column '{col}' does not exist in the sheet.")
    if not mapping.get("duration") and not mapping.get("end_time"):
        raise MappingError(
            "Map either 'Contact Duration' or 'Contact End Time' so contact "
            "duration can be determined.")


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Rename source columns to canonical names and drop everything else."""
    validate_mapping(mapping, [str(c) for c in df.columns])
    rename = {col: field for field, col in mapping.items() if col}
    out = df[[c for c in rename]].rename(columns=rename).copy()
    return out
