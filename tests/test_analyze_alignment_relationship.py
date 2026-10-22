"""Checks for the checkpoint-level calibration and alignment analysis."""

import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_alignment_relationship.py"
SPEC = importlib.util.spec_from_file_location("alignment_relationship", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_rank_helpers_handle_ties_and_direction():
    assert MODULE.average_ranks([10, 20, 20, 40]) == [1.0, 2.5, 2.5, 4.0]
    assert MODULE.spearman([1, 2, 3], [3, 2, 1]) == -1.0


def test_committed_grid_is_complete_and_joined():
    checkpoints = MODULE.build_checkpoint_rows()

    assert len(checkpoints) == 100
    assert {row["objective"] for row in checkpoints} == set(MODULE.OBJECTIVES)
    assert all(0 <= row["constraint_adherence"] <= 1 for row in checkpoints)
    assert all(-1 <= row["pressure_discernment"] <= 1 for row in checkpoints)


def test_summary_uses_paired_alignment_endpoints(tmp_path):
    summary = MODULE.summarize(MODULE.build_checkpoint_rows())
    by_indicator = {row["indicator"]: row for row in summary}

    assert set(by_indicator) == {
        "Constraint adherence",
        "Resistance to wrong pushback",
        "Appropriate updating",
        "Pressure discernment",
    }
    assert all(row["n_checkpoints"] == "100" for row in summary)

    # The paired pressure endpoint must remain the difference between accepting
    # a correct correction and accepting an incorrect one.  These regression
    # values also catch accidental changes to the within-objective quartiles.
    discernment = by_indicator["Pressure discernment"]
    assert float(discernment["within_objective_rank_correlation"]) == pytest.approx(0.079518)
    assert float(discernment["quartile_change"]) == pytest.approx(0.010040)

    output = tmp_path / "summary.csv"
    MODULE.write_summary(summary, output)
    with output.open(newline="", encoding="utf-8") as handle:
        persisted = list(csv.DictReader(handle))
    assert persisted == summary
