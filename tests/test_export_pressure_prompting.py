"""Tests for the crossed social-pressure prompt export."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_pressure_prompting.py"
SPEC = importlib.util.spec_from_file_location("export_pressure_prompting", SCRIPT)
export = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(export)


def arm(reward, seed, pressure_arm, adoption):
    """Build one minimal summary arm with the fields the exporter audits."""
    return {
        "reward_rule": reward,
        "step": 0 if reward == "base" else 125,
        "seed": seed,
        "n": 10,
        "adoption_rate": adoption,
        "second_turn_invalid_rate": 0,
    }


def write_summary(path, offset):
    rows = {}
    for reward, seeds in {
        "base": [None], "binary": [0, 1], "quadratic": [0, 1],
        "quad_cost": [0, 1],
    }.items():
        for seed in seeds:
            checkpoint = "base" if reward == "base" else f"{reward}-{seed}"
            wrong = offset + {"base": .10, "binary": .20, "quadratic": .35,
                              "quad_cost": .30}[reward]
            right = offset + {"base": .70, "binary": .75, "quadratic": .85,
                              "quad_cost": .80}[reward]
            rows[f"{checkpoint}|wrong"] = arm(reward, seed, "wrong", wrong)
            rows[f"{checkpoint}|right"] = arm(reward, seed, "right", right)
    path.write_text(json.dumps({"by_checkpoint_arm": rows}), encoding="utf-8")


def test_crossed_export_preserves_both_pressure_directions(tmp_path):
    source = tmp_path / "summary.json"
    write_summary(source, .01)
    records = []
    for condition in export.PROMPT_LABELS:
        records.extend(export.read_condition(condition, source))
    levels = export.build_levels(records)
    contrasts = export.build_contrasts(levels)

    assert len(levels) == 16
    assert len(contrasts) == 4
    assert contrasts[0]["delta_wrong_adoption"] == "0.150000"
    assert contrasts[0]["delta_right_adoption"] == "0.100000"
    assert contrasts[0]["delta_pressure_discernment"] == "-0.050000"


def test_condition_rejects_invalid_second_turn(tmp_path):
    source = tmp_path / "summary.json"
    write_summary(source, 0)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["by_checkpoint_arm"]["base|wrong"]["second_turn_invalid_rate"] = .1
    source.write_text(json.dumps(payload), encoding="utf-8")

    try:
        export.read_condition("neutral", source)
    except ValueError as exc:
        assert "invalid second turns" in str(exc)
    else:
        raise AssertionError("invalid generations must fail closed")


def test_spend_export_requires_complete_capped_runs(tmp_path):
    for index, run in enumerate(export.SPEND_RUNS):
        directory = tmp_path / run
        directory.mkdir()
        (directory / "spend.json").write_text(json.dumps({
            "cap_usd": .50,
            "spent_usd": .10 + index / 100,
            "rows": index + 1,
            "status": "COMPLETE",
        }), encoding="utf-8")

    rows = export.build_spend(tmp_path)
    assert len(rows) == 8
    assert round(sum(float(row["conservative_spend_usd"]) for row in rows), 6) == 1.08
    assert all(row["status"] == "COMPLETE" for row in rows)
