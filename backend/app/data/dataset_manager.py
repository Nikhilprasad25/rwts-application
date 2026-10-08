"""Dataset registry: raw files, processed datasets and reusable configurations.

Raw uploads are never modified (spec section 11). Everything is file-based
JSON/CSV/Parquet-free storage so the project stays database-less (spec 38).
"""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app import storage_io
from app.config import (ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES,
                        PROCESSED_DIR, RAW_DIR)
from app.data import excel_reader
from app.data.mapper import suggest_mapping
from app.data.transformer import (CleaningOptions, compute_contact_parameters,
                                  transform)
from app.models.contact import ContactRecord


class DatasetError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta_path(dataset_id: str) -> Path:
    return RAW_DIR / f"{dataset_id}.json"


# --------------------------------------------------------------------------- #
# upload / inspection
# --------------------------------------------------------------------------- #
def save_upload(filename: str, content: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise DatasetError(
            f"Extension '{ext}' is not allowed. Permitted: {sorted(ALLOWED_EXTENSIONS)}")
    if len(content) > MAX_UPLOAD_BYTES:
        raise DatasetError(f"File exceeds the {MAX_UPLOAD_BYTES // (1024*1024)} MB limit.")
    if not content:
        raise DatasetError("Uploaded file is empty.")

    dataset_id = uuid.uuid4().hex[:12]
    safe_name = Path(filename).name.replace("\\", "_").replace("/", "_")
    stored = RAW_DIR / f"{dataset_id}{ext}"
    storage_io.write_bytes(stored, content)

    try:
        info = excel_reader.inspect_workbook(stored)
    except Exception as exc:
        stored.unlink(missing_ok=True)
        raise DatasetError(f"Could not read the workbook: {exc}") from exc

    meta = {
        "dataset_id": dataset_id,
        "original_filename": safe_name,
        "stored_path": str(stored),
        "uploaded_at": _now(),
        "workbook": info.to_dict(),
        "prepared": False,
    }
    storage_io.write_json(_meta_path(dataset_id), meta)
    return meta


def register_local_file(path: str | Path) -> dict[str, Any]:
    """Register a file already on disk (used for the bundled sample data)."""
    p = Path(path)
    if not p.exists():
        raise DatasetError(f"{p} does not exist")
    return save_upload(p.name, p.read_bytes())


def get_meta(dataset_id: str) -> dict[str, Any]:
    meta = storage_io.read_json(_meta_path(dataset_id))
    if meta is None:
        raise DatasetError(f"Unknown dataset '{dataset_id}'")
    return meta


def save_meta(meta: dict[str, Any]) -> None:
    storage_io.write_json(_meta_path(meta["dataset_id"]), meta)


def list_datasets() -> list[dict[str, Any]]:
    out = []
    for f in sorted(RAW_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            m = json.loads(f.read_text())
        except Exception:                                   # pragma: no cover
            continue
        out.append({
            "dataset_id": m["dataset_id"],
            "original_filename": m["original_filename"],
            "uploaded_at": m["uploaded_at"],
            "prepared": m.get("prepared", False),
            "sheet_names": m["workbook"]["sheet_names"],
            "rows": m["workbook"]["sheets"][0]["rows"] if m["workbook"]["sheets"] else 0,
            "summary": m.get("summary"),
        })
    return out


def delete_dataset(dataset_id: str) -> None:
    meta = get_meta(dataset_id)
    Path(meta["stored_path"]).unlink(missing_ok=True)
    _meta_path(dataset_id).unlink(missing_ok=True)
    shutil.rmtree(PROCESSED_DIR / dataset_id, ignore_errors=True)


# --------------------------------------------------------------------------- #
# mapping suggestions / preview
# --------------------------------------------------------------------------- #
def sheet_frame(dataset_id: str, sheet: str | None = None,
                nrows: int | None = None) -> tuple[pd.DataFrame, bool, str]:
    meta = get_meta(dataset_id)
    sheet = sheet or meta.get("sheet") or meta["workbook"]["sheet_names"][0]
    df, synthetic = excel_reader.read_sheet(meta["stored_path"], sheet, nrows=nrows)
    return df, synthetic, sheet


def mapping_suggestions(dataset_id: str, sheet: str | None = None) -> dict[str, Any]:
    df, synthetic, sheet = sheet_frame(dataset_id, sheet)
    sugg = suggest_mapping(df, synthetic)
    return {
        "dataset_id": dataset_id,
        "sheet": sheet,
        "columns": [str(c) for c in df.columns],
        "synthetic_header": synthetic,
        "suggestions": [s.__dict__ for s in sugg],
    }


# --------------------------------------------------------------------------- #
# preparation
# --------------------------------------------------------------------------- #
def prepare(dataset_id: str, sheet: str | None, mapping: dict[str, str | None],
            cleaning: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the full preparation pipeline and persist the processed dataset."""
    df, _synthetic, sheet = sheet_frame(dataset_id, sheet)
    options = CleaningOptions.from_dict(cleaning)
    result = transform(df, mapping, options)
    if not result.records:
        raise DatasetError("Preparation produced zero valid contact records.")

    params = compute_contact_parameters(result.records, undirected=options.treat_as_undirected)

    outdir = PROCESSED_DIR / dataset_id
    outdir.mkdir(parents=True, exist_ok=True)
    result.frame.to_csv(outdir / "contacts.csv", index=False)
    pd.DataFrame([p.to_dict() for p in params.values()]).to_csv(
        outdir / "worker_parameters.csv", index=False)

    times = [r.timestamp for r in result.records]
    summary = {
        "workers": len(params),
        "contacts": len(result.records),
        "total_records": len(result.records),
        "time_start": min(times),
        "time_end": max(r.end_time for r in result.records),
        "duration": max(r.end_time for r in result.records) - min(times),
        "average_contacts_per_worker": round(
            sum(p.contact_count for p in params.values()) / max(len(params), 1), 2),
        "average_inter_contact_time": round(
            float(sum(p.mean_inter_contact_time for p in params.values())
                  / max(len(params), 1)), 2),
        "average_contact_duration": round(
            sum(r.duration for r in result.records) / len(result.records), 2),
        "time_unit": options.time_unit,
    }

    meta = get_meta(dataset_id)
    meta.update({
        "prepared": True,
        "prepared_at": _now(),
        "sheet": sheet,
        "mapping": mapping,
        "cleaning": result.cleaning,
        "funnel": [f.__dict__ for f in result.funnel],
        "validation": result.validation,
        "warnings": result.warnings,
        "summary": summary,
        "processed_dir": str(outdir),
    })
    save_meta(meta)

    return {
        "dataset_id": dataset_id,
        "summary": summary,
        "funnel": meta["funnel"],
        "validation": meta["validation"],
        "warnings": result.warnings,
        "worker_parameters": [p.to_dict() for p in params.values()],
        "preview": _preview_records(result.frame),
    }


def _preview_records(frame: pd.DataFrame, n: int = 100) -> list[dict[str, Any]]:
    return json.loads(frame.head(n).to_json(orient="records"))


def load_processed(dataset_id: str) -> tuple[list[ContactRecord], dict[str, Any]]:
    meta = get_meta(dataset_id)
    if not meta.get("prepared"):
        raise DatasetError("Dataset has not been prepared yet.")
    path = PROCESSED_DIR / dataset_id / "contacts.csv"
    df = pd.read_csv(path)
    records = [ContactRecord(float(r.timestamp), str(r.source_worker),
                             str(r.destination_worker), float(r.duration))
               for r in df.itertuples(index=False)]
    return records, meta


def processed_preview(dataset_id: str, n: int = 100) -> dict[str, Any]:
    meta = get_meta(dataset_id)
    if not meta.get("prepared"):
        raise DatasetError("Dataset has not been prepared yet.")
    df = pd.read_csv(PROCESSED_DIR / dataset_id / "contacts.csv", nrows=n)
    wp = pd.read_csv(PROCESSED_DIR / dataset_id / "worker_parameters.csv")
    return {
        "summary": meta["summary"],
        "records": json.loads(df.to_json(orient="records")),
        "worker_parameters": json.loads(wp.to_json(orient="records")),
        "funnel": meta.get("funnel", []),
        "validation": meta.get("validation", {}),
    }


# --------------------------------------------------------------------------- #
# reusable dataset configuration (spec section 12)
# --------------------------------------------------------------------------- #
def export_configuration(dataset_id: str) -> dict[str, Any]:
    meta = get_meta(dataset_id)
    return {
        "dataset": meta["original_filename"],
        "sheet": meta.get("sheet"),
        "column_mapping": meta.get("mapping"),
        "cleaning": meta.get("cleaning"),
        "prepared_at": meta.get("prepared_at"),
        "summary": meta.get("summary"),
        "app_version": "1.0.0",
    }


def apply_configuration(dataset_id: str, config: dict[str, Any]) -> dict[str, Any]:
    return prepare(dataset_id, config.get("sheet"), config["column_mapping"],
                   config.get("cleaning"))
