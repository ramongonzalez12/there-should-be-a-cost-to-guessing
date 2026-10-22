#!/usr/bin/env python3
"""Export matched prompt interventions for Qwen3 8B and GPT-OSS 20B.

Protocol: notes/2026-08-31-matched-prompt-interventions-8b-20b.md. All three
conditions were generated together on the same frozen eight-benchmark battery:
baseline, scoring-rule prompt, and direct confidence instruction.

Conventions frozen to match the integrated study's analysis:
  - accuracy and confidence over formatted, attempted answers with a usable
    probability; malformed output is an incorrect attempt, never silence;
  - the proper score uses every question, malformed probability scores p = 1;
  - transport errors are fatal.

Outputs (data/processed/):
  base_model_prompt_cells.csv     per model x benchmark x arm metrics
  base_model_prompt_manifest.json provenance (DB hash, spend, git commit,
                                  response count, catalogue identity)
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MODEL_DATABASES = {
    # Qwen's first joint run had an 11% parse-failure rate in the
    # scoring-rule/MATH-500 cell because 1,200 tokens truncated long solutions.
    # The replacement repeats all 2,400 Qwen calls with a 3,000-token ceiling.
    "qwen/qwen3-8b": (
        ROOT / "runs" / "matched_prompt_interventions_qwen3_8b_long_20260831.db"
    ),
    "openai/gpt-oss-20b": (
        ROOT / "runs" / "matched_prompt_interventions_8b20b_20260831.db"
    ),
}
MODEL_CATALOG = ROOT / "data" / "models_catalog.csv"

MODELS = ("qwen/qwen3-8b", "openai/gpt-oss-20b")
BENCHMARKS = ("mmlu_pro", "gpqa_parity", "medmcqa", "math500",
              "boolq", "truthfulqa_mc", "ethics_hard", "bbq")
ARMS = ("control", "quad_score_only", "hedge_placebo")
ITEMS = 100


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    rows: list[sqlite3.Row] = []
    for model, database in MODEL_DATABASES.items():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        rows.extend(
            connection.execute(
                "SELECT * FROM answers WHERE model = ?", (model,)
            ).fetchall()
        )
        connection.close()

    groups: dict[tuple[str, str, str], list[sqlite3.Row]] = defaultdict(list)
    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    total_cost = 0.0
    for row in rows:
        if row["error"]:
            raise ValueError(f"transport error for {row['key']}")
        if row["verdict"] not in {"CORRECT", "INCORRECT", "NOT_ATTEMPTED"}:
            raise ValueError(f"missing verdict for {row['key']}")
        key = (row["model"], row["benchmark"], row["contract"])
        if row["item_id"] in seen[key]:
            raise ValueError(f"duplicate response in {key}: {row['item_id']}")
        seen[key].add(row["item_id"])
        groups[key].append(row)
        total_cost += float(row["cost_usd"] or 0.0)

    expected = len(MODELS) * len(BENCHMARKS) * len(ARMS) * ITEMS
    if len(rows) != expected:
        raise ValueError(f"expected {expected:,} rows, found {len(rows):,}")
    for model in MODELS:
        for benchmark in BENCHMARKS:
            benchmark_item_sets = []
            for arm in ARMS:
                if len(seen[(model, benchmark, arm)]) != ITEMS:
                    raise ValueError(f"incomplete cell {(model, benchmark, arm)}")
                benchmark_item_sets.append(seen[(model, benchmark, arm)])
            if any(item_set != benchmark_item_sets[0] for item_set in benchmark_item_sets[1:]):
                raise ValueError(f"prompt arms changed item identities for {model}/{benchmark}")
    for benchmark in BENCHMARKS:
        first = seen[(MODELS[0], benchmark, ARMS[0])]
        for model in MODELS:
            for arm in ARMS:
                if seen[(model, benchmark, arm)] != first:
                    raise ValueError(f"models do not share frozen items for {benchmark}")

    out = []
    for (model, benchmark, arm), group in sorted(groups.items()):
        usable = []
        score_sum = 0.0
        attempted_n = 0
        parse_failures = 0
        high_confidence_errors_90 = 0
        for row in group:
            attempted = row["verdict"] != "NOT_ATTEMPTED"
            correct = row["verdict"] == "CORRECT"
            confidence = row["confidence"]
            attempted_n += attempted
            parse_failures += bool(row["parse_failure"])
            if (attempted and not row["parse_failure"]
                    and confidence is not None and 0 <= float(confidence) <= 1):
                usable.append((float(confidence), correct))
                high_confidence_errors_90 += bool(
                    not correct and float(confidence) >= 0.90
                )
            if attempted:
                p = float(confidence) if confidence is not None else 1.0
                p = min(1.0, max(0.0, p))
                score_sum += (2 * p - p * p) if correct else -(p * p)
        accuracy = (sum(c for _, c in usable) / len(usable)) if usable else math.nan
        confidence_mean = (sum(p for p, _ in usable) / len(usable)) if usable else math.nan
        out.append({
            "model": model, "benchmark": benchmark, "arm": arm,
            "responses": len(group),
            "answer_rate": attempted_n / len(group),
            "usable_confidence_rate": len(usable) / len(group),
            "accuracy": accuracy,
            "confidence": confidence_mean,
            "confidence_gap": confidence_mean - accuracy,
            "calibrated_score": score_sum / len(group),
            "high_confidence_error_90_count": high_confidence_errors_90,
            "high_confidence_error_90_rate": high_confidence_errors_90 / len(group),
            "parse_failure_rate": parse_failures / len(group),
        })

    PROCESSED.mkdir(parents=True, exist_ok=True)
    fields = ["model", "benchmark", "arm", "responses", "answer_rate",
              "usable_confidence_rate", "accuracy", "confidence",
              "confidence_gap", "calibrated_score",
              "high_confidence_error_90_count",
              "high_confidence_error_90_rate", "parse_failure_rate"]
    with (PROCESSED / "base_model_prompt_cells.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
    with (PROCESSED / "base_model_prompt_manifest.json").open("w") as handle:
        json.dump({
            "protocol": "notes/2026-08-31-matched-prompt-interventions-8b-20b.md",
            "databases": [
                {
                    "model": model,
                    "path": str(database.relative_to(ROOT)),
                    "sha256": _sha256(database),
                }
                for model, database in MODEL_DATABASES.items()
            ],
            "model_catalog": {"path": str(MODEL_CATALOG.relative_to(ROOT)),
                              "sha256": _sha256(MODEL_CATALOG)},
            "responses": len(rows),
            "total_cost_usd": round(total_cost, 4),
            "git_commit": git_commit,
        }, handle, indent=2)

    for model in MODELS:
        for arm in ARMS:
            sel = [r for r in out if r["model"] == model and r["arm"] == arm]
            gap = sum(r["confidence_gap"] for r in sel) / len(sel)
            acc = sum(r["accuracy"] for r in sel) / len(sel)
            conf = sum(r["confidence"] for r in sel) / len(sel)
            pf = sum(r["parse_failure_rate"] for r in sel) / len(sel)
            print(f"{model:22s} {arm:16s} acc {acc:.3f}  conf {conf:.3f}  "
                  f"gap {gap:+.3f}  parse_fail {pf:.3f}")
    print(f"spend: ${total_cost:.2f}")


if __name__ == "__main__":
    main()
