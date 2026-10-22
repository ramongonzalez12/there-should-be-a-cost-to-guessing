#!/usr/bin/env python3
"""Export the September coverage extension using the battery's existing metrics.

The selection manifest records both successful and unsuccessful candidates.
Only explicitly completed models can produce full-battery metrics, and every
such source is checked against the exact frozen questions and control prompt.
This exports the extension for report integration without silently changing the
published cohort or its paired prompt-intervention population.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analyze_notation_artifact import cell_metrics, equal_cell_summary, load_group

from belowzero.contracts import CONTRACTS
from belowzero.datasets import BENCHMARKS
from belowzero.prompts import build_messages
from belowzero.provenance import git_commit

BENCHES = ("mmlu_pro", "gpqa_parity", "medmcqa", "math500", "boolq",
           "truthfulqa_mc", "ethics_hard", "bbq")

# Names state the denominator. Values come directly from the established
# notation-corrected battery analyzer, rather than a second scoring formula.
METRICS = {
    "accuracy": "accuracy_among_usable_answers",
    "confidence": "mean_confidence_among_usable_answers",
    "confidence_gap": "confidence_gap_among_usable_answers",
    "overall_accuracy": "accuracy_all_questions",
    "calibrated_score": "quadratic_score_all_questions",
    "high_confidence_error_90_rate": "high_confidence_error_90_rate_all_questions",
    "usable_confidence_rate": "usable_confidence_rate_all_questions",
    "brier_loss": "brier_loss_all_questions",
    "confidence_when_wrong": "mean_confidence_among_wrong_usable_answers",
    "errors_at_90_share": "high_confidence_90_share_among_wrong_usable_answers",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_source(path: Path, model: str, frozen: dict) -> dict:
    """Reject incomplete, ungraded, mismatched, or mixed-configuration sources."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT a.*, m.request_json FROM answers a LEFT JOIN call_meta m USING(key) "
            "WHERE model=? AND contract='control'", (model,)).fetchall()
    if len(rows) != 800 or {r["item_id"] for r in rows} != set(frozen):
        raise ValueError(f"{model}: source does not contain the exact 800 frozen items")
    configurations = set()
    for row in rows:
        if row["error"] or row["verdict"] not in {"CORRECT", "INCORRECT", "NOT_ATTEMPTED"}:
            raise ValueError(f"{model}: provider error or ungraded response")
        if row["parse_failure"] and row["verdict"] != "INCORRECT":
            raise ValueError(f"{model}: malformed output was not graded incorrect")
        request = json.loads(row["request_json"])
        item = frozen[row["item_id"]]
        if request["messages"] != build_messages(item, CONTRACTS["control"]):
            raise ValueError(f"{model}: stored prompt differs from the frozen control")
        if row["reference"] != item["reference"]:
            raise ValueError(f"{model}: stored grading reference differs from frozen item")
        configurations.add(json.dumps({k: request.get(k) for k in
                                       ("max_tokens", "reasoning", "temperature")}, sort_keys=True))
    if len(configurations) != 1:
        raise ValueError(f"{model}: more than one inference configuration")
    return json.loads(next(iter(configurations)))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Refusing to export empty {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "data/processed")
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    frozen = {item["item_id"]: item for bench in BENCHES for item in BENCHMARKS[bench](100)}
    models, cells, inputs = [], [], []
    candidates = selection["candidates"]
    if len({r["model"] for r in candidates}) != len(candidates):
        raise ValueError("Selection contains duplicate model identifiers")
    for candidate in candidates:
        if candidate["status"] not in {"complete", "reused"}:
            continue
        model = candidate["model"]
        path = ROOT / candidate["source"]
        config = validate_source(path, model, frozen)
        rows = [r for r in load_group("coverage_extension", [path], ("control",))
                if r.model == model]
        inputs.append({"model": model, "path": candidate["source"], "sha256": sha256(path)})
        pooled = equal_cell_summary(rows, "corrected")
        models.append({"model": model, "source": candidate["source"],
                       "responses": len(rows), "benchmarks": 8,
                       "max_tokens": config["max_tokens"],
                       "reasoning": json.dumps(config["reasoning"], sort_keys=True),
                       "mean_absolute_benchmark_confidence_gap":
                           pooled["mean_absolute_confidence_gap"],
                       **{target: pooled[key] for key, target in METRICS.items()}})
        for bench in BENCHES:
            group = [r for r in rows if r.benchmark == bench]
            if len(group) != 100:
                raise ValueError(f"{model} {bench}: expected 100 responses")
            metrics = cell_metrics(group, "corrected")
            cells.append({"model": model, "benchmark": bench, "responses": 100,
                          "malformed_rate_all_questions": metrics["malformed_rate"],
                          "abstention_rate_all_questions": metrics["abstention_rate"],
                          **{target: metrics[key] for key, target in METRICS.items()}})
    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "model_coverage_extension_models.csv", models)
    write_csv(args.out / "model_coverage_extension_cells.csv", cells)
    write_csv(args.out / "model_coverage_extension_candidates.csv", candidates)
    manifest = {
        "created_by": "scripts/export_model_coverage_extension.py",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(ROOT),
        "benchmarks": list(BENCHES), "items_per_benchmark": 100,
        "contract": "control", "repetitions": 1,
        "selection_sha256": sha256(args.selection),
        "inputs": inputs, "models": len(models), "responses": len(models) * 800,
        "candidates": len(candidates), "program_spend_usd": selection["program_spend_usd"],
        "slice_sha256": {b: sha256(ROOT / f"data/slices/{b}_100.json") for b in BENCHES},
        "aggregation": "Equal benchmark means within each model; corrected confidence notation.",
        "scope": "Coverage extension; does not change the published paired prompt cohort.",
    }
    (args.out / "model_coverage_extension_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")
    print(f"Exported {len(models)} complete models, {len(cells)} benchmark cells")


if __name__ == "__main__":
    main()
