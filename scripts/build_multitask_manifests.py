#!/usr/bin/env python3
"""Build explicit checkpoint censuses for pooled and subject-specific comparisons.

Only complete binary/quadratic pairs are admitted. Failed arms remain in the
exclusion audit so downstream summaries cannot silently change the denominator.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone

MODEL = "Qwen/Qwen3-8B"
DOMAINS = ("medicine", "math", "ethics")


def _arm(path: pathlib.Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _sampler(arm: dict[str, object]) -> str | None:
    checkpoint = arm.get("checkpoint")
    return checkpoint.get("sampler_path") if isinstance(checkpoint, dict) else None


def build(
    *,
    seed0_root: pathlib.Path,
    replication_root: pathlib.Path,
    pooled_root: pathlib.Path,
    pooled_seeds: int = 5,
) -> dict[str, object]:
    checkpoints: dict[str, dict[str, object]] = {
        "base": {
            "training_domain": "base",
            "objective": "base",
            "training_seed": None,
            "model_family": MODEL,
            "sampler_path": None,
        }
    }
    exclusions = []

    def consider_pair(
        domain: str, seed: int, root: pathlib.Path, *, nested_domain: bool = True
    ) -> None:
        directory = root / domain if nested_domain else root
        arms = {
            objective: _arm(directory / f"{objective}_seed{seed}" / "arm.json")
            for objective in ("binary", "quadratic")
        }
        admitted = all(
            arm is not None and arm.get("status") == "COMPLETE" and _sampler(arm)
            for arm in arms.values()
        )
        if not admitted:
            exclusions.append(
                {
                    "training_domain": domain,
                    "training_seed": seed,
                    "planned_objectives": ["binary", "quadratic"],
                    "observed_statuses": {
                        objective: None if arm is None else arm.get("status")
                        for objective, arm in arms.items()
                    },
                    "reason": "incomplete_matched_pair",
                }
            )
            return
        for objective, arm in arms.items():
            checkpoints[f"{domain}_{objective}_seed{seed}"] = {
                "training_domain": domain,
                "objective": objective,
                "training_seed": seed,
                "model_family": MODEL,
                "sampler_path": _sampler(arm),
            }

    for domain in DOMAINS:
        consider_pair(domain, 0, seed0_root)
        for seed in (1, 2):
            consider_pair(domain, seed, replication_root)
    for seed in range(pooled_seeds):
        consider_pair("pooled", seed, pooled_root, nested_domain=False)

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "planned_subject_pairs": 9,
        "planned_pooled_pairs": pooled_seeds,
        "admitted_pairs": (len(checkpoints) - 1) // 2,
        "checkpoints": checkpoints,
        "excluded_pairs": exclusions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed0-root", type=pathlib.Path, required=True)
    parser.add_argument("--replication-root", type=pathlib.Path, required=True)
    parser.add_argument("--pooled-root", type=pathlib.Path, required=True)
    parser.add_argument("--pooled-seeds", type=int, default=5)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    payload = build(
        seed0_root=args.seed0_root,
        replication_root=args.replication_root,
        pooled_root=args.pooled_root,
        pooled_seeds=args.pooled_seeds,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "admitted_pairs": payload["admitted_pairs"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
