"""Tests for checkpoint admission and result aggregation."""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).parents[1]


def _load(name: str, script: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


MANIFESTS = _load("build_multitask_manifests", "build_multitask_manifests.py")
EXPORT = _load("export_multitask_family_agentic", "export_multitask_family_agentic.py")


def _arm(path: pathlib.Path, status: str = "COMPLETE") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "checkpoint": {"sampler_path": f"tinker://{path.parent.name}"}
        if status == "COMPLETE"
        else None,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_manifest_admits_only_complete_matched_pairs(tmp_path):
    seed0 = tmp_path / "seed0"
    replication = tmp_path / "replication"
    pooled = tmp_path / "pooled"
    for objective in ("binary", "quadratic"):
        _arm(seed0 / "medicine" / f"{objective}_seed0" / "arm.json")
    _arm(seed0 / "math" / "binary_seed0" / "arm.json")
    _arm(seed0 / "math" / "quadratic_seed0" / "arm.json", "FAILED_HEALTH_GATE")
    for seed in range(2):
        for objective in ("binary", "quadratic"):
            _arm(pooled / f"{objective}_seed{seed}" / "arm.json")
    payload = MANIFESTS.build(
        seed0_root=seed0,
        replication_root=replication,
        pooled_root=pooled,
        pooled_seeds=2,
    )
    assert payload["admitted_pairs"] == 3
    assert "medicine_binary_seed0" in payload["checkpoints"]
    assert "math_binary_seed0" not in payload["checkpoints"]
    assert "pooled_quadratic_seed1" in payload["checkpoints"]


def test_transfer_summary_keeps_seed_range_and_direction_count():
    rows = [
        {
            "training_domain": "pooled",
            "evaluation_domain": "gpqa",
            "accuracy_change": value,
            "high_confidence_wrong_change": -value,
            "high_confidence_error_90_change": -value / 2,
            "quadratic_score_change": value / 2,
        }
        for value in (0.01, 0.03, 0.02)
    ]
    summary = EXPORT._summarize_transfer(rows)[0]
    assert summary["matched_seed_pairs"] == 3
    assert summary["median_accuracy_change"] == 0.02
    assert summary["min_accuracy_change"] == 0.01
    assert summary["risk_reductions"] == 3
    assert summary["min_confidence_calibrated_score_change"] == 0.005
    assert summary["max_confidence_calibrated_score_change"] == 0.015


def test_transfer_levels_keep_before_after_context_and_weight_by_responses():
    cells = {
        "medicine_binary_seed0|math": {
            "training_domain": "medicine",
            "training_objective": "binary",
            "n": 100,
            "coverage": 0.50,
            "overall_accuracy": 0.40,
            "mean_confidence_among_answers": 0.90,
            "high_confidence_wrong_rate": 0.50,
            "high_confidence_error_90_rate": 0.25,
            "mean_quadratic_score": -0.10,
        },
        "medicine_binary_seed1|math": {
            "training_domain": "medicine",
            "training_objective": "binary",
            "n": 300,
            "coverage": 1.00,
            "overall_accuracy": 0.60,
            "mean_confidence_among_answers": 0.70,
            "high_confidence_wrong_rate": 0.30,
            "high_confidence_error_90_rate": 0.15,
            "mean_quadratic_score": 0.10,
        },
        "medicine_quadratic_seed0|math": {
            "training_domain": "medicine",
            "training_objective": "quadratic",
            "n": 100,
            "coverage": 0.50,
            "overall_accuracy": 0.40,
            "mean_confidence_among_answers": 0.50,
            "high_confidence_wrong_rate": 0.10,
            "high_confidence_error_90_rate": 0.05,
            "mean_quadratic_score": 0.20,
        },
    }
    rows = EXPORT._summarize_transfer_levels(cells)
    binary = next(
        row for row in rows if row["training_objective"] == "binary"
    )
    assert binary["matched_seed_pairs"] == 2
    assert binary["response_count"] == 400
    assert binary["items_per_checkpoint"] == "varies"
    assert binary["mean_accuracy"] == 0.55
    assert binary["mean_coverage"] == pytest.approx(0.875)
    assert binary["mean_accuracy_when_answered"] == pytest.approx(0.55 / 0.875)
    assert binary["mean_confidence_when_answered"] == pytest.approx(0.7285714286)
    assert binary["mean_signed_confidence_gap"] == pytest.approx(0.1)
    assert binary["mean_high_confidence_wrong_rate"] == 0.35
    assert binary["mean_high_confidence_error_90_rate"] == 0.175
    assert binary["mean_confidence_calibrated_score"] == 0.05


def _generalization_cell(training, objective, seed, n, **metrics):
    return {
        "training_domain": training,
        "training_objective": objective,
        "training_seed": seed,
        "n": n,
        **metrics,
    }


def test_generalization_summary_separates_same_other_and_unseen_domains():
    default = {
        "coverage": 0.5,
        "overall_accuracy": 0.25,
        "mean_confidence_among_answers": 0.8,
        "high_confidence_wrong_rate": 0.4,
        "high_confidence_error_90_rate": 0.2,
        "mean_quadratic_score": 0.1,
    }
    treated = {
        "coverage": 0.5,
        "overall_accuracy": 0.25,
        "mean_confidence_among_answers": 0.5,
        "high_confidence_wrong_rate": 0.1,
        "high_confidence_error_90_rate": 0.05,
        "mean_quadratic_score": 0.2,
    }
    cells = {}
    contrasts = []
    for evaluation, n in (
        ("medicine", 100), ("math", 200), ("ethics", 300), ("gpqa", 400)
    ):
        for objective, metrics in (("binary", default), ("quadratic", treated)):
            key = f"medicine_{objective}_seed0|{evaluation}"
            cells[key] = _generalization_cell(
                "medicine", objective, 0, n, **metrics
            )
        contrasts.append({
            "training_domain": "medicine",
            "training_seed": 0,
            "evaluation_domain": evaluation,
            "n": n,
            "accuracy_change": 0.0,
            "high_confidence_wrong_change": -0.3,
            "high_confidence_error_90_change": -0.15,
            "quadratic_score_change": 0.2,
        })

    rows = {
        row["scope"]: row
        for row in EXPORT._summarize_generalization(cells, contrasts)
    }
    assert rows["same_subject"]["pair_tests"] == 1
    assert rows["other_trained_subject"]["pair_tests"] == 2
    assert rows["unseen_gpqa"]["questions_per_arm"] == 400
    assert rows["all_off_domain"]["pair_tests"] == 3
    assert rows["all_off_domain"]["questions_per_arm"] == 900
    assert rows["all_off_domain"]["stored_responses"] == 1800
    # Overall accuracy is among all questions, while confidence is pooled only
    # among answered questions. The signed gap is therefore 80% - 50%.
    assert rows["same_subject"]["binary_accuracy_when_answered"] == 0.5
    assert rows["same_subject"]["binary_signed_confidence_gap"] == pytest.approx(0.3)
    assert rows["all_off_domain"]["high_confidence_risk_eliminated"] == pytest.approx(0.75)


def test_generalization_pairs_keep_training_pair_as_replication_unit():
    default = {
        "coverage": 0.5,
        "overall_accuracy": 0.25,
        "mean_confidence_among_answers": 0.8,
        "high_confidence_error_90_rate": 0.2,
        "mean_quadratic_score": 0.1,
    }
    treated = {
        "coverage": 0.5,
        "overall_accuracy": 0.25,
        "mean_confidence_among_answers": 0.5,
        "high_confidence_error_90_rate": 0.05,
        "mean_quadratic_score": 0.2,
    }
    cells = {}
    contrasts = []
    for evaluation, n, risk in (
        ("medicine", 100, -0.1),
        ("math", 200, -0.2),
        ("ethics", 300, -0.3),
        ("gpqa", 400, -0.4),
    ):
        for objective, metrics in (("binary", default), ("quadratic", treated)):
            key = f"medicine_{objective}_seed0|{evaluation}"
            cells[key] = _generalization_cell(
                "medicine", objective, 0, n, **metrics
            )
        contrasts.append({
            "training_domain": "medicine",
            "training_seed": 0,
            "evaluation_domain": evaluation,
            "n": n,
            "accuracy_change": 0.01,
            "high_confidence_wrong_change": risk,
            "high_confidence_error_90_change": risk / 2,
            "quadratic_score_change": 0.1,
        })
    row = EXPORT._summarize_generalization_pairs(cells, contrasts)[0]
    assert row["same_subject_pair_tests"] == 1
    assert row["off_domain_pair_tests"] == 3
    assert row["off_domain_questions_per_arm"] == 900
    assert row["same_subject_high_confidence_wrong_change"] == -0.1
    expected = (-0.2 * 200 - 0.3 * 300 - 0.4 * 400) / 900
    assert row["off_domain_high_confidence_wrong_change"] == expected
    assert row["same_subject_binary_signed_confidence_gap"] == pytest.approx(0.3)
    assert row["same_subject_quadratic_signed_confidence_gap"] == 0.0
    assert row["all_off_domain_signed_confidence_gap_change"] == pytest.approx(-0.3)
    assert row["same_subject_binary_confidence_calibrated_score"] == 0.1
    assert row["same_subject_quadratic_confidence_calibrated_score"] == 0.2
    assert row["all_off_domain_confidence_calibrated_score_change"] == 0.1
    assert row["same_subject_high_confidence_error_90_change"] == pytest.approx(
        -0.15
    )
    assert row["all_off_domain_high_confidence_error_90_change"] == pytest.approx(
        -0.15
    )
