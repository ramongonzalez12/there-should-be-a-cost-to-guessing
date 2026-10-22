from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "export_openweight_followup.py"
SPEC = importlib.util.spec_from_file_location("export_openweight_followup", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_transfer_summary_keeps_magnitude_and_direction_counts():
    rows = [
        {
            "evaluation_domain": "gpqa",
            "accuracy_change": accuracy,
            "high_confidence_wrong_change": risk,
            "quadratic_score_change": score,
        }
        for accuracy, risk, score in ((-0.01, -0.10, 0.08), (-0.03, 0.02, 0.04))
    ]
    result = MODULE.summarize_transfer(rows)[0]
    assert result["matched_pairs"] == 2
    assert result["median_accuracy_change"] == -0.02
    assert result["risk_reductions"] == 1
    assert result["score_improvements"] == 2


def test_hidden_summary_preserves_each_seed():
    def cell(seed, objective, unauthorized, high, control):
        return {
            "training_seed": seed,
            "objective": objective,
            "unauthorized_action_rate": unauthorized,
            "high_confidence_unauthorized_rate": high,
            "authorized_control_completion": control,
        }

    summary = {"by_checkpoint": {
        "b0": cell(0, "binary", 0.8, 0.7, 1.0),
        "q0": cell(0, "quadratic", 0.6, 0.4, 1.0),
        "b1": cell(1, "binary", 0.9, 0.8, 0.9),
        "q1": cell(1, "quadratic", 0.7, 0.5, 1.0),
    }}
    rows = MODULE.summarize_hidden(summary)
    assert [row["training_seed"] for row in rows] == [0, 1]
    assert rows[0]["unauthorized_rate_change"] == pytest.approx(-0.2)
    assert rows[1]["authorized_completion_change"] == pytest.approx(0.1)
