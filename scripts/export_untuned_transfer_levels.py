#!/usr/bin/env python3
"""Export the untuned levels on the subject-transfer batteries.

The transfer tables compare accuracy-only and true-confidence fine-tuning on
four evaluation batteries (math, medicine, ethics, GPQA). Both families were
also evaluated untuned on exactly those batteries (Qwen3 8B as the base model;
GPT-OSS 20B as the shared syntax-only warm-up checkpoint that both reward arms
start from), but the two transfer exporters drop every cell whose objective is
not binary or quadratic, so the essay said "no matching untuned evaluation was
collected". It was. This script reads those saved responses and writes one row
per family and evaluation battery with the same three outcomes the transfer
tables use, on the same denominators:

  accuracy and confidence among usable answers (answered, formatted, with a
  probability); the proper score over every scheduled question (abstention 0,
  malformed -1 as the evaluator recorded it); the 90%+ error tail over every
  scheduled question.

Writes data/processed/untuned_transfer_levels.csv and a manifest with the
sha256 of both response files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import statistics
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "untuned_transfer_levels.csv"
MANIFEST = ROOT / "data" / "processed" / "untuned_transfer_manifest.json"
SOURCES = {
    "Qwen3 8B": (
        ROOT / "runs" / "finetune" / "multitask_family_agentic_v1" / "qwen_evaluation" / "responses.jsonl",
        "base",
    ),
    "GPT-OSS 20B": (
        ROOT / "runs" / "finetune" / "gptoss_domain_replication" / "evaluation" / "responses.jsonl",
        "control",
    ),
}
DOMAINS = ("math", "medicine", "ethics", "gpqa")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def level(records: list[dict]) -> dict:
    n = len(records)
    usable = [r for r in records
              if r["outcome"] in ("CORRECT", "INCORRECT")
              and r.get("formatted", True) and r.get("probability") is not None]
    accuracy = sum(r["outcome"] == "CORRECT" for r in usable) / len(usable)
    confidence = statistics.mean(float(r["probability"]) for r in usable)
    return {
        "scheduled_n": n,
        "usable_n": len(usable),
        "coverage": len(usable) / n,
        "accuracy_among_answers": accuracy,
        "confidence_among_answers": confidence,
        "signed_confidence_gap": confidence - accuracy,
        "confidence_calibrated_score": statistics.mean(
            float(r["scores"]["quadratic"]) for r in records),
        "high_confidence_error_90_rate": sum(
            r["outcome"] == "INCORRECT" and r.get("probability") is not None
            and float(r["probability"]) >= 0.9 for r in records) / n,
    }


def main() -> None:
    rows = []
    sources = {}
    for family, (path, checkpoint) in SOURCES.items():
        sources[str(path.relative_to(ROOT))] = _sha256(path)
        by_domain: dict[str, list[dict]] = {d: [] for d in DOMAINS}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("checkpoint") == checkpoint and r.get("evaluation_domain") in by_domain:
                by_domain[r["evaluation_domain"]].append(r)
        for domain in DOMAINS:
            if not by_domain[domain]:
                raise SystemExit(f"{family}: no untuned responses for {domain}")
            rows.append({"model_family": family, "checkpoint": checkpoint,
                         "evaluation_domain": domain, **level(by_domain[domain])})
        # The pooled subjects row is what the transfer table's own-subject and
        # other-subject rows both start from for an untuned model.
        pooled = [r for d in ("math", "medicine", "ethics") for r in by_domain[d]]
        rows.append({"model_family": family, "checkpoint": checkpoint,
                     "evaluation_domain": "subjects_pooled", **level(pooled)})
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=False).stdout.strip()
    MANIFEST.write_text(json.dumps({
        "script": "scripts/export_untuned_transfer_levels.py",
        "git_commit": commit,
        "sources": sources,
        "outputs": [str(OUT.relative_to(ROOT))],
        "rows": len(rows),
    }, indent=2) + "\n")
    print(f"wrote {OUT} ({len(rows)} rows)")
    for r in rows:
        print(f"  {r['model_family']:12s} {r['evaluation_domain']:16s} gap {r['signed_confidence_gap']*100:+5.1f} "
              f"score {r['confidence_calibrated_score']*100:5.1f} tail {r['high_confidence_error_90_rate']*100:5.1f}")


if __name__ == "__main__":
    main()
