"""Dataset endpoints (spec section 36)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES
from app.data import dataset_manager as dm
from app.data.mapper import CANONICAL_FIELDS
from app.experiments.export import processed_dataset_bytes

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


class MappingRequest(BaseModel):
    sheet: str | None = None
    mapping: dict[str, str | None]


class PrepareRequest(BaseModel):
    sheet: str | None = None
    mapping: dict[str, str | None]
    cleaning: dict[str, Any] | None = None


class ConfigRequest(BaseModel):
    configuration: dict[str, Any]


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except dm.DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:                                # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/fields")
def canonical_fields() -> dict[str, Any]:
    return {
        "fields": [{"field": f, **{k: v for k, v in m.items() if k != "synonyms"}}
                   for f, m in CANONICAL_FIELDS.items()],
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@router.get("")
def list_datasets() -> dict[str, Any]:
    return {"datasets": dm.list_datasets()}


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    meta = _guard(dm.save_upload, file.filename or "upload.xlsx", content)
    return meta


@router.post("/sample")
def load_sample(name: str = Query("contacts.Exp1.xls")) -> dict[str, Any]:
    base = Path(__file__).resolve().parents[3] / "sample_data"
    path = base / Path(name).name
    if not path.exists():
        raise HTTPException(404, f"Sample dataset '{name}' not found.")
    return _guard(dm.register_local_file, path)


@router.get("/samples")
def list_samples() -> dict[str, Any]:
    base = Path(__file__).resolve().parents[3] / "sample_data"
    files = sorted(p.name for p in base.glob("*")) if base.exists() else []
    return {"samples": files}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str) -> dict[str, Any]:
    return _guard(dm.get_meta, dataset_id)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str) -> dict[str, str]:
    _guard(dm.delete_dataset, dataset_id)
    return {"status": "deleted"}


@router.get("/{dataset_id}/preview")
def preview(dataset_id: str, sheet: str | None = None,
            rows: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        meta = dm.get_meta(dataset_id)
        if meta.get("prepared"):
            return {"prepared": True, **dm.processed_preview(dataset_id, rows)}
        df, synthetic, sheet_name = dm.sheet_frame(dataset_id, sheet, nrows=rows)
        import json as _json
        return {"prepared": False, "sheet": sheet_name,
                "synthetic_header": synthetic,
                "columns": [str(c) for c in df.columns],
                "records": _json.loads(df.head(rows).to_json(orient="records"))}
    return _guard(_do)


@router.get("/{dataset_id}/mapping")
def mapping(dataset_id: str, sheet: str | None = None) -> dict[str, Any]:
    return _guard(dm.mapping_suggestions, dataset_id, sheet)


@router.post("/{dataset_id}/map")
def set_mapping(dataset_id: str, body: MappingRequest) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        meta = dm.get_meta(dataset_id)
        meta["mapping"] = body.mapping
        meta["sheet"] = body.sheet or meta.get("sheet")
        dm.save_meta(meta)
        return {"dataset_id": dataset_id, "mapping": body.mapping,
                "sheet": meta["sheet"]}
    return _guard(_do)


@router.post("/{dataset_id}/prepare")
def prepare(dataset_id: str, body: PrepareRequest) -> dict[str, Any]:
    return _guard(dm.prepare, dataset_id, body.sheet, body.mapping, body.cleaning)


@router.get("/{dataset_id}/validation")
def validation(dataset_id: str) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        meta = dm.get_meta(dataset_id)
        if not meta.get("prepared"):
            raise dm.DatasetError("Dataset has not been prepared yet.")
        return {"validation": meta["validation"], "funnel": meta["funnel"],
                "warnings": meta.get("warnings", []), "summary": meta["summary"]}
    return _guard(_do)


@router.get("/{dataset_id}/workers")
def worker_parameters(dataset_id: str) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        return {"worker_parameters":
                dm.processed_preview(dataset_id, 1)["worker_parameters"]}
    return _guard(_do)


@router.get("/{dataset_id}/configuration")
def configuration(dataset_id: str) -> dict[str, Any]:
    return _guard(dm.export_configuration, dataset_id)


@router.post("/{dataset_id}/configuration")
def apply_configuration(dataset_id: str, body: ConfigRequest) -> dict[str, Any]:
    return _guard(dm.apply_configuration, dataset_id, body.configuration)


@router.get("/{dataset_id}/export")
def export_processed(dataset_id: str, fmt: str = Query("csv", pattern="^(csv|json|xlsx)$")):
    data = _guard(processed_dataset_bytes, dataset_id, fmt)
    media = {"csv": "text/csv", "json": "application/json",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[fmt]
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="processed_{dataset_id}.{fmt}"'})
