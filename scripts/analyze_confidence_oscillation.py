#!/usr/bin/env python3
"""Decompose the confidence-trained overconfidence oscillation, checkpoint by
checkpoint, from the stored dose-grid responses.

Motivating observation (2026-08-27): at 25-step resolution the quadratic arm's
overconfidence gap is not a dose-response but a wave (~0 points at step 100,
troughs near 9 at 250-275, crests near 25 at 350-375). This script asks what
is actually moving, using the raw per-item responses rather than the
aggregated CSV:

  1. Is the movement in stated confidence or in accuracy? (Answer: confidence;
     accuracy is flat at 0.57-0.66 everywhere.)
  2. Is the confidence movement item-specific (relearning which questions it
     knows) or a global level shift? The 250->375 rise moves 90 of 100 items
     up and none down, so it is a level shift: a global confidence prior
     drifting, not knowledge changing.
  3. Does the confidence vocabulary collapse to a few round tokens, and does
     discrimination (mean confidence on correct minus incorrect answers)
     survive the drift? The vocabulary is ~{40,60,75,85,90,95}; oscillation
     is mixture weight sliding across adjacent tokens; discrimination stays
     positive throughout but compresses at crests.
  4. Do the five reward arms oscillate in phase? No: quadratic crests at
     350-375 exactly where quad_cost_0.04 troughs, and binary sits at the
     ceiling throughout. Out-of-phase wandering across arms that share seed,
     data order, and schedule rules out epoch/data-order coupling as the
     driver and points at weak-gradient drift: once nearly calibrated, the
     within-group reward differences GRPO learns from are tiny, so the level
     is free to wander under the KL pull toward the overconfident base.

Reads  runs/finetune/qwen_dose_grid_knowledge_all_steps_v1/responses.jsonl
Writes data/processed/confidence_oscillation.csv  (one row per arm x step)

The CSV is committed so the finding is reproducible without the (gitignored)
runs directory; findings are written up in
notes/2026-08-27-confidence-oscillation-decomposition.md.
"""
import csv
import json
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "runs" / "finetune" / "qwen_dose_grid_knowledge_all_steps_v1" / "responses.jsonl"
OUT = ROOT / "data" / "processed" / "confidence_oscillation.csv"

ARMS = ["binary", "quadratic", "quad_cost_0.04", "quad_cost_0.09", "quad_cost_0.16"]


def main():
    # Group answered responses (those that stated a probability) by arm and
    # optimizer step. Abstentions and unparseable responses carry no stated
    # confidence, so they cannot enter a confidence distribution; the
    # aggregated CSVs already track their rates separately.
    by_cell = defaultdict(list)
    with open(SRC) as f:
        for line in f:
            r = json.loads(line)
            # Same "answered" definition as export_seed_dense_knowledge.py:
            # abstentions and unformatted output are excluded even when they
            # carry a probability token. The two scripts once disagreed here
            # and produced two different "overconfidence gaps" from one file
            # (21 of 60 cells apart by more than half a point).
            if (r["arm"] in ARMS and r["probability"] is not None
                    and not r.get("abstained") and r.get("formatted", True)):
                by_cell[(r["arm"], int(r["dose"]))].append(r)

    rows = []
    for (arm, step), rs in sorted(by_cell.items()):
        probs = [r["probability"] for r in rs]
        n = len(probs)
        mean = sum(probs) / n
        sd = (sum((x - mean) ** 2 for x in probs) / n) ** 0.5
        acc = sum(1 for r in rs if r["correct"]) / n

        # The stated-confidence vocabulary is discrete (models emit round
        # percentages), so the modal token and its share describe the
        # distribution better than moments alone.
        tokens = Counter(round(p * 100) for p in probs)
        top_token, top_n = tokens.most_common(1)[0]

        # Discrimination: does the model still rank its right answers above
        # its wrong ones while the overall level drifts?
        c = [r["probability"] for r in rs if r["correct"]]
        w = [r["probability"] for r in rs if not r["correct"]]
        conf_correct = sum(c) / len(c) if c else float("nan")
        conf_wrong = sum(w) / len(w) if w else float("nan")

        rows.append({
            "arm": arm,
            "step": step,
            "n_answered": n,
            "accuracy_answered": round(acc, 4),
            "mean_confidence": round(mean, 4),
            "sd_confidence": round(sd, 4),
            "gap_points": round((mean - acc) * 100, 1),
            "top_token_pct": top_token,
            "top_token_share": round(top_n / n, 3),
            "share_conf_ge_90": round(sum(1 for x in probs if x >= 0.895) / n, 3),
            "share_conf_le_60": round(sum(1 for x in probs if x <= 0.605) / n, 3),
            "mean_conf_correct": round(conf_correct, 4),
            "mean_conf_wrong": round(conf_wrong, 4),
            "discrimination": round(conf_correct - conf_wrong, 4),
        })

    with open(OUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} arm x step cells)")

    # Headline check, printed so a rerun surfaces drift from the numbers in
    # the note: breadth of the quadratic arm's trough-to-crest level shift.
    conf = defaultdict(dict)
    for (arm, step), rs in by_cell.items():
        if arm == "quadratic":
            for r in rs:
                conf[r["item_id"]][step] = r["probability"]
    deltas = [v[375] - v[250] for v in conf.values() if 250 in v and 375 in v]
    up = sum(1 for d in deltas if d > 0.02)
    down = sum(1 for d in deltas if d < -0.02)
    print(f"quadratic 250->375: {up} items up, {down} down of {len(deltas)} "
          f"(mean {sum(deltas)/len(deltas):+.3f}) — a global level shift")
    every_seed()


