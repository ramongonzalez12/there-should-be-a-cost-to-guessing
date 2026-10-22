"""Tests for the matched common-battery training export."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "export_training_common_battery",
    Path(__file__).parents[1] / "scripts" / "export_training_common_battery.py",
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def row(outcome, probability, quadratic):
    return {
        "outcome": outcome,
        "probability": probability,
        "scores": {"quadratic": quadratic},
    }


def test_three_endpoints_use_their_declared_denominators():
    rows = [
        row("CORRECT", 0.8, 0.96),
        row("INCORRECT", 0.95, -0.9025),
        row("ABSTAINED", None, 0.0),
        row("INVALID", None, -1.0),
    ]

    result = exporter.metrics(rows)

    assert result["scheduled_n"] == 4
    assert result["usable_attempt_n"] == 2
    assert result["accuracy_on_usable_attempts"] == pytest.approx(0.5)
    assert result["mean_confidence_on_usable_attempts"] == pytest.approx(0.875)
    assert result["signed_overconfidence_gap"] == pytest.approx(0.375)
    assert result["confidence_adjusted_accuracy"] == pytest.approx(-0.235625)
    assert result["high_confidence_error_90_count"] == 1
    assert result["high_confidence_error_90_rate"] == pytest.approx(0.25)


def test_high_confidence_correct_answers_do_not_enter_the_error_tail():
    result = exporter.metrics(
        [
            row("CORRECT", 0.99, 0.9999),
            row("INCORRECT", 0.89, -0.7921),
        ]
    )

    assert result["high_confidence_error_90_count"] == 0
