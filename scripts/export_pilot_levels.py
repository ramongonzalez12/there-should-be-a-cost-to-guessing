"""Per-model LEVELS from the live pilot, not the changes.

The site has always shown what the announced rule CHANGED (see
data/processed/pilot_announced_rule.csv). Ramon's outline asks the prior
question: what does each model actually score, under each way of scoring, in
each condition? Those levels already exist -- the lab runner's report computes them
in metrics.sql and its export writes them to results/tables.json --
but nothing carried them into data/processed/, so the published page could not
quote them.

This reads the committed results/tables.json and emits the two arms the brief
compares:

    control    the model answers and states a confidence, no rule announced
    quad_both  the model is told the confidence-calibrated rule and its formula

    python scripts/export_pilot_levels.py -> data/processed/pilot_levels.csv

Columns are levels, not deltas: accuracy (share of ALL items correct, so an
abstention counts against it exactly as a wrong answer would on a normal
benchmark), abstention rate, mean stated confidence, over/under confidence
(stated minus actual, signed), and the confidence-calibrated score.

Two caveats travel with the data rather than living only in prose:

  * `n` is carried per row. GPT-5.6 Luna's multiple-choice treatment ran on a
    nested 20-item slice against a 50-item control, so its pooled row mixes
    sample sizes; the pooled row records the smallest n it drew on.
  * SimpleQA accuracy depends on the still-unvalidated judge. The abstention
    and confidence columns do not, which is why they are reported without
    qualification and accuracy is flagged in the site's caption.

Pooling is a plain mean over benchmarks, unweighted, because each benchmark
contributes the same 50 frozen items by design. Weighting by n would silently
let one benchmark's larger slice speak for the model.
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "results", "tables.json")
OUT = os.path.join(ROOT, "data", "processed", "pilot_levels.csv")

# The two conditions the brief compares. The pilot ran eight contracts; the
# other six vary how the rule is worded, which is a separate question.
ARMS = {"control": "answer normally and give a confidence",
        "quad_both": "maximise the confidence-calibrated score"}

FIELDS = ["model", "arm", "arm_label", "benchmark", "n", "accuracy",
          "abstention_rate", "mean_confidence", "over_under_confidence",
          "calibrated_score"]


def load_rows():
    with open(SRC, encoding="utf-8") as fh:
        table = json.load(fh)["knowledge_track"]
    cols = table["columns"]
    return [dict(zip(cols, row)) for row in table["rows"]]


def main():
    rows = [r for r in load_rows() if r["contract"] in ARMS]

    out = []
    models = sorted({r["model"] for r in rows})
    for model in models:
        for arm, label in ARMS.items():
            sel = [r for r in rows if r["model"] == model and r["contract"] == arm]
            if not sel:
                continue
            for r in sorted(sel, key=lambda r: r["benchmark"]):
                out.append({
                    "model": model, "arm": arm, "arm_label": label,
                    "benchmark": r["benchmark"], "n": r["n"],
                    "accuracy": r["accuracy"],
                    "abstention_rate": r["abstain_rate"],
                    "mean_confidence": r["mean_p_attempted"],
                    "over_under_confidence": r["overconfidence"],
                    "calibrated_score": r["quad_score"]})

            def avg(key, sel=sel):
                return round(sum(r[key] for r in sel) / len(sel), 4)
            out.append({
                "model": model, "arm": arm, "arm_label": label,
                "benchmark": "POOLED",
                # The smallest slice any benchmark contributed, so a pooled row
                # built partly from a 20-item arm cannot claim 50.
                "n": min(r["n"] for r in sel),
                "accuracy": avg("accuracy"),
                "abstention_rate": avg("abstain_rate"),
                "mean_confidence": avg("mean_p_attempted"),
                "over_under_confidence": avg("overconfidence"),
                "calibrated_score": avg("quad_score")})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    pooled = sum(1 for r in out if r["benchmark"] == "POOLED")
    print(f"wrote {OUT}: {len(out)} rows, {pooled} pooled")


if __name__ == "__main__":
    main()
