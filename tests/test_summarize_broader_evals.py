"""Broader-eval exports preserve model, training, and bias identities."""

import importlib.util
import json
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "summarize_broader_evals",
    pathlib.Path(__file__).parents[1] / "scripts" / "summarize_broader_evals.py",
)
assert _SPEC and _SPEC.loader
summary = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(summary)


def fixture():
    cell = {
        "n": 10,
        "accuracy": 0.6,
        "coverage": 0.9,
        "abstention": 0.1,
        "invalid": 0.0,
        "mean_confidence": 0.8,
        "confidence_std": 0.1,
        "signed_calibration_gap": 0.133,
        "expected_calibration_error": 0.2,
        "brier": 0.25,
        "confidence_auroc": 0.7,
        "mean_scores": {
            "binary": 0.6,
            "quadratic": 0.4,
            "quad_cost_0.04": 0.36,
            "quad_cost_0.09": 0.31,
            "quad_cost_0.16": 0.24,
        },
    }
    return {
        "design": {
            "model": "Qwen/Qwen3-8B",
            "checkpoints": {
                "quadratic-s2": {
                    "arm": "quadratic",
                    "dose": 500,
                    "training_seed": 2,
                }
            },
        },
        "by_benchmark": {
            "bbq": {
                "cells": {"quadratic-s2|neutral": cell},
                "by_stratum": {"Age|ambig": {"quadratic-s2|neutral": cell}},
                "bias": {
                    "quadratic-s2|neutral": {
                        "ambig": {
                            "n": 5,
                            "non_unknown_attempts": 2,
                            "accuracy": 0.6,
                            "raw_bias_score": 0.0,
                            "accuracy_scaled_bias_score": 0.0,
                        }
                    }
                },
            }
        },
    }


def test_flattened_rows_retain_training_and_score_fields():
    rows = summary.benchmark_rows([fixture()])

    assert rows[0]["training_seed"] == 2
    assert rows[0]["score_quadratic"] == 0.4
    assert rows[0]["signed_calibration_gap"] == 0.133


def test_stratum_rows_retain_the_native_subtask_label():
    rows = summary.stratum_rows([fixture()])

    assert rows[0]["stratum"] == "Age|ambig"
    assert rows[0]["benchmark"] == "bbq"
    assert rows[0]["training_seed"] == 2


def test_contrasts_are_paired_to_binary_within_seed():
    binary = summary.benchmark_rows([fixture()])[0]
    binary.update(
        {
            "checkpoint": "binary-s2",
            "arm": "binary",
            "accuracy": 0.5,
            "score_quadratic": 0.3,
        }
    )
    quadratic = dict(binary)
    quadratic.update(
        {
            "checkpoint": "quadratic-s2",
            "arm": "quadratic",
            "accuracy": 0.6,
            "score_quadratic": 0.4,
        }
    )

    rows = summary.contrast_rows(
        [binary, quadratic], identity_fields=("benchmark",)
    )

    assert rows[0]["training_seed"] == 2
    assert rows[0]["delta_accuracy"] == pytest.approx(0.1)
    assert rows[0]["delta_score_quadratic"] == pytest.approx(0.1)


def test_bbq_bias_contrasts_are_paired_within_seed():
    treatment = summary.bbq_rows([fixture()])[0]
    treatment["raw_bias_score"] = 0.2
    binary = dict(treatment)
    binary.update(
        {
            "checkpoint": "binary-s2",
            "arm": "binary",
            "raw_bias_score": 0.5,
            "non_unknown_attempts": 3,
        }
    )

    rows = summary.bbq_contrast_rows([binary, treatment])

    assert rows[0]["training_seed"] == 2
    assert rows[0]["delta_raw_bias_score"] == pytest.approx(-0.3)
    assert rows[0]["delta_non_unknown_attempts"] == pytest.approx(-1)


def test_exact_final_item_manifests_are_grouped_by_benchmark(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "items.jsonl").write_text(
        '\n'.join(
            [
                json.dumps({"benchmark": "bbq", "item_id": "bbq:2"}),
                json.dumps({"benchmark": "bbq", "item_id": "bbq:1"}),
                json.dumps(
                    {"benchmark": "truthfulqa_mc", "item_id": "truthfulqa_mc:1"}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    written = summary.export_item_manifests([run], output=tmp_path / "slices")

    assert json.loads(written["bbq"].read_text(encoding="utf-8")) == [
        "bbq:1",
        "bbq:2",
    ]
    assert written["truthfulqa_mc"].name == "truthfulqa_mc_broader_final_1.json"


def test_main_writes_screen_tables(tmp_path):
    run = tmp_path / "raw" / "screen_fixture"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps(fixture()), encoding="utf-8")

    assert (
        summary.main(
            ["--screen-root", str(tmp_path / "raw"), "--out", str(tmp_path / "out")]
        )
        == 0
    )
    assert "score_quadratic" in (
        tmp_path / "out" / "broader_model_screen.csv"
    ).read_text(encoding="utf-8")
    assert "Age|ambig" in (
        tmp_path / "out" / "broader_model_screen_strata.csv"
    ).read_text(encoding="utf-8")
    assert "accuracy_scaled_bias_score" in (
        tmp_path / "out" / "broader_model_screen_bbq_bias.csv"
    ).read_text(encoding="utf-8")
