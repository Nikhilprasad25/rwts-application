"""Result export in CSV / Excel / JSON / PNG / PDF (spec section 35)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import pandas as pd                      # noqa: E402

from app.config import EXPERIMENT_DIR, EXPORT_DIR, PROCESSED_DIR   # noqa: E402
from app.evaluation.metrics import CMS_METRIC, METRIC_LABELS, TMS_METRIC  # noqa: E402
from app.experiments import runner                                  # noqa: E402

CHART_METRICS = [CMS_METRIC, TMS_METRIC, "total_cost", "average_completion_time",
                 "rework_rate", "failure_rate", "average_attempts", "runtime_seconds"]


def _results(experiment_id: str) -> dict[str, Any]:
    return runner.results(experiment_id)


def aggregated_frame(experiment_id: str) -> pd.DataFrame:
    res = _results(experiment_id)
    rows = []
    for cond in res["conditions"]:
        comp = cond["comparison"]
        for algo in comp["algorithms"]:
            for metric, stats in comp["aggregate"][algo].items():
                rows.append({"condition": cond["label"], "algorithm": algo,
                             "metric": metric,
                             "metric_label": METRIC_LABELS.get(metric, metric),
                             **stats})
    return pd.DataFrame(rows)


def raw_frame(experiment_id: str) -> pd.DataFrame:
    p = EXPERIMENT_DIR / experiment_id / "raw_runs.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def summary_markdown(experiment_id: str) -> str:
    res = _results(experiment_id)
    comp = res["comparison"]
    cfg = res["config"]
    lines = [f"# Research summary — {experiment_id}", "",
             f"* Dataset: **{res['dataset']['filename']}** "
             f"({res['dataset']['summary']['contacts']} contacts, "
             f"{res['n_workers']} workers used)",
             f"* Tasks per repetition: {cfg['tasks']['n_tasks']}",
             f"* Repetitions: {cfg['repetitions']}  |  Seed: {cfg['simulation']['seed']}",
             f"* Reliability (SYNTHETIC): {cfg['reliability']['distribution']}, "
             f"mean {cfg['reliability']['mean']}, sd {cfg['reliability']['std']}",
             f"* WRS weights: completion {cfg['wrs']['completion_weight']:.2f}, "
             f"delay {cfg['wrs']['delay_weight']:.2f}, rework {cfg['wrs']['rework_weight']:.2f}"
             f" (Beta prior alpha={cfg['wrs']['alpha']}, beta={cfg['wrs']['beta']})",
             "", "## Primary results (mean over repetitions, 95% CI)", ""]
    header = "| Metric | " + " | ".join(comp["algorithms"]) + " |"
    lines += [header, "|" + "---|" * (len(comp["algorithms"]) + 1)]
    for metric in CHART_METRICS:
        if metric not in comp["metrics"]:
            continue
        cells = []
        for a in comp["algorithms"]:
            s = comp["aggregate"][a][metric]
            cells.append(f"{s['mean']:.4g} ± {max(s['ci_high'] - s['mean'], 0):.2g}")
        lines.append(f"| {METRIC_LABELS.get(metric, metric)} | " + " | ".join(cells) + " |")

    ratios = comp.get("approximation_ratios", {})
    if ratios.get(CMS_METRIC):
        lines += ["", "## Empirical approximation ratio vs. Oracle (CMS)", "",
                  "| Algorithm | Mean ratio | 95% CI |", "|---|---|---|"]
        for a, s in ratios[CMS_METRIC].items():
            lines.append(f"| {a} | {s['mean']:.4f} | "
                         f"[{s['ci_low']:.4f}, {s['ci_high']:.4f}] |")

    sig = comp.get("significance", {}).get(CMS_METRIC, {})
    if sig:
        lines += ["", "## Paired significance tests (CMS objective)", "",
                  "| Comparison | Mean difference | t p-value | Cohen's d |",
                  "|---|---|---|---|"]
        for k, v in sig.items():
            lines.append(f"| {k} | {v.get('mean_difference', float('nan')):.4g} | "
                         f"{v.get('t_p_value', float('nan')):.4g} | "
                         f"{v.get('cohens_d', float('nan')):.3f} |")

    lines += ["", "## Reproducibility", "",
              "```json", json.dumps(res["config"], indent=2, default=str)[:4000], "```",
              "", f"Configuration fingerprint: `{res['fingerprint']}`", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def chart_png(experiment_id: str, metric: str) -> bytes:
    res = _results(experiment_id)
    comp = res["comparison"]
    algos = comp["algorithms"]
    means = [comp["aggregate"][a][metric]["mean"] for a in algos]
    errs = [max(comp["aggregate"][a][metric]["ci_high"]
                - comp["aggregate"][a][metric]["mean"], 0) for a in algos]
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=140)
    ax.bar(algos, means, yerr=errs, capsize=4,
           color=["#6b7280", "#94a3b8", "#2563eb", "#0ea5e9", "#16a34a"][:len(algos)])
    ax.set_title(METRIC_LABELS.get(metric, metric))
    ax.set_ylabel(METRIC_LABELS.get(metric, metric))
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def charts_pdf(experiment_id: str) -> bytes:
    from matplotlib.backends.backend_pdf import PdfPages
    res = _results(experiment_id)
    comp = res["comparison"]
    algos = comp["algorithms"]
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69), dpi=140)
        fig.text(0.08, 0.92, f"RWTS experiment {experiment_id}", size=18, weight="bold")
        fig.text(0.08, 0.88, res["dataset"]["filename"], size=11)
        body = summary_markdown(experiment_id).split("## Primary results")[0]
        fig.text(0.08, 0.30, body.replace("#", "").strip()[:2600], size=9, va="bottom")
        pdf.savefig(fig); plt.close(fig)
        for metric in CHART_METRICS:
            if metric not in comp["metrics"]:
                continue
            means = [comp["aggregate"][a][metric]["mean"] for a in algos]
            errs = [max(comp["aggregate"][a][metric]["ci_high"]
                        - comp["aggregate"][a][metric]["mean"], 0) for a in algos]
            fig, ax = plt.subplots(figsize=(8.27, 4.5), dpi=140)
            ax.bar(algos, means, yerr=errs, capsize=4, color="#2563eb")
            ax.set_title(METRIC_LABELS.get(metric, metric))
            ax.grid(axis="y", alpha=0.25)
            fig.tight_layout()
            pdf.savefig(fig); plt.close(fig)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
def excel_workbook(experiment_id: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        aggregated_frame(experiment_id).to_excel(xl, sheet_name="aggregated", index=False)
        raw_frame(experiment_id).to_excel(xl, sheet_name="raw_runs", index=False)
        res = _results(experiment_id)
        pd.json_normalize(res["config"]).to_excel(xl, sheet_name="configuration", index=False)
        details = res.get("details", {})
        for algo, d in list(details.items())[:5]:
            pd.DataFrame(d["workers"]).to_excel(
                xl, sheet_name=f"workers_{algo}"[:31], index=False)
    return buf.getvalue()


def processed_dataset_bytes(dataset_id: str, fmt: str = "csv") -> bytes:
    path = PROCESSED_DIR / dataset_id / "contacts.csv"
    df = pd.read_csv(path)
    if fmt == "csv":
        return df.to_csv(index=False).encode()
    if fmt == "json":
        return df.to_json(orient="records", indent=2).encode()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        df.to_excel(xl, sheet_name="contacts", index=False)
        wp = pd.read_csv(PROCESSED_DIR / dataset_id / "worker_parameters.csv")
        wp.to_excel(xl, sheet_name="worker_parameters", index=False)
    return buf.getvalue()


def bundle_zip(experiment_id: str) -> bytes:
    res = _results(experiment_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("configuration.json", json.dumps(res["config"], indent=2, default=str))
        z.writestr("results.json", json.dumps(res, indent=2, default=str))
        z.writestr("aggregated_results.csv", aggregated_frame(experiment_id).to_csv(index=False))
        z.writestr("raw_runs.csv", raw_frame(experiment_id).to_csv(index=False))
        z.writestr("research_summary.md", summary_markdown(experiment_id))
        z.writestr("charts.pdf", charts_pdf(experiment_id))
        try:
            z.writestr("processed_dataset.csv",
                       processed_dataset_bytes(res["config"]["dataset_id"], "csv"))
        except Exception:                                    # pragma: no cover
            pass
    return buf.getvalue()
