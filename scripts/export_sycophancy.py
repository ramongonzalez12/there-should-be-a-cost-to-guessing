"""Does calibration training make a model harder to push around? Both arms.

The hope behind this project's speculative section was that a model trained to
price its own confidence would hold its ground under social pressure. This
lifts the measured answer out of gitignored run state into a committed CSV so
the published page can quote it, whichever way it points.

    python scripts/export_sycophancy.py -> data/processed/sycophancy_pressure.csv

Source (override with $BELOWZERO_RUNS):
    <repo>/runs/finetune/calibration_sycophancy_all_steps_v1/summary.json

Both arms are always emitted together, and that is the whole methodology.
Under WRONG pushback, adopting the user's answer is sycophancy. Under RIGHT
pushback, adopting it is appropriate updating. A model that never moves scores
perfectly on the wrong arm while being merely inert, so the wrong-arm number
alone is the flattering, misleading half. The sycophancy evaluation makes
the same argument at length; this script refuses to write one arm without the
other.

The checkpoints here are the same lineage as the final test
(calibration_replication_seed{0,1}_{binary,quadratic,quad_cost}@{50,100,125}),
which is why this file and finetune_matrix.csv can be read side by side, and
the base row is the untuned model both are measured against. n is about 40 per
cell, so these are directional, not precise.
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_summary():
    """Find the sycophancy run from the main checkout or any worktree."""
    here = ROOT
    rel = os.path.join("runs", "finetune",
                       "calibration_sycophancy_all_steps_v1", "summary.json")
    while here != os.path.dirname(here):
        candidate = os.path.join(here, rel)
        if os.path.exists(candidate):
            return candidate
        here = os.path.dirname(here)
    return os.path.join(ROOT, rel)


SRC = os.environ.get("BELOWZERO_SYCOPHANCY_SUMMARY") or _default_summary()
OUT = os.path.join(ROOT, "data", "processed", "sycophancy_pressure.csv")

LABELS = {"base": "Untuned base", "binary": "Accuracy only",
          "quadratic": "Confidence-calibrated",
          "quad_cost": "Confidence-calibrated + fixed cost"}

FIELDS = ["checkpoint", "reward", "reward_label", "seed", "step", "n_wrong_arm",
          "accepts_wrong_pushback", "abandoned_correct_rate", "n_right_arm",
          "accepts_right_pushback"]


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing sycophancy summary: {SRC}")
    with open(SRC, encoding="utf-8") as fh:
        cells = json.load(fh)["by_checkpoint_arm"]

    checkpoints = sorted({k.split("|")[0] for k in cells})
    rows = []
    for ck in checkpoints:
        wrong, right = cells.get(f"{ck}|wrong"), cells.get(f"{ck}|right")
        if not wrong or not right:
            # One arm alone is the misleading half, so a half-measured
            # checkpoint is dropped rather than reported.
            print(f"  skipping {ck}: only one pressure arm present",
                  file=sys.stderr)
            continue
        reward = wrong.get("reward_rule") or "base"
        rows.append({
            "checkpoint": ck,
            "reward": reward,
            "reward_label": LABELS.get(reward, reward),
            "seed": wrong.get("seed") if wrong.get("seed") is not None else "",
            "step": wrong.get("step", 0),
            "n_wrong_arm": wrong["n_usable"],
            "accepts_wrong_pushback": round(wrong["adoption_rate"], 4),
            "abandoned_correct_rate": round(wrong["abandoned_correct_rate"], 4),
            "n_right_arm": right["n_usable"],
            "accepts_right_pushback": round(right["adoption_rate"], 4)})

    rows.sort(key=lambda r: (r["reward"] != "base", r["reward"],
                             str(r["seed"]), r["step"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} checkpoints, both arms each")


if __name__ == "__main__":
    main()
