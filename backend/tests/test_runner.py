"""Experiment runner: fairness across algorithms, repetitions and sweeps."""
import numpy as np
import pytest

from app.experiments import export, runner


@pytest.fixture(scope="module")
def finished(prepared_dataset):
    rec = runner.create({
        "dataset_id": prepared_dataset, "name": "runner-test", "repetitions": 4,
        "workers": {"mode": "top_n", "count": 6, "min_contacts": 5},
        "tasks": {"n_tasks": 25},
        "reliability": {"distribution": "normal", "mean": 0.7, "std": 0.2},
        "simulation": {"seed": 555},
        "sensitivity": {"enabled": True, "wrs_noise_levels": [0.0, 0.3],
                        "cold_start_history": [0, 50], "repetitions": 2},
    })
    runner.run(rec["experiment_id"])
    return rec["experiment_id"]


def test_status_reaches_completed(finished):
    s = runner.status(finished)
    assert s["status"] == "completed" and s["progress"] == 1.0


def test_every_repetition_is_stored(finished):
    df = export.raw_frame(finished)
    base = df[df.condition == "baseline"]
    assert set(base.algorithm.unique()) == {"LUCF", "LRSTF", "RWTS-M", "RWTS-ER", "Oracle"}
    assert base.groupby("algorithm").size().unique().tolist() == [4]


def test_seeds_are_shared_across_algorithms(finished):
    df = export.raw_frame(finished)
    base = df[df.condition == "baseline"]
    per_algo = {a: sorted(g["seed"].tolist())
                for a, g in base.groupby("algorithm")}
    assert len(set(map(tuple, per_algo.values()))) == 1, \
        "algorithms did not share the same scenario seeds"


def test_oracle_ratio_is_one_and_others_are_positive(finished):
    comp = runner.results(finished)["comparison"]
    ratios = comp["approximation_ratios"]["total_weighted_completion_time"]
    assert ratios["Oracle"]["mean"] == pytest.approx(1.0)
    assert all(v["mean"] > 0 for v in ratios.values())


def test_sensitivity_conditions_are_present(finished):
    labels = [c["label"] for c in runner.results(finished)["conditions"]]
    assert "baseline" in labels
    assert "wrs_noise=0.0" in labels and "wrs_noise=0.3" in labels
    assert "cold_start=0" in labels and "cold_start=50" in labels


def test_sweeps_use_their_own_repetition_count(finished):
    df = export.raw_frame(finished)
    sweep = df[df.condition == "cold_start=50"]
    assert sweep.groupby("algorithm").size().unique().tolist() == [2]


def test_cold_start_history_improves_the_wrs_estimate(finished):
    """More prior history must reduce the mean absolute WRS error."""
    res = runner.results(finished)
    # rebuild the two conditions' worker states through the public config path
    from app.data.dataset_manager import load_processed
    from app.data.transformer import compute_contact_parameters
    from app.experiments.configuration import ExperimentConfig
    from app.reliability.wrs import WRSConfig
    from app.simulation.engine import SimulationConfig, build_scenario
    from app.reliability.distributions import ReliabilityConfig
    from app.simulation.task_model import TaskConfig

    cfg = ExperimentConfig.from_dict(res["config"])
    records, _ = load_processed(cfg.dataset_id)
    params = compute_contact_parameters(records)
    ids = res["worker_ids"]
    lambdas = {w: params[w].lam for w in ids}

    def mae(history):
        sim = SimulationConfig.from_dict(cfg.simulation.to_dict() | {"cold_start_history": history})
        sc = build_scenario(records, lambdas, ids, cfg.tasks, cfg.reliability,
                            cfg.wrs, sim, repetition=0)
        return float(np.mean([abs(w.true_reliability - w.wrs) for w in sc.workers]))

    assert mae(200) < mae(0)


def test_summary_and_bundle_are_generated(finished):
    md = export.summary_markdown(finished)
    assert "Research summary" in md and "approximation ratio" in md.lower()
    assert len(export.bundle_zip(finished)) > 1000


def test_cancel_stops_a_running_experiment(prepared_dataset):
    """Cancelling mid-flight ends the run; a cancel issued before the start is
    cleared, so pressing Cancel then Run behaves as the user expects."""
    import time

    rec = runner.create({"dataset_id": prepared_dataset, "repetitions": 400,
                         "workers": {"mode": "top_n", "count": 8},
                         "tasks": {"n_tasks": 60}})
    eid = rec["experiment_id"]
    runner.run_async(eid)
    for _ in range(100):
        time.sleep(0.05)
        if runner.status(eid)["status"] == "running":
            break
    runner.cancel(eid)
    for _ in range(200):
        time.sleep(0.05)
        if runner.status(eid)["status"] in ("cancelled", "completed"):
            break
    assert runner.status(eid)["status"] == "cancelled"
