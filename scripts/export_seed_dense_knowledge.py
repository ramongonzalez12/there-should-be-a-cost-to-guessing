#!/usr/bin/env python3
"""Export the dense (every-25-steps) knowledge trajectories for all three
densely evaluated training seeds into one committed CSV.

Provenance:
  seed 0 — runs/finetune/qwen_dose_grid_knowledge_all_steps_v1/responses.jsonl
           (the original all-checkpoint eval of 2026-08-18)
  seed 1 — runs/finetune/seed1_dense_eval_v1/responses.jsonl (2026-08-27)
  seed 2 — runs/finetune/seed2_dense_eval_v1/responses.jsonl (2026-08-27)

All three runs use the identical 100 held-out knowledge items (verified by
item-id list against the original run before the paid runs were launched),
neutral framing, temperature 0. Seeds 0 and 1 trained on the identical item
order; seed 2 on a seeded permutation — that contrast is the point of the
export (see notes/2026-08-27-confidence-oscillation-decomposition.md).

Writes data/processed/seed_dense_knowledge.csv with the same accounting as
seed_replication_knowledge.csv: `accuracy` and `coverage` are over all items,
so accuracy among answered items is accuracy/coverage, and `overconfidence`
is mean stated probability minus accuracy-among-answered, both among answered
items only. `confidence_adjusted_accuracy` is the mean pure quadratic score
over every item. For binary correctness y and stated probability p, this is
y - (p - y)^2: raw accuracy minus Brier loss.

`high_confidence_error_90_rate` is the share of all scheduled questions that
produce an incorrect answer reported at 90% confidence or higher. Multiplying
it by 100 gives the essay's "90%+ confidence errors per 100 questions" measure.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def _read_csv(path):
    # SIM115: context-managed CSV read
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _read_json(path):
    # SIM115: context-managed JSON read
    with open(path) as fh:
        return json.load(fh)

ROOT = Path(__file__).resolve().parent.parent
# seed -> (responses file, curriculum order). Seeds 0/1 trained on the pool's
# file order, seed 2 on a seeded permutation, seeds 7/8 on the
# difficulty-balanced order (notes/2026-08-28-balanced-recipe-protocol.md).
# The balanced family's eval labels arms "reward.seedN" because one manifest
# carries both seeds; parse_arm() below normalises both label styles.
SOURCES = {
    0: (ROOT / "runs" / "finetune" / "qwen_dose_grid_knowledge_all_steps_v1" / "responses.jsonl", "file"),
    1: (ROOT / "runs" / "finetune" / "seed1_dense_eval_v1" / "responses.jsonl", "file"),
    2: (ROOT / "runs" / "finetune" / "seed2_dense_eval_v1" / "responses.jsonl", "permuted"),
    7: (ROOT / "runs" / "finetune" / "balanced_dense_eval_s7" / "responses.jsonl", "balanced"),
    8: (ROOT / "runs" / "finetune" / "balanced_dense_eval_s8" / "responses.jsonl", "balanced"),
    # seed 9 trains with group size 16 (vs 8 everywhere else) on the balanced
    # order: the rung-2 recipe candidate.
    9: (ROOT / "runs" / "finetune" / "balanced_dense_eval_s9" / "responses.jsonl", "balanced-g16"),
    # seeds 11/12: the pre-registered 2x2 at 4x per-step scale (batch 8 x
    # group 16 = 128 completions/step), balanced order, one epoch of 250
    # steps with checkpoints every 10.
    11: (ROOT / "runs" / "finetune" / "scaled_dense_eval_s11" / "responses.jsonl", "balanced-b8g16"),
    12: (ROOT / "runs" / "finetune" / "scaled_dense_eval_s12" / "responses.jsonl", "balanced-b8g16"),
    # seed 13: the scaling-curve extension, 256 completions/step
    # (batch 16 x group 16), 125 steps = one epoch, checkpoints every 5.
    13: (ROOT / "runs" / "finetune" / "scaled_dense_eval_s13" / "responses.jsonl", "balanced-b16g16"),
    # seed 14: the pre-registered confirmation pair at 256/step.
    14: (ROOT / "runs" / "finetune" / "scaled_dense_eval_s14" / "responses.jsonl", "balanced-b16g16"),
}
OUT = ROOT / "data" / "processed" / "seed_dense_knowledge.csv"


def parse_arm(label: str):
    """'quadratic' -> ('quadratic', None); 'quadratic.seed7' -> ('quadratic', 7)."""
    if ".seed" in label:
        reward, _, seed = label.partition(".seed")
        return reward, int(seed)
    return label, None

# The three arms trained in every seed. Seed 0's file also carries
# quad_cost_0.04 / 0.16, which the replication seeds do not have; the export
# keeps the common set so every (objective, step) cell exists for every seed.
ARMS = ("base", "binary", "quadratic", "quad_cost_0.09")


def main():
    # This machine evicts cold files (APFS dataless; reads come back empty),
    # and raw runs/ artifacts are exactly the cold files it goes for. The
    # committed CSV is the durable record, so when a seed's raw source is
    # missing OR reads empty, carry that seed's rows forward from the
    # existing CSV instead of silently dropping the seed.
    prior = {}
    if OUT.exists():
        for row in _read_csv(OUT):
            prior.setdefault(int(row["seed"]), []).append(row)

    rows = []
    for seed, (path, order) in sorted(SOURCES.items()):
        readable = False
        if path.exists() and path.stat().st_size > 0:
            with open(path) as fh:
                readable = bool(fh.readline().strip())
        if not readable:
            # An unreadable source used to be carried forward silently from
            # the committed CSV, which made re-running this exporter look like
            # a verification when it could be re-emitting stale rows forever
            # (this machine evicts cold files, so "unreadable" is common).
            # Carrying forward is now an explicit choice on the command line;
            # the default is to stop and say which source is missing.
            if "--allow-carry-forward" not in sys.argv:
                raise SystemExit(
                    f"seed {seed}: {path} is missing or empty; re-fetch it or "
                    "pass --allow-carry-forward to keep the committed rows")
            if seed in prior:
                rows.extend(prior[seed])
                print(f"seed {seed}: source unreadable, carried {len(prior[seed])} rows forward from the committed CSV (explicitly allowed)")
            else:
                print(f"seed {seed}: {path.name} not present, skipped")
            continue
        cells = defaultdict(list)
        for line in path.read_text().splitlines():
            r = json.loads(line)
            reward, label_seed = parse_arm(r["arm"])
            # In a multi-seed responses file, keep only this seed's rows.
            if label_seed is not None and label_seed != seed:
                continue
            if reward in ARMS:
                cells[(reward, int(r["dose"]))].append(r)
        for (arm, step), rs in sorted(cells.items()):
            n = len(rs)
            # "Answered" excludes abstentions and unformatted output even when
            # the response still carried a probability token (an "I DON'T
            # KNOW" line often does): coverage and the overconfidence gap are
            # defined among genuine answers, matching
            # seed_replication_knowledge.csv exactly (base: coverage 0.89,
            # overconfidence 0.266, not 1.0/0.346).
            answered = [r for r in rs
                        if not r["abstained"] and r["formatted"]
                        and r["probability"] is not None]
            correct = sum(1 for r in answered if r["correct"])
            coverage = len(answered) / n
            accuracy = correct / n
            mean_p = (sum(r["probability"] for r in answered) / len(answered)
                      if answered else float("nan"))
            over = mean_p - (correct / len(answered)) if answered else float("nan")
            # Every saved response carries the score computed from the raw
            # answer and probability. Average it over all items so malformed
            # attempts cannot disappear from the confidence-adjusted result.
            confidence_adjusted_accuracy = (
                sum(float(r["scores"]["quadratic"]) for r in rs) / n
            )
            high_confidence_error_90_rate = sum(
                r["outcome"] == "INCORRECT"
                and r.get("probability") is not None
                and float(r["probability"]) >= 0.9
                for r in rs
            ) / n
            rows.append({
                "seed": seed,
                "order": order,
                "objective": arm,
                "step": step,
                "n": n,
                "accuracy": round(accuracy, 4),
                "coverage": round(coverage, 4),
                "abstention_rate": round(sum(1 for r in rs if r["abstained"]) / n, 4),
                "invalid_rate": round(sum(1 for r in rs if not r["formatted"]) / n, 4),
                "mean_probability": round(mean_p, 4),
                "overconfidence": round(over, 4),
                "confidence_adjusted_accuracy": round(
                    confidence_adjusted_accuracy, 4
                ),
                "high_confidence_error_90_rate": round(
                    high_confidence_error_90_rate, 4
                ),
            })

    with open(OUT, "w", newline="") as f:
        # Pin Unix line endings so regeneration is byte-stable across
        # platforms and `git diff --check` does not interpret CRLF endings as
        # trailing whitespace.
        w = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys()),
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} seed x objective x step cells)")


if __name__ == "__main__":
    main()
