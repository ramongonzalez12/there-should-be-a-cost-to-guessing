#!/usr/bin/env python3
"""Build a fail-closed checkpoint census for one pooled-training family.

The control may be a shared format-only checkpoint rather than the untouched
base model. This keeps the behavioral comparison focused on the reward
objective: every binary and quadratic arm starts from that same prerequisite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from datetime import datetime, timezone


def build(
    *,
    model: str,
    family_label: str,
    arm_root: pathlib.Path,
    seeds: list[int],
    control_sampler: str | None,
) -> dict[str, object]:
    checkpoints: dict[str, dict[str, object]] = {
        "control": {
            "training_domain": "shared_format_control" if control_sampler else "base",
            "objective": "base",
            "training_seed": None,
            "model_family": family_label,
            "sampler_path": control_sampler,
        }
    }
    census: list[dict[str, object]] = []
    for seed in seeds:
        pair: dict[str, str] = {}
        arm_rows = []
        for objective in ("binary", "quadratic"):
            path = arm_root / f"{objective}_seed{seed}" / "arm.json"
            if not path.exists():
                row = {"objective": objective, "status": "MISSING", "path": str(path)}
            else:
                arm = json.loads(path.read_text(encoding="utf-8"))
                checkpoint = arm.get("checkpoint") or {}
                sampler = checkpoint.get("sampler_path")
                row = {
                    "objective": objective,
                    "status": arm.get("status"),
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "sampler_path": sampler,
                }
                if arm.get("status") == "COMPLETE" and sampler:
                    pair[objective] = sampler
            arm_rows.append(row)
        admitted = set(pair) == {"binary", "quadratic"}
        census.append(
            {
                "training_seed": seed,
                "matched_pair_admitted": admitted,
                "arms": arm_rows,
            }
        )
        if admitted:
            for objective, sampler in pair.items():
                label = f"pooled_{objective}_seed{seed}"
                checkpoints[label] = {
                    "training_domain": "pooled",
                    "objective": objective,
                    "training_seed": seed,
                    "model_family": family_label,
                    "sampler_path": sampler,
                }
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "family_label": family_label,
        "checkpoints": checkpoints,
        "training_census": census,
        "matched_pairs_admitted": sum(row["matched_pair_admitted"] for row in census),
        "planned_pairs": len(census),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--family-label", required=True)
    parser.add_argument("--arm-root", type=pathlib.Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--control-sampler")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("--seeds must be unique")
    result = build(
        model=args.model,
        family_label=args.family_label,
        arm_root=args.arm_root,
        seeds=args.seeds,
        control_sampler=args.control_sampler,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "matched_pairs_admitted": result["matched_pairs_admitted"],
        "planned_pairs": result["planned_pairs"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
