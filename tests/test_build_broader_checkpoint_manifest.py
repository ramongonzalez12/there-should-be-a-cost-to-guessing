"""The broader manifest cannot silently omit or duplicate a training seed."""

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_broader_checkpoint_manifest",
    pathlib.Path(__file__).parents[1]
    / "scripts"
    / "build_broader_checkpoint_manifest.py",
)
assert _SPEC and _SPEC.loader
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


def seed0():
    result = {"base": {"arm": "base", "dose": 0, "sampler_path": None}}
    for arm in builder.SEED0_ARMS:
        result[arm] = {"arm": arm, "dose": 500, "sampler_path": f"tinker://0/{arm}"}
    return result


def replication(seed):
    return {
        arm: {
            "arm": arm,
            "dose": 500,
            "training_seed": seed,
            "sampler_path": f"tinker://{seed}/{arm}",
        }
        for arm in builder.REPLICATION_ARMS
    }


def test_builds_exact_eighteen_checkpoint_matrix():
    result = builder.build(seed0(), [replication(seed) for seed in (1, 2, 4, 5)])

    assert len(result) == 18
    assert result["seed0-binary"]["training_seed"] == 0
    assert result["seed2-quadratic"]["training_seed"] == 2
    assert result["seed0-quad_cost_0.16"]["arm"] == "quad_cost_0.16"


def test_rejects_wrong_or_duplicate_seed_set():
    with pytest.raises(ValueError, match="expected replication seeds"):
        builder.build(seed0(), [replication(seed) for seed in (1, 1, 4, 5)])


def test_rejects_a_nonterminal_dose():
    bad = replication(2)
    bad["quadratic"]["dose"] = 375
    with pytest.raises(ValueError, match="dose 500"):
        builder.build(seed0(), [replication(1), bad, replication(4), replication(5)])
