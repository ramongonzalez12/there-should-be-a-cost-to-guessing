import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_domain_checkpoint_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_domain_checkpoint_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _arm(root: Path, domain: str, objective: str, seed: int, status: str) -> None:
    path = root / domain / f"{objective}_seed{seed}" / "arm.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "checkpoint": ({"sampler_path": f"tinker://{domain}/{objective}/{seed}"}
                       if status == "COMPLETE" else None),
        "health_gate": {"reasons": ["invalid_rate"]},
    }
    path.write_text(json.dumps(payload))


def test_manifest_admits_only_complete_matched_pairs(tmp_path):
    _arm(tmp_path, "medicine", "binary", 1, "COMPLETE")
    _arm(tmp_path, "medicine", "quadratic", 1, "COMPLETE")
    _arm(tmp_path, "math", "binary", 1, "COMPLETE")
    _arm(tmp_path, "math", "quadratic", 1, "FAILED_HEALTH_GATE")

    result = MODULE.build(
        model="model", family_label="family", seed_roots={1: tmp_path},
        domains=["medicine", "math"],
    )

    assert result["matched_pairs_admitted"] == 1
    assert result["planned_pairs"] == 2
    labels = set(result["checkpoints"])
    assert "family_medicine_binary_seed1" in labels
    assert "family_math_binary_seed1" not in labels
    failed = next(row for row in result["training_census"] if row["training_domain"] == "math")
    assert failed["matched_pair_admitted"] is False
    assert failed["arms"][1]["status"] == "FAILED_HEALTH_GATE"

