"""Tests for the expanded deterministic prompt experiment export."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_prompt_estimation.py"
SPEC = importlib.util.spec_from_file_location("export_prompt_estimation", SCRIPT)
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = exporter
SPEC.loader.exec_module(exporter)


def row(verdict, confidence, *, parse_failure=0, cost=0.01):
    return {"verdict": verdict, "confidence": confidence,
            "parse_failure": parse_failure, "cost_usd": cost}


def test_cell_metrics_keep_answered_denominators_aligned():
    rows = [
        row("CORRECT", 0.8),
        row("INCORRECT", 0.6),
        row("NOT_ATTEMPTED", 0.1),
        row("INCORRECT", None, parse_failure=1),
    ]
    result = exporter.summarize_cell(rows)

    assert result["accuracy"] == 0.25
    assert result["answered_rate"] == 0.75
    assert result["accuracy_when_answered"] == 1 / 3
    assert result["confidence_when_answered"] == (0.8 + 0.6 + 0.5) / 3
    assert result["confidence_gap"] == (0.8 + 0.6 + 0.5) / 3 - 1 / 3
    # Parse failures receive -1, never the zero awarded to abstention.
    assert result["confidence_calibrated_score"] == pytest.approx(
        (0.87 - 0.45 + 0 - 1) / 4)


def make_db(path, *, include_second_contract=True):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE answers (
        model TEXT, benchmark TEXT, item_id TEXT, contract TEXT, error TEXT, verdict TEXT,
        confidence REAL, parse_failure INTEGER, cost_usd REAL
    )""")
    contracts = ["control", "treatment"] if include_second_contract else ["control"]
    for contract in contracts:
        con.execute("INSERT INTO answers VALUES (?, ?, ?, ?, NULL, ?, ?, 0, ?)",
                    ("example/model", "bench", "bench:1", contract,
                     "CORRECT", 0.7, 0.01))
    con.commit()
    con.close()


def test_export_requires_every_planned_cell(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "RUNS", str(tmp_path))
    monkeypatch.setattr(exporter, "BENCHMARKS", ("bench",))
    monkeypatch.setattr(exporter, "CONTRACTS", ("control", "treatment"))
    cohort = exporter.Cohort("example/model", "run.db", 1, "off")
    make_db(tmp_path / "run.db")

    rows, metadata = exporter.export((cohort,))

    assert len(rows) == 2
    assert metadata["responses"] == 2
    assert metadata["generation_cost_usd"] == 0.02


def test_export_fails_closed_on_missing_cell(tmp_path, monkeypatch):
    monkeypatch.setattr(exporter, "RUNS", str(tmp_path))
    monkeypatch.setattr(exporter, "BENCHMARKS", ("bench",))
    monkeypatch.setattr(exporter, "CONTRACTS", ("control", "treatment"))
    cohort = exporter.Cohort("example/model", "run.db", 1, "off")
    make_db(tmp_path / "run.db", include_second_contract=False)

    try:
        exporter.export((cohort,))
    except ValueError as exc:
        assert "missing cells" in str(exc)
    else:
        raise AssertionError("an incomplete paid run must not be published")
