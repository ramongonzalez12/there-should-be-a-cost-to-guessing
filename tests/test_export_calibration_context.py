import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_calibration_context",
    ROOT / "scripts" / "export_calibration_context.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_calibration_bins_keep_empty_deciles_and_actual_confidence_means():
    rows = [
        {"experiment": "x", "cohort": "c", "arm": "a",
         "probability": 0.11, "correct": False},
        {"experiment": "x", "cohort": "c", "arm": "a",
         "probability": 0.19, "correct": True},
        {"experiment": "x", "cohort": "c", "arm": "a",
         "probability": 1.0, "correct": True},
    ]

    result = MODULE.calibration_bins(rows)

    assert len(result) == 10
    assert result[0]["n"] == 0
    assert result[0]["accuracy"] == ""
    assert result[1]["n"] == 2
    assert result[1]["mean_confidence"] == pytest.approx(0.15)
    assert result[1]["accuracy"] == pytest.approx(0.5)
    assert result[9]["n"] == 1


def test_training_levels_use_only_paired_seed_cells():
    rows = []
    for objective, seed, probability, outcome in (
        ("binary", 0, 0.9, "INCORRECT"),
        ("quadratic", 0, 0.6, "CORRECT"),
        ("binary", 1, 1.0, "INCORRECT"),
        ("quadratic", 1, 0.7, "CORRECT"),
    ):
        rows.append({
            "model_family": "Family", "evaluation_domain": "math",
            "training_objective": objective, "training_seed": seed,
            "outcome": outcome, "probability": probability,
            "scores": {"quadratic": 0.2 if objective == "binary" else 0.8},
        })

    result = MODULE.summarize_training_levels(rows)
    index = {row["training_objective"]: row for row in result}

    assert index["binary"]["matched_seed_pairs"] == 2
    assert index["binary"]["mean_accuracy"] == 0
    assert index["binary"]["mean_high_confidence_wrong_rate"] == 1
    assert index["quadratic"]["mean_accuracy"] == 1
    assert index["quadratic"]["mean_confidence_among_answers"] == pytest.approx(0.65)


def test_training_baseline_must_use_the_same_items_as_every_trained_cell():
    baseline = [
        {"model_family": "Family", "evaluation_domain": "math",
         "item_id": item_id}
        for item_id in ("a", "b")
    ]
    trained = [
        {"model_family": "Family", "evaluation_domain": "math",
         "training_objective": objective, "training_seed": seed,
         "item_id": item_id}
        for objective in ("binary", "quadratic")
        for seed in (0, 1)
        for item_id in ("a", "b")
    ]

    MODULE._validate_training_battery_identity(baseline, trained)

    trained[-1]["item_id"] = "different"
    with pytest.raises(ValueError, match="does not match its untuned battery"):
        MODULE._validate_training_battery_identity(baseline, trained)


def test_committed_reliability_export_includes_the_untuned_training_curve():
    with (ROOT / "data" / "processed" /
          "calibration_reliability_bins.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    baseline = [
        row for row in rows
        if row["experiment"] == "training"
        and row["arm"] == "untuned_baseline"
    ]

    assert len(baseline) == 10
    assert sum(int(row["n"]) for row in baseline) == 1631
