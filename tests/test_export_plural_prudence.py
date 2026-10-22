"""Tests for the plural-prudence result exporter."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_plural_prudence", ROOT / "scripts" / "export_plural_prudence.py"
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def _cell(checkpoint, objective, seed, framing, offset):
    return {
        "checkpoint": checkpoint,
        "training_objective": objective,
        "training_seed": seed,
        "framing": framing,
        "prudence": {metric: offset for metric in exporter.TRACK_METRICS["prudence"]},
        "evidence": {metric: offset for metric in exporter.TRACK_METRICS["evidence"]},
        "plural": {metric: offset for metric in exporter.TRACK_METRICS["plural"]},
        "integrity": {metric: offset for metric in exporter.TRACK_METRICS["integrity"]},
        "goal": {metric: offset for metric in exporter.TRACK_METRICS["goal"]},
    }


def test_export_separates_training_and_prompt_contrasts(tmp_path):
    cells = {}
    for seed in (0, 1, 2, 4, 5):
        for objective, treatment_offset in (
            ("binary", 0.1), ("quadratic", 0.2), ("quad_cost_0.09", 0.3)
        ):
            for framing, prompt_offset in (
                ("neutral", 0.0), ("plural", 0.01),
                ("prudence", 0.02), ("combined", 0.03),
            ):
                checkpoint = f"seed{seed}-{objective}"
                cell = _cell(
                    checkpoint, objective, seed, framing, treatment_offset + prompt_offset
                )
                cells[f"{checkpoint}|{framing}"] = cell
    base = _cell("base", "base", None, "neutral", 0.0)
    cells["base|neutral"] = base
    for framing, offset in (("plural", 0.01), ("prudence", 0.02), ("combined", 0.03)):
        cells[f"base|{framing}"] = _cell("base", "base", None, framing, offset)
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"by_cell": cells}), encoding="utf-8")

    levels, contrasts, prompts = exporter.export(summary)

    assert len(levels) == 64
    assert len(contrasts) == 40
    assert len(prompts) == 48
    quadratic = next(
        row for row in contrasts
        if row["training_seed"] == "0"
        and row["framing"] == "neutral"
        and row["treatment_objective"] == "quadratic"
    )
    assert round(quadratic["prudence_brier_loss_change"], 6) == 0.1
    combined = next(
        row for row in prompts
        if row["checkpoint"] == "seed0-binary" and row["framing"] == "combined"
    )
    assert round(combined["goal_goal_dogmatism_rate_change"], 6) == 0.03
