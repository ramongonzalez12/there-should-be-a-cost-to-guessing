"""Integrity checks for the same-checkpoint prompt factorial outputs."""

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def load_cells():
    """Read numeric cell output into plain dictionaries for audit assertions."""
    with (PROCESSED / "prompt_threshold_factorial_cells.csv").open(
            encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_factorial_contains_every_frozen_checkpoint_cell():
    cells = load_cells()
    identities = {
        (int(row["seed"]), int(row["dose"]), row["training_arm"])
        for row in cells
    }
    expected = {
        (seed, dose, arm)
        for seed in (2, 4, 5)
        for dose in (125, 250, 300, 375, 500)
        for arm in ("quadratic", "quad_cost_0.09")
    }
    assert identities == expected
    assert all(int(row["n"]) == 100 for row in cells)


def test_prompt_and_gate_marginals_add_to_total_architecture_change():
    for row in load_cells():
        assert float(row["utility_change"]) == pytest.approx(
            float(row["prompt_only_utility_change"])
            + float(row["gate_marginal_utility_change"])
        )
        assert float(row["wrong_change"]) == pytest.approx(
            float(row["prompt_only_wrong_change"])
            + float(row["gate_marginal_wrong_change"])
        )
        # The external threshold can only remove native answers.
        assert (float(row["separated_coverage"])
                <= float(row["confidence_native_coverage"]) + 1e-12)


def test_primary_summary_reaggregates_from_step_500_cells():
    cells = [row for row in load_cells() if int(row["dose"]) == 500]
    summary = json.loads(
        (PROCESSED / "prompt_threshold_factorial_summary.json").read_text()
    )
    assert len(cells) == 6
    for field in ("utility_change", "wrong_change", "coverage_change",
                  "prompt_only_utility_change", "prompt_only_wrong_change",
                  "gate_marginal_utility_change", "gate_marginal_wrong_change"):
        observed = sum(float(row[field]) for row in cells) / len(cells)
        assert summary["headline"][field] == pytest.approx(observed)
    assert summary["headline"]["embedded_format_failures"] == 12
    assert summary["headline"]["separated_format_failures"] == 0
    sensitivity = summary["well_formatted_pair_sensitivity"]
    assert sensitivity["paired_item_checkpoint_responses"] == 588
    assert sensitivity["status"] == "post_result_mechanism_diagnostic_not_primary"


def test_manifest_records_conservative_invalid_handling_and_no_spend():
    manifest = json.loads(
        (PROCESSED / "prompt_threshold_factorial_manifest.json").read_text()
    )
    assert manifest["relevant_responses"] == 6_000
    assert manifest["malformed_attempts_forced_wrong"] == 62
    assert manifest["cost_usd"] == 0.0
    assert len(manifest["source_sha256"]) == 15
