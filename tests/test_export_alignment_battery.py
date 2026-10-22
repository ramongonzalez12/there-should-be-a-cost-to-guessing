"""Tests for the matched alignment battery exporter."""

import importlib.util
import json
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "export_alignment_battery",
    pathlib.Path(__file__).parents[1] / "scripts" / "export_alignment_battery.py",
)
assert _SPEC and _SPEC.loader
exporter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(exporter)


def _cell(arm, seed, bad, unsupported):
    return {
        "arm": arm,
        "training_seed": seed,
        "decision": {"n": 10, "parse_rate": 1, "accuracy": 1-bad, "execution_rate": 1, "wrong_execution_rate": bad, "high_confidence_wrong_execution_rate": bad, "threshold_consistency": 1},
        "scheme": {"n": 4, "parse_rate": 1, "prohibited_action_rate": 0, "prohibited_conflict_rate": 0, "prohibited_no_conflict_rate": 0, "concealment_given_prohibited": None, "benign_control_success": 1},
        "evidence": {"unsupported_n": 5, "adopted_unsupported_wrong_rate": unsupported, "verified_n": 5, "adopted_verified_correct_rate": 1},
    }


def test_exporter_pairs_each_treatment_with_binary_from_the_same_seed(tmp_path):
    cells = {"base": _cell("base", None, .5, .5)}
    for seed in (0, 1, 2, 4, 5):
        cells[f"b{seed}"] = _cell("binary", seed, .5, .4)
        cells[f"q{seed}"] = _cell("quadratic", seed, .4, .6)
        cells[f"c{seed}"] = _cell("quad_cost_0.09", seed, .45, .5)
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"by_checkpoint": cells}), encoding="utf-8")
    levels, contrasts = exporter.export(path)
    assert len(levels) == 16
    assert len(contrasts) == 10
    q0 = next(r for r in contrasts if r["training_seed"] == "0" and r["treatment_objective"] == "quadratic")
    assert round(q0["high_confidence_wrong_execution_change"], 6) == -0.1
    assert round(q0["unsupported_wrong_adoption_change"], 6) == 0.2
