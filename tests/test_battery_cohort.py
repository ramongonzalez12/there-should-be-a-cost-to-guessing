"""The battery's cohort registry agrees with the tables built from it.

The registry (data/processed/battery_cohort.csv) is the one place that says
which models are in the battery, which of their prompt arms were admitted,
and which database is each arm's source. Three analyzers read it, and the
essay quotes their counts. These tests hold the committed registry and the
committed analyzer outputs to one another, so a registry that drifts from
the tables (or the reverse) fails here rather than on the page.

The first group needs only committed files and runs everywhere. The last
test opens the run databases and is skipped on a checkout without runs/.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from belowzero.cohort import ARM_COLUMNS, load_cohort

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
REGISTRY = PROCESSED / "battery_cohort.csv"

BENCHMARKS = ("mmlu_pro", "gpqa_parity", "medmcqa", "math500", "boolq",
              "truthfulqa_mc", "ethics_hard", "bbq")
ITEMS = 100


def _csv(name: str) -> list[dict]:
    with (PROCESSED / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json(name: str) -> dict:
    return json.loads((PROCESSED / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cohort():
    return load_cohort(REGISTRY)


def test_every_row_is_explained(cohort):
    """An arm is admitted with a source, or it carries a recorded reason."""
    for row in cohort.rows:
        for short in ARM_COLUMNS.values():
            status = row[f"{short}_status"]
            if status == "admitted":
                assert row[f"{short}_db"], (row["model"], short)
                assert int(row[f"{short}_rows"]) >= len(BENCHMARKS) * ITEMS
            else:
                assert status in ("format_failure", "not_run"), (row["model"], short)
                assert not row[f"{short}_db"]
                assert f"{short}:" in row["reason"], (row["model"], short)
        # The baseline arm defines membership: it is always admitted.
        assert row["control_status"] == "admitted"
        # P is exactly "admitted on all three arms".
        expected = all(row[f"{s}_status"] == "admitted" for s in ARM_COLUMNS.values())
        assert (row["in_p"] == "1") == expected, row["model"]


def test_registry_matches_the_battery_rollups(cohort):
    """The notation analyzer's design block and model table read the registry."""
    summary = _json("notation_artifact_summary.json")
    design = summary["rerun_design"]
    assert set(design["control_models"]) == cohort.models
    assert set(design["paired_models"]) == cohort.p
    assert design["models_both_arms_complete"] == len(cohort.p)
    assert set(design["p_models"]) == cohort.p
    models = _csv("notation_rerun_models.csv")
    assert {r["model"] for r in models} == cohort.models
    # A model outside P has no rule-arm level in the table (blank/nan), and
    # every model in P has one.
    for r in models:
        has_rule = r["treatment_accuracy"] not in ("", "nan")
        assert has_rule == (r["model"] in cohort.p), r["model"]


def test_registry_matches_the_warning_comparison(cohort):
    """The warning exporter's battery control reads the same P."""
    manifest = _json("warning_comparison_manifest.json")
    assert set(manifest["warning_models"]) == cohort.p
    assert manifest["responses"]["warning"] == 800 * len(cohort.p)
    levels = _csv("warning_comparison_levels.csv")
    rerun_models = {r["scope"].split(":", 1)[1] for r in levels
                    if r["control"] == "aug27_rerun" and r["scope"].startswith("model:")}
    assert rerun_models == cohort.p
    all_row = next(r for r in levels if r["control"] == "aug27_rerun"
                   and r["scope"] == "all" and r["metric"] == "gap")
    assert int(all_row["cells"]) == len(BENCHMARKS) * len(cohort.p)


def test_registry_matches_the_vintage_table(cohort):
    rows = _csv("model_vintage_calibration.csv")
    assert {r["model"] for r in rows} == cohort.models
    by_model = {r["model"]: r for r in cohort.rows}
    for r in rows:
        assert r["listed_date"] == by_model[r["model"]]["listed_date"]
        assert (r["treatment_complete"] == "1") == (r["model"] in cohort.p), r["model"]


def test_admitted_arms_are_complete_in_their_named_database(cohort):
    """Every admitted arm has the full grid, error-free, in the database the
    registry names. Skipped when the run databases are not on this checkout."""
    if not (ROOT / "runs").exists():
        pytest.skip("run databases are not on this checkout")
    for row in cohort.rows:
        for arm, short in ARM_COLUMNS.items():
            if row[f"{short}_status"] != "admitted":
                continue
            path = ROOT / row[f"{short}_db"]
            if not path.exists() or path.stat().st_size == 0:
                pytest.skip(f"{path.name} is not on this checkout")
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            per_bench = dict(con.execute(
                "SELECT benchmark, COUNT(DISTINCT item_id) FROM answers "
                "WHERE model=? AND contract=? AND error IS NULL GROUP BY benchmark",
                (row["model"], arm)).fetchall())
            rows_total = con.execute(
                "SELECT COUNT(*) FROM answers WHERE model=? AND contract=? "
                "AND error IS NULL", (row["model"], arm)).fetchone()[0]
            con.close()
            for bench in BENCHMARKS:
                assert per_bench.get(bench, 0) >= ITEMS, (row["model"], arm, bench)
            assert rows_total == int(row[f"{short}_rows"]), (row["model"], arm)


def test_superseded_control_requires_an_explicit_validated_replacement(tmp_path, monkeypatch):
    """An unavailable old control is skippable only for a replaced model."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_battery_cohort as builder

    selection = tmp_path / "model_coverage_extension_selection.json"
    selection.write_text(json.dumps({"candidates": [
        {"model": "test/model", "status": "complete", "source": "runs/old.db"}
    ]}))
    (tmp_path / "model_coverage_extension_manifest.json").write_text(json.dumps({
        "selection_sha256": builder.sha256(selection),
        "inputs": [{"model": "test/model", "path": "runs/old.db", "sha256": "unavailable"}],
    }))
    monkeypatch.setattr(builder, "PROCESSED", tmp_path)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="unavailable"):
        builder.coverage_controls()
    assert builder.coverage_controls({"test/model"}) == {}
