#!/usr/bin/env python3
"""Build a fail-closed census of matched domain-training checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from datetime import datetime, timezone


def _seed_root(value: str) -> tuple[int, pathlib.Path]:
    try:
        seed_text, path = value.split("=", 1)
        return int(seed_text), pathlib.Path(path)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError("--seed-root must look like SEED=PATH") from error


def build(
    *,
    model: str,
    family_label: str,
    seed_roots: dict[int, pathlib.Path],
    domains: list[str],
) -> dict[str, object]:
    checkpoints: dict[str, dict[str, object]] = {
        "base": {
            "training_domain": "base",
            "objective": "base",
            "training_seed": None,
            "model_family": family_label,
            "sampler_path": None,
        }
    }
    census = []
    for seed, root in sorted(seed_roots.items()):
        for domain in domains:
            pair = {}
            arm_rows = []
            for objective in ("binary", "quadratic"):
                path = root / domain / f"{objective}_seed{seed}" / "arm.json"
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
                        "health_gate": (
                            arm.get("stages", [{}])[-1].get("health_gate")
                            if arm.get("stages") else None
                        ) or ({
                            "status": "RED",
                            "reasons": arm.get("health_gate", {}).get("reasons", []),
                        } if arm.get("status") == "FAILED_HEALTH_GATE" else None),
                    }
                    if arm.get("status") == "COMPLETE" and sampler:
                        pair[objective] = sampler
                arm_rows.append(row)
            admitted = set(pair) == {"binary", "quadratic"}
            census.append({
                "training_seed": seed,
                "training_domain": domain,
                "matched_pair_admitted": admitted,
                "arms": arm_rows,
            })
            if admitted:
                for objective, sampler in pair.items():
                    label = f"{family_label}_{domain}_{objective}_seed{seed}"
                    checkpoints[label] = {
                        "training_domain": domain,
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
    parser.add_argument("--seed-root", type=_seed_root, action="append", required=True)
    parser.add_argument("--domains", nargs="+", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    seed_roots = dict(args.seed_root)
    if len(seed_roots) != len(args.seed_root):
        parser.error("each training seed must have exactly one root")
    result = build(
        model=args.model,
        family_label=args.family_label,
        seed_roots=seed_roots,
        domains=args.domains,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