OUT_SEEDS = ROOT / "data" / "processed" / "confidence_oscillation_seeds.csv"


def every_seed():
    """The same decomposition on every dense-evaluation seed, not only seed 0.

    The 2026-08-27 note established the wave on one training trajectory. The
    rigor review (2026-09-02) asked for the phenomenology on every seed whose
    dense checkpoints are on disk. This writes one row per seed x arm x step
    to a separate file, so the seed-0 CSV that the oscillation page reads is
    unchanged, and prints per seed the quadratic arm's confidence amplitude
    after the first quarter (crest minus trough of the checkpoint means) and
    how many times the level reversed direction: a wave has several reversals
    and an amplitude well above the item-level noise; a converging run has
    neither.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "export_seed_dense_knowledge", ROOT / "scripts" / "export_seed_dense_knowledge.py")
    dense = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dense)
    rows = []
    headline = []
    for seed, (path, order) in sorted(dense.SOURCES.items()):
        if not path.exists() or path.stat().st_size == 0:
            print(f"seed {seed}: {path.name} missing, skipped")
            continue
        by_cell = defaultdict(list)
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            reward, _ = dense.parse_arm(r["arm"])
            if (reward in dense.ARMS and r["probability"] is not None
                    and not r.get("abstained") and r.get("formatted", True)):
                by_cell[(reward, int(float(r["dose"])))].append(r)
        series = defaultdict(list)
        for (arm, step), rs in sorted(by_cell.items()):
            probs = [r["probability"] for r in rs]
            n = len(probs)
            mean = sum(probs) / n
            acc = sum(1 for r in rs if r["correct"]) / n
            c = [r["probability"] for r in rs if r["correct"]]
            w = [r["probability"] for r in rs if not r["correct"]]
            rows.append({
                "seed": seed, "order": order, "arm": arm, "step": step,
                "n_answered": n,
                "accuracy_answered": round(acc, 4),
                "mean_confidence": round(mean, 4),
                "sd_confidence": round((sum((x - mean) ** 2 for x in probs) / n) ** 0.5, 4),
                "gap_points": round((mean - acc) * 100, 1),
                "share_conf_ge_90": round(sum(1 for x in probs if x >= 0.895) / n, 3),
                "discrimination": round(
                    (sum(c) / len(c) if c else float("nan"))
                    - (sum(w) / len(w) if w else float("nan")), 4),
            })
            series[arm].append((step, mean))
        for arm in ("quadratic", "binary"):
            pts = sorted(series.get(arm, []))
            if len(pts) < 4:
                continue
            last = pts[-1][0]
            window = [m for s_, m in pts if s_ > last / 4]
            amplitude = (max(window) - min(window)) * 100
            diffs = [b - a for a, b in pairwise(window)]
            reversals = sum(1 for a, b in pairwise(diffs) if a * b < 0)
            headline.append((seed, order, arm, len(window), amplitude, reversals))
    with open(OUT_SEEDS, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT_SEEDS} ({len(rows)} seed x arm x step cells)")
    for seed, order, arm, k, amp, rev in headline:
        print(f"  seed {seed:2d} {order:14s} {arm:9s} checkpoints {k:2d} "
              f"amplitude {amp:5.1f} pts  reversals {rev}")


if __name__ == "__main__":
    main()
