"""Replication analysis keeps failed runs visible and uses matching noise units."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    """Load a repository script as a module without making scripts a package."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analysis = _load_script("analyze_seed_replication")
verdict = _load_script("replication_verdict")


def test_run_record_retains_a_technical_gate_without_an_evaluation(tmp_path):
    """A failed gate is an observed run, not a seed that disappears."""
    run = tmp_path / "qwen_seed_replication_seed3"
    run.mkdir()
    (run / "program.json").write_text(
        json.dumps(
            {
                "seed": 3,
                "status": "STARTED",
                "stages": {
                    "125": {"status": "BLOCKED_TECHNICAL_GATE"},
                },
            }
        ),
        encoding="utf-8",
    )

    record = analysis.replication_run_record(run, {})

    assert record["analysis_included"] is False
    assert record["exclusion_reason"] == "no_completed_evaluation"
    assert record["stage_statuses"] == {"125": "BLOCKED_TECHNICAL_GATE"}


def test_discovery_includes_started_and_complete_programs(tmp_path):
    """Run discovery must not preselect only successful seeds."""
    for seed, status in ((2, "STARTED"), (4, "COMPLETE")):
        run = tmp_path / f"qwen_seed_replication_seed{seed}"
        run.mkdir()
        (run / "program.json").write_text(
            json.dumps({"seed": seed, "status": status}), encoding="utf-8"
        )

    assert analysis.discover_runs(tmp_path) == {
        2: tmp_path / "qwen_seed_replication_seed2",
        4: tmp_path / "qwen_seed_replication_seed4",
    }


def test_accuracy_uses_the_accuracy_noise_floor():
    """Accuracy changes cannot be compared with a binary-score range."""
    rows = []
    for seed in (0, 1):
        rows.extend(
            [
                {
                    "seed": str(seed),
                    "objective": "base",
                    "step": "0",
                    "accuracy": "0.50",
                    "score_quadratic": "0.20",
                    "overconfidence": "0.20",
                },
                {
                    "seed": str(seed),
                    "objective": "binary",
                    "step": "125",
                    "accuracy": "0.60",
                    "score_quadratic": "0.30",
                    "overconfidence": "0.10",
                },
            ]
        )
    floor = {
        "accuracy": {"range": 0.02},
        "quadratic": {"range": 0.02},
        # This deliberately large, wrong-unit range would mask the 0.10
        # accuracy effect if the former bug selected it.
        "binary": {"range": 1.0},
    }

    result = verdict.report(rows, dose=125, floor=floor)
    accuracy = result["objectives"]["binary"]["measures"]["plain accuracy"]

    assert accuracy["within_measurement_band"] == []


def test_report_seed_list_is_scoped_to_the_requested_dose():
    """A partial seed at an earlier dose must not enter a later-dose header."""
    rows = [
        {
            "seed": "2",
            "objective": "base",
            "step": "0",
            "accuracy": "0.50",
        },
        {
            "seed": "2",
            "objective": "binary",
            "step": "125",
            "accuracy": "0.55",
        },
        {
            "seed": "4",
            "objective": "base",
            "step": "0",
            "accuracy": "0.50",
        },
        {
            "seed": "4",
            "objective": "binary",
            "step": "500",
            "accuracy": "0.60",
        },
    ]

    result = verdict.report(rows, dose=500, floor=None)

    assert result["seeds"] == [4]
    assert result["varied_curriculum_seeds"] == [4]


def test_render_names_runs_excluded_from_the_numeric_verdict():
    """The human-readable output carries the same failed-run inventory."""
    result = {
        "dose": 125,
        "seeds": [1, 4, 5],
        "fixed_curriculum_seeds": [1],
        "varied_curriculum_seeds": [4, 5],
        "run_inventory": {
            "3": {
                "status": "STARTED",
                "analysis_included": False,
                "exclusion_reason": "no_completed_evaluation",
                "doses": [],
                "stage_statuses": {"125": "BLOCKED_TECHNICAL_GATE"},
            }
        },
        "objectives": {},
        "contrasts": {},
    }

    text = verdict.render(result)

    assert "seed 3: STARTED" in text
    assert "BLOCKED_TECHNICAL_GATE" in text
    assert "no numeric row at 125 steps" in text


def test_render_flags_a_partial_program_even_when_the_dose_is_available():
    """A partial run may contribute a dose without being called complete."""
    result = {
        "dose": 125,
        "seeds": [2],
        "fixed_curriculum_seeds": [],
        "varied_curriculum_seeds": [2],
        "run_inventory": {
            "2": {
                "status": "STARTED",
                "analysis_included": True,
                "exclusion_reason": None,
                "doses": [125, 250],
                "stage_statuses": {
                    "125": "COMPLETE",
                    "250": "COMPLETE",
                    "300": "BLOCKED_SPEND_RECONCILIATION",
                },
            }
        },
        "objectives": {},
        "contrasts": {},
    }

    text = verdict.render(result)

    assert "numeric row comes from a nonterminal program" in text
    assert "seed 2: STARTED" in text
    assert "BLOCKED_SPEND_RECONCILIATION" in text
