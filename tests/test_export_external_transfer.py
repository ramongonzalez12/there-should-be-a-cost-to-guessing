from __future__ import annotations

import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "export_external_transfer.py"
SPEC = importlib.util.spec_from_file_location("export_external_transfer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_delta_leaves_undefined_metrics_blank() -> None:
    assert MODULE._delta("", 0.4) == ""
    assert MODULE._delta(None, 0.4) == ""
    assert MODULE._delta(0.3, 0.4) == 0.10000000000000003


def test_level_keeps_family_and_denominator_identity() -> None:
    row = MODULE._level(
        "seed0-quadratic",
        {"training_objective": "quadratic", "training_seed": 0},
        "honesty under pressure",
        "MASK",
        "known_facts",
        {"n": 209, "known_n": 100, "honesty_given_known": 0.7},
    )
    assert row["family"] == "honesty under pressure"
    assert row["n"] == 209
    assert row["known_n"] == 100
    assert row["honesty_given_known"] == 0.7


def test_calibrated_score_field_is_part_of_export_schema() -> None:
    assert "confidence_calibrated_score" in MODULE.LEVEL_FIELDS
    assert "confidence_calibrated_score_change" in MODULE.CONTRAST_FIELDS
