"""Does calibration training make a model break fewer stated constraints?

The second behaviour test, and the companion to export_sycophancy.py. Each
item states a constraint and then makes breaking it the tempting move; the
checkers are deterministic, so this is measured rather than judged.

    python scripts/export_behaviour.py
        -> data/processed/behaviour_constraints.csv

Source (override with $BELOWZERO_BEHAVIOUR_SUMMARY):
    <repo>/runs/finetune/calibration_behaviour_all_steps_v1/summary.json

Three rates travel together and have to be read together. A model can avoid
breaking a constraint by declining the task, so the abstention column is not
a footnote to the violation column, it is the other half of it: a version that
violates less while declining more has not become better behaved, it has
become less useful. The unusable column is the third: a response the checker
cannot parse is neither.

Same checkpoint lineage as the pressure test, so the two can be read side by
side, and the untuned base is included as the thing both are measured against.
Thirty-three items per cell, so these are directional.
"""
import collections
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_summary():
    """Find the run from the main checkout or any worktree."""
    here = ROOT
    rel = os.path.join("runs", "finetune",
                       "calibration_behaviour_all_steps_v1", "summary.json")
    while here != os.path.dirname(here):
        candidate = os.path.join(here, rel)
        if os.path.exists(candidate):
            return candidate
        here = os.path.dirname(here)
    return os.path.join(ROOT, rel)


SRC = os.environ.get("BELOWZERO_BEHAVIOUR_SUMMARY") or _default_summary()
OUT = os.path.join(ROOT, "data", "processed", "behaviour_constraints.csv")

LABELS = {"base": "Untuned base", "binary": "Accuracy only",
          "quadratic": "Confidence-calibrated",
          "quad_cost": "Confidence-calibrated + fixed cost"}

# The step both behaviour runs report on, matching the pressure export so the
# two tables describe the same checkpoints.
STEPS = (0, 125)

FIELDS = ["reward", "reward_label", "n_cells", "n_items",
          "breaks_constraint", "declines", "unusable"]


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing behaviour summary: {SRC}")
    with open(SRC, encoding="utf-8") as fh:
        cells = json.load(fh)["by_checkpoint"]

    grouped = collections.defaultdict(list)
    for cell in cells.values():
        if cell.get("step") in STEPS:
            grouped[cell.get("reward_rule") or "base"].append(cell)

    rows = []
    for reward in ("base", "binary", "quadratic", "quad_cost"):
        sel = grouped.get(reward)
        if not sel:
            continue

        def mean(key, sel=sel):
            return round(sum(c[key] for c in sel) / len(sel), 4)
        rows.append({
            "reward": reward,
            "reward_label": LABELS.get(reward, reward),
            "n_cells": len(sel),
            "n_items": sel[0]["n"],
            "breaks_constraint": mean("violation_rate"),
            "declines": mean("abstention_rate"),
            "unusable": mean("invalid_rate")})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} rows")
    for r in rows:
        print(f"  {r['reward_label']:36s} breaks {r['breaks_constraint']:.3f} "
              f"declines {r['declines']:.3f}")


if __name__ == "__main__":
    main()
