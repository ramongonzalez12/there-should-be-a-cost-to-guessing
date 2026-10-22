"""The fine-tune's checkpoint x announced-prompt matrix, in absolute levels.

data/processed/finetune_pilot_summary.json publishes absolutes for the neutral
prompt only, and contrasts for the announced ones. Ramon's outline asks for the
full grid: every trained version crossed with what the test prompt told it,
each cell carrying accuracy, the confidence it claims, and the
confidence-calibrated score. Those cells exist in the final test's run
artifacts, which are gitignored runtime state, so this script lifts them into
a committed CSV rather than letting the site read a path that may not exist on
another machine.

    python scripts/export_finetune_matrix.py -> data/processed/finetune_matrix.csv

Source (override with $BELOWZERO_FINETUNE_RUNS):
    <repo>/../../.worktrees/finetune/runs/finetune/calibration_final_seed{0,1}_eval_200/summary.json

Each summary carries `cells` keyed "<checkpoint>|<prompt_condition>" for all
sixteen combinations. Seeds are averaged with equal weight because each ran the
same 200 frozen items; the resulting neutral row reproduces the published
final_test.neutral_combined exactly, which is the check that this script and
the published summary describe the same run. `items_sha256` is carried into
every row for the same reason: if the item set ever changes, the CSV says so
rather than silently describing a different experiment.

Per-seed rows are emitted alongside the mean, because the confidence column is
the seed-unstable one (0.45 vs 0.63 for the calibrated checkpoint) and a mean
that hides that would be the more flattering number and the less honest one.
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_runs():
    """Find the training worktree's run directory from anywhere in the repo.

    This script may be run from the main checkout or from any worktree under
    .claude/worktrees/, so the relative depth to the repository root varies.
    Walking up for the .worktrees directory is stable under both.
    """
    here = ROOT
    while here != os.path.dirname(here):
        candidate = os.path.join(here, ".worktrees", "finetune", "runs",
                                 "finetune")
        if os.path.isdir(candidate):
            return candidate
        here = os.path.dirname(here)
    return os.path.join(ROOT, "runs", "finetune")


RUNS = os.environ.get("BELOWZERO_FINETUNE_RUNS") or _default_runs()
OUT = os.path.join(ROOT, "data", "processed", "finetune_matrix.csv")

SEEDS = (0, 1)

# Reader-facing names for the reward each version was trained on, and for what
# the test prompt announced. Kept here rather than in the site so the CSV is
# legible on its own.
CHECKPOINTS = [
    ("base", "Untuned base"),
    ("binary", "Accuracy only"),
    ("quadratic", "Confidence-calibrated"),
    ("quad_cost", "Confidence-calibrated + fixed cost"),
]
PROMPTS = [
    ("neutral", "Answer normally and give a confidence"),
    ("quadratic", "Maximise the confidence-calibrated score"),
]

FIELDS = ["checkpoint", "checkpoint_label", "prompt_condition", "prompt_label",
          "seed", "n", "accuracy", "abstention_rate", "mean_confidence",
          "over_under_confidence", "calibrated_score", "items_sha256"]


def load_seed(seed):
    path = os.path.join(RUNS, f"calibration_final_seed{seed}_eval_200",
                        "summary.json")
    if not os.path.exists(path):
        sys.exit(f"missing final-test artifact: {path}\n"
                 "Set BELOWZERO_FINETUNE_RUNS to the run directory, or "
                 "regenerate the final test. This script deliberately fails "
                 "rather than emitting a partial matrix.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    summaries = {seed: load_seed(seed) for seed in SEEDS}
    shas = {s["items_sha256"] for s in summaries.values()}
    if len(shas) != 1:
        sys.exit(f"seeds ran different item sets: {shas}")
    sha = shas.pop()

    out = []
    for ck, ck_label in CHECKPOINTS:
        for pr, pr_label in PROMPTS:
            cells = [summaries[seed]["cells"][f"{ck}|{pr}"] for seed in SEEDS]

            def row(cell, seed, ck=ck, ck_label=ck_label, pr=pr,
                    pr_label=pr_label):
                accuracy = cell["overall_accuracy"]
                confidence = cell["mean_reported_probability"]
                return {
                    "checkpoint": ck, "checkpoint_label": ck_label,
                    "prompt_condition": pr, "prompt_label": pr_label,
                    "seed": seed, "n": cell["n"],
                    "accuracy": round(accuracy, 4),
                    "abstention_rate": round(cell["abstention_rate"], 4),
                    "mean_confidence": round(confidence, 4),
                    # Signed, claimed minus delivered: positive is
                    # overconfident. Recomputed here rather than taking the
                    # summary's signed_calibration_gap, which is measured among
                    # attempted items only and so would not line up with the
                    # accuracy column beside it.
                    "over_under_confidence": round(confidence - accuracy, 4),
                    "calibrated_score": round(cell["mean_scores"]["quadratic"], 4),
                    "items_sha256": sha}

            for seed, cell in zip(SEEDS, cells):
                out.append(row(cell, seed))

            mean_cell = {
                "n": sum(c["n"] for c in cells),
                "overall_accuracy": sum(c["overall_accuracy"] for c in cells) / len(cells),
                "abstention_rate": sum(c["abstention_rate"] for c in cells) / len(cells),
                "mean_reported_probability":
                    sum(c["mean_reported_probability"] for c in cells) / len(cells),
                "mean_scores": {"quadratic":
                                sum(c["mean_scores"]["quadratic"] for c in cells) / len(cells)},
            }
            out.append(row(mean_cell, "mean"))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {OUT}: {len(out)} rows, items {sha[:12]}")


if __name__ == "__main__":
    main()
