#!/usr/bin/env python3
"""Build a checkpoint manifest for evaluate_tinker_grid.py from a run family.

One command replaces the ad-hoc snippets that assembled the seed-1 and seed-2
dense-eval manifests by hand: scan every arm directory under a family root,
collect each checkpoint's sampler path (rescued permanent paths first, then
milestone files), and write the labels -> sampler-path JSON the evaluator
consumes. The base model is always included as label "base".

Usage:
  python3 scripts/build_dense_eval_manifest.py \
      --runs runs/finetune/qwen_balanced_order_v1 \
      --out  runs/finetune/balanced_dense_eval_v1/checkpoints.json

Arm directories are recognised by containing checkpoints.jsonl. The arm name
in each label is the reward rule recorded in arm.json, plus the arm dir's
seed when the family mixes seeds (label format: reward[.seedN]@step).
"""
import argparse
import json
import pathlib


def sampler_paths_for_arm(arm_dir: pathlib.Path) -> dict[int, str]:
    """step -> sampler path, preferring rescued permanent paths."""
    paths: dict[int, str] = {}
    # milestone files live one level up, keyed by arm name within
    rescued = arm_dir / "checkpoints_rescued.jsonl"
    if rescued.exists():
        for line in rescued.read_text().splitlines():
            d = json.loads(line)
            sp = (d.get("permanent_sampler_path") or d.get("sampler_path")
                  or next((v for v in d.values()
                           if isinstance(v, str) and "sampler_weights" in v), None))
            if sp:
                paths[int(d["step"])] = sp
    # fall back to the training-time checkpoint records for anything unrescued
    plain = arm_dir / "checkpoints.jsonl"
    if plain.exists():
        for line in plain.read_text().splitlines():
            d = json.loads(line)
            step = int(d["step"])
            if step not in paths:
                sp = d.get("sampler_path") or next(
                    (v for v in d.values()
                     if isinstance(v, str) and "sampler_weights" in v), None)
                if sp:
                    paths[step] = sp
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=pathlib.Path, required=True,
                        help="family root containing arm directories")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--seed", type=int, default=None,
                        help="keep only arms trained with this seed, and label "
                             "them by plain reward name; evaluate_tinker_grid "
                             "only accepts the standard reward-arm labels, so "
                             "multi-seed families are evaluated one seed at a "
                             "time")
    args = parser.parse_args()

    arm_dirs = sorted(d for d in args.runs.iterdir()
                      if d.is_dir() and (d / "checkpoints.jsonl").exists())
    if not arm_dirs:
        raise SystemExit(f"no arm directories with checkpoints.jsonl under {args.runs}")

    manifest = {"base": {"arm": "base", "dose": 0.0, "label": "base",
                         "sampler_path": None}}
    seeds = set()
    arms = []
    for arm_dir in arm_dirs:
        meta = json.loads((arm_dir / "arm.json").read_text())
        if args.seed is not None and meta.get("seed") != args.seed:
            continue
        arms.append((arm_dir, meta))
        seeds.add(meta.get("seed"))
    if not arms:
        raise SystemExit(f"no arms match seed {args.seed} under {args.runs}")
    multi_seed = len(seeds) > 1

    for arm_dir, meta in arms:
        reward = meta.get("reward") or "profile"
        seed = meta.get("seed")
        arm_label = f"{reward}.seed{seed}" if multi_seed else reward
        for step, sp in sorted(sampler_paths_for_arm(arm_dir).items()):
            label = f"{arm_label}@{step}"
            manifest[label] = {"arm": arm_label, "dose": float(step),
                               "label": label, "sampler_path": sp}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=1))
    per_arm = {}
    for v in manifest.values():
        per_arm[v["arm"]] = per_arm.get(v["arm"], 0) + 1
    print(f"wrote {args.out}: {per_arm}")


if __name__ == "__main__":
    main()
