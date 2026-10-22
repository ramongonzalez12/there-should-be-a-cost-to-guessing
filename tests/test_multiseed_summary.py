"""Tests for the deterministic final-test analysis across promoted seeds."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_tinker_seeds.py"
SPEC = importlib.util.spec_from_file_location("summarize_tinker_seeds", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

ITEM_HASH = "a" * 64


def _write_matrix(
    root: Path,
    *,
    seed: int,
    quadratic_scores: tuple[float, float],
) -> Path:
    """Create a complete 2-item by 16-cell matrix with controlled primary effects."""
    directory = root / f"seed{seed}"
    directory.mkdir()
    checkpoints = ["base", "binary", "quadratic", "quad_cost"]
    prompts = ["neutral", "binary", "quadratic", "quad_cost"]
    rows = []
    for item_index, item_id in enumerate(("item-1", "item-2")):
        for checkpoint in checkpoints:
            for prompt in prompts:
                # Only the neutral binary-versus-quadratic cells affect the primary
                # result. The other cells still exist so matrix completeness is tested.
                score = 0.0
                outcome = "INCORRECT"
                if checkpoint == "quadratic":
                    score = quadratic_scores[item_index]
                    outcome = "CORRECT"
                elif checkpoint in {"base", "quad_cost"}:
                    score = 0.1
                rows.append(
                    {
                        "benchmark": "fixture",
                        "item_id": item_id,
                        "checkpoint": checkpoint,
                        "prompt_condition": prompt,
                        "repetition": 0,
                        "outcome": outcome,
                        "scores": {
                            "binary": float(outcome == "CORRECT"),
                            "quadratic": score,
                            "quad_cost": score - 0.09,
                        },
                    }
                )
    responses_path = directory / "responses.jsonl"
    responses_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    workload = {
        "status": "READY",
        "items": 2,
        "items_sha256": ITEM_HASH,
        "checkpoints": checkpoints,
        "prompt_conditions": prompts,
        "posthoc_score_rules": ["binary", "quadratic", "quad_cost"],
        "repetitions": 1,
        "generation_cells_per_item": 16,
        "generation_calls": 32,
        "max_completion_tokens": 2048,
    }
    manifest = {
        "status": "COMPLETE",
        "split_label": "final",
        "item_offset_per_benchmark": 20,
        "seed": seed,
        "model": "fixture-model",
        "renderer": "fixture-renderer",
        "assertion_cost": 0.09,
        "temperature": 0.0,
        "max_tokens": 64,
        "prompt_hashes": {prompt: prompt for prompt in prompts},
        "checkpoint_paths": {checkpoint: checkpoint for checkpoint in checkpoints},
        "workload": workload,
    }
    (directory / "evaluation.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (directory / "summary.json").write_text("{}\n", encoding="utf-8")
    return directory


def _summarize(tmp_path: Path, matrices: list[tuple[str, Path]]):
    protocol = tmp_path / "protocol.md"
    protocol.write_text("# Frozen before generation\n", encoding="utf-8")
    return MODULE.summarize(
        matrices,
        expected_items_sha256=ITEM_HASH,
        expected_offset=20,
        bootstrap_samples=200,
        minimum_combined_quadratic=0.0,
        minimum_seed_quadratic=0.0,
        minimum_combined_accuracy=-0.03,
        minimum_seed_accuracy=-0.05,
        maximum_invalid_change=0.01,
        protocol_path=protocol,
    )


def test_two_positive_promoted_seeds_pass(tmp_path):
    seed0 = _write_matrix(tmp_path, seed=0, quadratic_scores=(0.2, 0.4))
    seed1 = _write_matrix(tmp_path, seed=1, quadratic_scores=(0.1, 0.3))

    result = _summarize(tmp_path, [("seed0", seed0), ("seed1", seed1)])

    assert result["verdict"] == "PASS"
    assert result["combined"]["quadratic_score"]["estimate"] == pytest.approx(0.25)
    assert result["primary"]["paired_training_seeds"] == [0, 1]
    assert result["primary"]["paired_items"] == 2
    assert all(gate["passed"] for gate in result["gates"].values())


def test_direction_reversal_fails_even_when_combined_effect_is_positive(tmp_path):
    seed0 = _write_matrix(tmp_path, seed=0, quadratic_scores=(0.5, 0.5))
    seed1 = _write_matrix(tmp_path, seed=1, quadratic_scores=(-0.1, -0.1))

    result = _summarize(tmp_path, [("seed0", seed0), ("seed1", seed1)])

    assert result["combined"]["quadratic_score"]["estimate"] > 0
    assert result["verdict"] == "FAIL"
    assert not result["gates"]["every_seed_quadratic_positive"]["passed"]


def test_final_item_hash_mismatch_fails_closed(tmp_path):
    seed0 = _write_matrix(tmp_path, seed=0, quadratic_scores=(0.2, 0.4))
    seed1 = _write_matrix(tmp_path, seed=1, quadratic_scores=(0.1, 0.3))
    manifest_path = seed1 / "evaluation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workload"]["items_sha256"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="different final item set"):
        _summarize(tmp_path, [("seed0", seed0), ("seed1", seed1)])


def test_incomplete_crossed_item_fails_closed(tmp_path):
    seed0 = _write_matrix(tmp_path, seed=0, quadratic_scores=(0.2, 0.4))
    seed1 = _write_matrix(tmp_path, seed=1, quadratic_scores=(0.1, 0.3))
    responses_path = seed1 / "responses.jsonl"
    rows = responses_path.read_text(encoding="utf-8").splitlines()
    responses_path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
    manifest_path = seed1 / "evaluation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workload"]["generation_calls"] = 31
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete crossed item"):
        _summarize(tmp_path, [("seed0", seed0), ("seed1", seed1)])
