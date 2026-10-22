"""Focused tests for the external-threshold policy analysis."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "analyze_policy_architecture", ROOT / "scripts" / "analyze_policy_architecture.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def response(item_id, probability, correct, abstained=False):
    """Create the smallest valid stored response needed by policy functions."""
    return {"item_id": item_id, "probability": probability, "correct": correct,
            "abstained": abstained, "formatted": True, "failure": None,
            "outcome": "NOT_ATTEMPTED" if abstained else
                       "CORRECT" if correct else "INCORRECT"}


def test_external_threshold_turns_probability_into_deterministic_action():
    rows = [response("a", 0.29, True), response("b", 0.30, False),
            response("c", 0.80, True)]
    actions = [MODULE.threshold_action(row, 0.30) for row in rows]
    assert actions == [False, True, True]
    metrics = MODULE.decision_metrics(rows, actions, 0.30)
    assert metrics["coverage"] == pytest.approx(2 / 3)
    assert metrics["wrong_per_question"] == pytest.approx(1 / 3)
    # At a 30% break-even threshold, a wrong answer costs 3/7 of a right answer.
    assert metrics["utility_per_question"] == pytest.approx((1 - 3 / 7) / 3)


def test_top_k_matches_coverage_and_prefers_higher_confidence():
    rows = [response("a", 0.60, False), response("b", 0.90, True),
            response("c", 0.80, True), response("d", 0.40, False)]
    actions = MODULE.top_k_actions(rows, 2, seed=0, benchmark="test")
    assert sum(actions) == 2
    assert actions == [False, True, True, False]


def test_top_k_tie_breaking_is_deterministic_and_outcome_blind():
    rows = [response("a", 0.70, False), response("b", 0.70, True),
            response("c", 0.70, False)]
    first = MODULE.top_k_actions(rows, 1, seed=4, benchmark="test")
    rows_with_flipped_outcomes = [{**row, "correct": not row["correct"]} for row in rows]
    second = MODULE.top_k_actions(rows_with_flipped_outcomes, 1, seed=4,
                                  benchmark="test")
    assert first == second
    assert sum(first) == 1


def test_unformatted_attempt_is_forced_wrong_and_through_every_threshold():
    bad = response("a", 0.80, False)
    bad.update({"formatted": False, "failure": "format", "probability": None,
                "outcome": "INVALID"})
    normalized = MODULE.normalize_response(bad)
    assert normalized["_format_failure"] is True
    assert normalized["correct"] is False
    assert normalized["probability"] == 1.0
    assert MODULE.threshold_action(normalized, 0.90) is True


def test_both_historical_explicit_abstention_labels_are_recognized():
    """Schema vocabulary may differ, but both labels describe a native abstention."""
    for label in ("NOT_ATTEMPTED", "ABSTAINED"):
        row = response("a", 0.20, False, abstained=True)
        row["outcome"] = label
        assert MODULE.native_action(row) is False
