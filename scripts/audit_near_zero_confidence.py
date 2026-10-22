#!/usr/bin/env python3
"""Page-wide audit of near-zero stated-confidence values.

The prompting study's "481 answers below 1% confidence" turned out to be a
notation artifact (PROBABILITY: 0.85 written as a fraction, parsed /100).
Ramon's v3.3 review asked for a THOROUGH check that no other exhibit on the
essay page carries the same misinterpretation. This script reads the raw
responses behind every confidence-valued exhibit and writes the receipts to
data/processed/near_zero_confidence_audit.json, which the verify battery
asserts against.

Fingerprints separating artifact from behavior (the audit skill):
  - artifact: decimal tokens <= 1.0 in the raw text; bin mean near a top-bin
    value / 100; bin accuracy matching the top bins.
  - genuine: literal integer tokens; accuracy at or below the base rate.

Surfaces covered:
  1. Fine-tuned family evaluations (the training bubble chart, the
     miscalibration table's low-confidence rows): raw scan of both families'
     responses.jsonl for fraction-notation tokens and the <5%-stated pile.
  2. The corrected re-run bins (every overconfidence/prompting exhibit):
     bin-0 mean stated confidence must be exactly 0 after correction.
  3. The identification and base-model runs: fraction counts from the
     notation-artifact census (already corrected in analysis).
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

TRAINING_FILES = {
    "qwen": ROOT / "runs/finetune/multitask_family_agentic_v1/qwen_evaluation/responses.jsonl",
    "gpt_oss": ROOT / "runs/finetune/openweight_family_v2/gpt_oss_evaluation/responses.jsonl",
}
PROB_RE = re.compile(
    r"(?:probability|confidence)\s*[:=]?\s*([0-9]{1,3}(?:\.[0-9]+)?)\s*%?",
    re.IGNORECASE)


def audit_training(path: Path) -> dict:
    n = fraction = 0
    overall = Counter()
    low = {}  # training_objective -> Counter(n, correct)
    with path.open() as fh:
        for line in fh:
            r = json.loads(line)
            raw = r.get("raw") or ""
            tokens = PROB_RE.findall(raw)
            if not tokens:
                continue
            n += 1
            tok = tokens[-1]
            if "." in tok and float(tok) <= 1.0:
                fraction += 1
            p = r.get("probability")
            correct = bool(r.get("correct"))
            overall["n"] += 1
            overall["correct"] += correct
            if p is not None and float(p) < 0.05:
                c = low.setdefault(r.get("training_objective") or "?",
                                   Counter())
                c["n"] += 1
                c["correct"] += correct
    return {
        "responses_with_probability_token": n,
        "fraction_notation_tokens": fraction,
        "overall_accuracy": overall["correct"] / overall["n"],
        "below_5pct_stated": {
            obj: {"n": c["n"], "accuracy": c["correct"] / c["n"]}
            for obj, c in sorted(low.items())},
    }


def main() -> None:
    out = {"training_families": {}, "corrected_rerun_bins": {},
           "artifact_census_fractions": {}}
    for name, path in TRAINING_FILES.items():
        out["training_families"][name] = audit_training(path)

    bins = list(csv.DictReader(
        (PROCESSED / "notation_rerun_reliability_bins.csv").open()))
    out["corrected_rerun_bins"] = {
        r["arm"]: float(r["mean_stated_confidence"])
        for r in bins if float(r["confidence_bin"]) == 0.0}

    summary = json.loads((PROCESSED / "notation_artifact_summary.json").read_text())
    for group, models in summary["artifact_census"].items():
        out["artifact_census_fractions"][group] = sum(
            v["fraction"] for v in models.values())

    with (PROCESSED / "near_zero_confidence_audit.json").open("w") as fh:
        json.dump(out, fh, indent=2)
    for name, t in out["training_families"].items():
        print(f"{name}: fraction tokens {t['fraction_notation_tokens']}, "
              f"low-stated piles: { {k: (v['n'], round(v['accuracy'], 2)) for k, v in t['below_5pct_stated'].items()} }")
    print("corrected bin-0 means:", out["corrected_rerun_bins"])


if __name__ == "__main__":
    main()
