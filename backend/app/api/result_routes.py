"""Export endpoints (spec sections 35-36)."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.experiments import export, runner

router = APIRouter(prefix="/api/results", tags=["results"])

MEDIA = {
    "csv": "text/csv",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown",
    "png": "image/png",
    "pdf": "application/pdf",
    "zip": "application/zip",
}


@router.get("/{experiment_id}/export")
def export_results(experiment_id: str,
                   kind: str = Query("aggregated",
                                     pattern="^(aggregated|raw|config|summary|charts|bundle|chart)$"),
                   fmt: str = Query("csv", pattern="^(csv|json|xlsx|md|png|pdf|zip)$"),
                   metric: str = Query("total_weighted_completion_time")):
    try:
        if kind == "aggregated":
            df = export.aggregated_frame(experiment_id)
            data = (df.to_csv(index=False).encode() if fmt == "csv"
                    else df.to_json(orient="records", indent=2).encode() if fmt == "json"
                    else export.excel_workbook(experiment_id))
            fmt = fmt if fmt in ("csv", "json") else "xlsx"
        elif kind == "raw":
            df = export.raw_frame(experiment_id)
            data = (df.to_csv(index=False).encode() if fmt == "csv"
                    else df.to_json(orient="records", indent=2).encode())
            fmt = fmt if fmt in ("csv", "json") else "csv"
        elif kind == "config":
            data = json.dumps(runner.get(experiment_id)["config"], indent=2).encode()
            fmt = "json"
        elif kind == "summary":
            data = export.summary_markdown(experiment_id).encode()
            fmt = "md"
        elif kind == "chart":
            data = export.chart_png(experiment_id, metric)
            fmt = "png"
        elif kind == "charts":
            data = export.charts_pdf(experiment_id)
            fmt = "pdf"
        else:
            data = export.bundle_zip(experiment_id)
            fmt = "zip"
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:                                  # pragma: no cover
        raise HTTPException(500, str(exc)) from exc
    return Response(content=data, media_type=MEDIA[fmt], headers={
        "Content-Disposition": f'attachment; filename="{experiment_id}_{kind}.{fmt}"'})
