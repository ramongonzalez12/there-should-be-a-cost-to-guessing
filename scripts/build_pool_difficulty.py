#!/usr/bin/env python3
"""Estimate per-position difficulty for the frozen 2,000-item training pool.

Why this exists: the confidence-level oscillation (notes/2026-08-27) is forced
by batch-difficulty fluctuation - 95% of GRPO groups are uniform-outcome, and
the balance of all-correct (pushes confidence up) versus all-wrong (pushes it
down) groups tracks whatever difficulty the frozen order serves next. The
`balanced` item-order mode in train_grpo.py neutralises that forcing by giving
every batch the same expected difficulty, and it needs this table to do it.

Difficulty = pass rate over the logged training rollouts of seeds 0, 1 and 2
(quadratic arms; each item was sampled 8 times per run it appeared in, so up
to 24 samples per item). Keyed by POOL POSITION, not item_id, because the
pool's one duplicated id (train:hellaswag:34062 at two positions, two
different questions) would make an id-keyed table ambiguous; those two
positions share their pooled estimate, which is noted in the output.

Writes data/processed/pool_difficulty_2000.csv:
    position, item_id, n_samples, pass_rate

Sources are the recovery-archive rollouts (the training worktree is retired);
this script is a one-time deriver, and the committed CSV is the artifact the
trainer consumes.
"""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Recovery archive kept beside the repo checkout on the lab machine.
ARCHIVE = (ROOT.parent / "below-zero-recovery-20260821-final"
           / "untracked" / "finetune" / "runs" / "finetune")
POOL = ARCHIVE / "qwen_dose_grid_pool_2000" / "items.jsonl"
ROLLOUTS = [
    ARCHIVE / "qwen_dose_grid_seed0" / "qwen_dose_grid_seed0_quadratic" / "rollouts.jsonl",
    ARCHIVE / "qwen_seed_replication_seed1" / "qwen_seed_replication_seed1_quadratic" / "rollouts.jsonl",
    ARCHIVE / "qwen_seed_replication_seed2" / "qwen_seed_replication_seed2_quadratic" / "rollouts.jsonl",
]
OUT = ROOT / "data" / "processed" / "pool_difficulty_2000.csv"


def main():
    pool = [json.loads(line) for line in POOL.read_text().splitlines()]

    # pass counts by item_id across all three runs' training rollouts
    hits = defaultdict(lambda: [0, 0])  # id -> [correct, total]
    for path in ROLLOUTS:
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r.get("mode") == "train":
                h = hits[r["item_id"]]
                h[1] += 1
                if r["correct"]:
                    h[0] += 1

    rows = []
    for position, item in enumerate(pool):
        correct, total = hits.get(item["item_id"], (0, 0))
        # An item never rolled out (should not happen for a consumed pool)
        # gets the neutral 0.5 so it cannot bias a batch either way.
        rate = correct / total if total else 0.5
        rows.append({
            "position": position,
            "item_id": item["item_id"],
            "n_samples": total,
            "pass_rate": round(rate, 4),
        })

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["position", "item_id", "n_samples", "pass_rate"])
        w.writeheader()
        w.writerows(rows)

    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    n_unsampled = sum(1 for r in rows if r["n_samples"] == 0)
    dupes = [r["position"] for r in rows if r["item_id"] == "train:hellaswag:34062"]
    print(f"wrote {OUT} ({len(rows)} positions, sha256 {digest[:16]}...)")
    print(f"unsampled positions: {n_unsampled}; duplicated-id positions sharing an estimate: {dupes}")


if __name__ == "__main__":
    main()
