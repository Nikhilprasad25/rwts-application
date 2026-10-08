"""Workbook inspection and safe reading.

Handles three physical shapes of "Excel" file:

1. genuine OOXML workbooks (.xlsx / .xlsm)  -> openpyxl, read_only, macros never executed
2. genuine legacy BIFF workbooks (.xls)     -> xlrd
3. delimited text files carrying an .xls/.dat extension (the CRAWDAD / Cambridge
   Haggle traces are tab separated text named ``contacts.Exp1.xls``) -> sniffed
   and read as text.  Header-less files get synthetic column names ``col_1..col_n``.

Nothing here ever evaluates a formula, macro or embedded script: openpyxl is
opened with ``data_only=True`` so only cached values are read.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pandas as pd

TEXT_DELIMITERS = ["\t", ",", ";", "|"]
_OOXML_MAGIC = b"PK\x03\x04"
_BIFF_MAGIC = b"\xd0\xcf\x11\xe0"


class DatasetReadError(Exception):
    """Raised when a workbook cannot be interpreted."""


@dataclass
class SheetInfo:
    name: str
    rows: int
    columns: int
    column_names: list[str]
    dtypes: dict[str, str]
    missing_values: dict[str, int]
    duplicate_rows: int
    synthetic_header: bool
    sample: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkbookInfo:
    filename: str
    file_size: int
    physical_format: str          # "xlsx" | "xls" | "delimited-text"
    delimiter: str | None
    sheet_count: int
    sheet_names: list[str]
    sheets: list[SheetInfo]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sheets"] = [s.to_dict() for s in self.sheets]
        return d


# --------------------------------------------------------------------------- #
# format detection
# --------------------------------------------------------------------------- #
def detect_format(path: str | Path) -> tuple[str, str | None]:
    """Return ``(physical_format, delimiter)`` by inspecting file content.

    The declared extension is deliberately *not* trusted (spec section 37).
    """
    path = Path(path)
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head.startswith(_OOXML_MAGIC):
        return "xlsx", None
    if head.startswith(_BIFF_MAGIC):
        return "xls", None
    # fall back to delimited text
    delim = _sniff_delimiter(path)
    if delim is None:
        raise DatasetReadError(
            f"{path.name} is neither an Excel workbook nor a recognisable "
            "delimited text file."
        )
    return "delimited-text", delim


def _sniff_delimiter(path: Path, sample_bytes: int = 64_000) -> str | None:
    raw = path.read_bytes()[:sample_bytes]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError:
            return None
    lines = [ln for ln in text.splitlines() if ln.strip()][:50]
    if not lines:
        return None
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters="".join(TEXT_DELIMITERS))
        if dialect.delimiter in TEXT_DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass
    # manual: pick the delimiter with the most consistent, >1 field count
    best, best_score = None, 0
    for d in TEXT_DELIMITERS:
        counts = [ln.count(d) for ln in lines]
        if min(counts) < 1:
            continue
        consistency = counts.count(max(set(counts), key=counts.count)) / len(counts)
        score = consistency * min(counts)
        if score > best_score:
            best, best_score = d, score
    return best


def _looks_like_header(values: list[Any]) -> bool:
    """A header row is all-text and contains no pure numbers."""
    if not values:
        return False
    non_null = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_null:
        return False
    numeric = 0
    for v in non_null:
        try:
            float(str(v).strip())
            numeric += 1
        except ValueError:
            pass
    return numeric == 0


# --------------------------------------------------------------------------- #
# sheet enumeration / reading
# --------------------------------------------------------------------------- #
def list_sheets(path: str | Path) -> tuple[str, str | None, list[str]]:
    fmt, delim = detect_format(path)
    if fmt == "xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        names = list(wb.sheetnames)
        wb.close()
    elif fmt == "xls":
        import xlrd

        book = xlrd.open_workbook(path, on_demand=True)
        names = list(book.sheet_names())
        book.release_resources()
    else:
        names = ["data"]
    return fmt, delim, names


def read_sheet(path: str | Path, sheet: str | None = None,
               nrows: int | None = None) -> tuple[pd.DataFrame, bool]:
    """Read one sheet into a DataFrame.

    Returns ``(dataframe, synthetic_header)`` where ``synthetic_header`` is True
    when the source had no header row and ``col_1..col_n`` names were generated.
    """
    path = Path(path)
    fmt, delim, names = list_sheets(path)
    sheet = sheet or names[0]
    if sheet not in names:
        raise DatasetReadError(f"Sheet '{sheet}' not found. Available: {names}")

    if fmt == "delimited-text":
        first = pd.read_csv(path, sep=delim, header=None, nrows=1,
                            dtype=str, engine="python", keep_default_na=False)
        synthetic = not _looks_like_header(list(first.iloc[0]))
        df = pd.read_csv(path, sep=delim, header=None if synthetic else 0,
                         nrows=nrows, engine="python",
                         skip_blank_lines=True, comment=None)
    else:
        engine = "openpyxl" if fmt == "xlsx" else "xlrd"
        probe = pd.read_excel(path, sheet_name=sheet, header=None, nrows=1,
                              engine=engine, dtype=object)
        synthetic = probe.empty or not _looks_like_header(list(probe.iloc[0]))
        df = pd.read_excel(path, sheet_name=sheet, header=None if synthetic else 0,
                           nrows=nrows, engine=engine)

    if synthetic:
        df.columns = [f"col_{i + 1}" for i in range(df.shape[1])]
    else:
        df.columns = [str(c).strip() if str(c) != "nan" else f"col_{i + 1}"
                      for i, c in enumerate(df.columns)]
    # drop fully-empty trailing columns produced by ragged text files
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")
    return df, synthetic


def _json_safe(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "item"):
        try:
            return _json_safe(v.item())
        except Exception:          # pragma: no cover
            return str(v)
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def inspect_workbook(path: str | Path, sample_rows: int = 10,
                     max_sheets: int = 20) -> WorkbookInfo:
    """Full inspection report used by the Dataset page (spec section 5)."""
    path = Path(path)
    fmt, delim, names = list_sheets(path)
    sheets: list[SheetInfo] = []
    for name in names[:max_sheets]:
        try:
            df, synthetic = read_sheet(path, name)
        except Exception as exc:                     # pragma: no cover
            sheets.append(SheetInfo(name, 0, 0, [], {}, {}, 0, False,
                                    [{"error": str(exc)}]))
            continue
        sample = [
            {c: _json_safe(v) for c, v in row.items()}
            for row in df.head(sample_rows).to_dict(orient="records")
        ]
        sheets.append(
            SheetInfo(
                name=name,
                rows=int(df.shape[0]),
                columns=int(df.shape[1]),
                column_names=[str(c) for c in df.columns],
                dtypes={str(c): str(t) for c, t in df.dtypes.items()},
                missing_values={str(c): int(df[c].isna().sum()) for c in df.columns},
                duplicate_rows=int(df.duplicated().sum()),
                synthetic_header=synthetic,
                sample=sample,
            )
        )
    return WorkbookInfo(
        filename=path.name,
        file_size=path.stat().st_size,
        physical_format=fmt,
        delimiter=delim,
        sheet_count=len(names),
        sheet_names=names,
        sheets=sheets,
    )
