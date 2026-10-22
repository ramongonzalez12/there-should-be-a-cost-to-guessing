import importlib.util
import math
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_prompt_only_calibration.py"
SPEC = importlib.util.spec_from_file_location("prompt_only_analysis", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def record(*, verdict="correct", confidence=0.8, parse_failure=False):
    attempted = float(verdict != "abstained")
    correct = float(verdict == "correct")
    usable = float(attempted and not parse_failure and confidence is not None)
    if verdict == "abstained":
        score = 0.0
    else:
        p = 1.0 if confidence is None else confidence
        score = (2 * p - p * p) if correct else -(p * p)
    return MODULE.Record(
        model="m", benchmark="b", item_id="q", arm="control", rep=0,
        attempted=attempted, usable=usable,
        correct_usable=correct if usable else math.nan,
        confidence_usable=confidence if usable else math.nan,
        score=score, parse_failure=float(parse_failure), cost_usd=0.0,
    )


def test_metrics_use_the_same_usable_subset_for_accuracy_and_confidence():
    rows = [
        record(verdict="correct", confidence=0.8),
        record(verdict="incorrect", confidence=0.6),
        record(verdict="incorrect", confidence=None, parse_failure=True),
        record(verdict="abstained", confidence=None),
    ]

    result = MODULE.metric_row(rows)

    assert result["answer_rate"] == pytest.approx(0.75)
    assert result["usable_confidence_rate"] == pytest.approx(0.5)
    assert result["accuracy"] == pytest.approx(0.5)
    assert result["confidence"] == pytest.approx(0.7)
    # The malformed attempt is scored as a fully confident error, not silence.
    assert result["calibrated_score"] == pytest.approx((0.96 - 0.36 - 1.0) / 4)


def test_reliability_bins_answer_the_plain_language_confidence_question():
    rows = [
        record(verdict="correct", confidence=0.89),
        record(verdict="incorrect", confidence=0.91),
        record(verdict="incorrect", confidence=None, parse_failure=True),
    ]

    result = MODULE.reliability_rows(rows)

    assert len(result) == 1
    assert result[0]["confidence_bin"] == pytest.approx(0.9)
    assert result[0]["responses"] == 2
    assert result[0]["accuracy"] == pytest.approx(0.5)
    assert result[0]["mean_stated_confidence"] == pytest.approx(0.9)


def test_cell_improvement_means_closer_to_zero_not_more_underconfident(monkeypatch):
    monkeypatch.setattr(MODULE, "MODELS", ("m",))
    monkeypatch.setattr(MODULE, "BENCHMARKS", ("b",))
    cells = [
        {
            "model": "m", "benchmark": "b", "arm": "control",
            "answer_rate": 1.0, "usable_confidence_rate": 1.0,
            "accuracy": 0.80, "confidence": 0.75,
            "confidence_gap": -0.05, "calibrated_score": 0.50,
            "high_confidence_error_90_rate": 0.0, "parse_failure_rate": 0.0,
        },
        {
            "model": "m", "benchmark": "b", "arm": "quad_score_only",
            "answer_rate": 1.0, "usable_confidence_rate": 1.0,
            "accuracy": 0.80, "confidence": 0.50,
            "confidence_gap": -0.30, "calibrated_score": 0.30,
            "high_confidence_error_90_rate": 0.0, "parse_failure_rate": 0.0,
        },
    ]

    arms, change = MODULE.paired_summary(cells)

    assert arms[0]["mean_absolute_confidence_gap"] == pytest.approx(0.05)
    assert arms[1]["mean_absolute_confidence_gap"] == pytest.approx(0.30)
    assert change["mean_absolute_confidence_gap"] == pytest.approx(0.25)
    assert change["cells_gap_improved"] == 0
    assert change["control_cells_overconfident"] == 0
    assert change["treatment_cells_overconfident"] == 0
