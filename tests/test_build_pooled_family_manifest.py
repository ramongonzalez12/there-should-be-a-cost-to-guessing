from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "build_pooled_family_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_pooled_family_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _arm(path: pathlib.Path, status: str = "COMPLETE") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "status": status,
            "checkpoint": (
                {"sampler_path": f"tinker://{path.parent.name}"}
                if status == "COMPLETE"
                else None
            ),
        }),
        encoding="utf-8",
    )


def test_builder_keeps_failed_seed_in_denominator(tmp_path):
    arms = tmp_path / "arms"
    for objective in ("binary", "quadratic"):
        _arm(arms / f"{objective}_seed0" / "arm.json")
    _arm(arms / "binary_seed1" / "arm.json", "FAILED_HEALTH_GATE")

    result = MODULE.build(
        model="openai/gpt-oss-20b",
        family_label="gpt_oss_20b",
        arm_root=arms,
        seeds=[0, 1],
        control_sampler="tinker://shared-format",
    )

    assert result["planned_pairs"] == 2
    assert result["matched_pairs_admitted"] == 1
    assert result["checkpoints"]["control"]["sampler_path"] == "tinker://shared-format"
    assert "pooled_binary_seed0" in result["checkpoints"]
    assert "pooled_binary_seed1" not in result["checkpoints"]
