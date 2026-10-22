"""Export the expanded prompt experiment from its preserved run databases.

The paid runner deliberately writes one SQLite database per model so a slow or
rate-limited provider cannot corrupt the other cohorts.  This script is the
single joining boundary: it accepts only the five planned model/database pairs,
requires every deterministic cell to be complete, and writes the compact levels
that the brief renders.  Raw responses remain in ``runs/`` for audit and replay.

Usage::

    python scripts/export_prompt_estimation.py

No model calls occur here.  Generation and grading must already be complete.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "runs")
SLICES = os.path.join(ROOT, "data", "slices")
OUT = os.path.join(ROOT, "data", "processed", "prompt_estimation_levels.csv")
META = os.path.join(ROOT, "data", "processed", "prompt_estimation_run.json")

BENCHMARKS = ("mmlu_pro", "gpqa_parity", "medmcqa")
CONTRACTS = (
    "control", "guess", "thresh75", "quad_formula", "quad_plain",
    "quad_both", "quad_c50", "deploy",
)


@dataclass(frozen=True)
class Cohort:
    model: str
    filename: str
    expected_n: int
    reasoning: str


COHORTS = (
    Cohort("deepseek/deepseek-v4-pro-0813",
           "prompt_estimation_deepseek_20260822.db", 120, "off"),
    Cohort("google/gemini-3.7-flash",
           "prompt_estimation_gemini_20260822.db", 120, "low"),
    Cohort("mistralai/mistral-small-2603",
           "prompt_estimation_mistral_20260822.db", 198, "off"),
    Cohort("mistralai/mistral-medium-3.1",
           "prompt_estimation_mistral_medium_20260822.db", 120, "off"),
    Cohort("nvidia/nemotron-3-nano-30b-a3b",
           "prompt_estimation_nemotron_20260822.db", 198, "off"),
)

FIELDS = (
    "model", "benchmark", "contract", "n", "accuracy", "answered_rate",
    "accuracy_when_answered", "confidence_when_answered", "confidence_gap",
    "confidence_calibrated_score", "parse_failure_rate", "cost_usd",
)


def _score(row: sqlite3.Row) -> float:
    """Apply the report's frozen confidence-calibrated rule after generation.

    The common c=0.09 scoring lens is applied to every prompt arm.  This keeps
    the outcome comparable even when an arm announced a different rule.
    """
    if row["parse_failure"]:
        return -1.0
    if row["verdict"] == "NOT_ATTEMPTED":
        return 0.0
    probability = row["confidence"] if row["confidence"] is not None else 0.5
    if row["verdict"] == "CORRECT":
        return 2 * probability - probability * probability - 0.09
    return -probability * probability - 0.09


def summarize_cell(rows: list[sqlite3.Row]) -> dict[str, float | int]:
    """Return metrics with explicit denominators for one matched cell."""
    n = len(rows)
    answered = [r for r in rows if r["verdict"] != "NOT_ATTEMPTED"]
    correct = sum(r["verdict"] == "CORRECT" for r in rows)
    correct_answered = sum(r["verdict"] == "CORRECT" for r in answered)
    probabilities = [r["confidence"] if r["confidence"] is not None else 0.5
                     for r in answered]
    answered_n = len(answered)
    answered_accuracy = correct_answered / answered_n if answered_n else 0.0
    answered_confidence = (sum(probabilities) / answered_n
                           if answered_n else 0.0)
    return {
        "n": n,
        "accuracy": correct / n,
        "answered_rate": answered_n / n,
        "accuracy_when_answered": answered_accuracy,
        "confidence_when_answered": answered_confidence,
        "confidence_gap": answered_confidence - answered_accuracy,
        "confidence_calibrated_score": sum(_score(r) for r in rows) / n,
        "parse_failure_rate": sum(bool(r["parse_failure"]) for r in rows) / n,
        "cost_usd": sum(float(r["cost_usd"] or 0.0) for r in rows),
    }


def export(cohorts: tuple[Cohort, ...] = COHORTS) -> tuple[list[dict], dict]:
    """Read, validate, and summarize all planned cohorts."""
    exported: list[dict] = []
    total_cost = 0.0
    total_responses = 0

    for cohort in cohorts:
        path = os.path.join(RUNS, cohort.filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"missing planned run database: {path}")
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        placeholders_b = ",".join("?" for _ in BENCHMARKS)
        placeholders_c = ",".join("?" for _ in CONTRACTS)
        rows = con.execute(
            f"SELECT * FROM answers WHERE model=? "
            f"AND benchmark IN ({placeholders_b}) "
            f"AND contract IN ({placeholders_c})",
            (cohort.model, *BENCHMARKS, *CONTRACTS),
        ).fetchall()
        con.close()

        # A provider may have completed part of an earlier, larger target
        # before being resumed on a nested frozen slice.  Select the committed
        # item identities for the final target; never take an arbitrary first N
        # rows, which would break the paired design.
        allowed: dict[str, set[str]] = {}
        for benchmark in BENCHMARKS:
            slice_path = os.path.join(
                SLICES, f"{benchmark}_{cohort.expected_n}.json")
            if os.path.exists(slice_path):
                with open(slice_path, encoding="utf-8") as handle:
                    allowed[benchmark] = set(json.load(handle))
        rows = [r for r in rows
                if r["benchmark"] not in allowed
                or r["item_id"] in allowed[r["benchmark"]]]

        errors = [r for r in rows if r["error"] is not None]
        pending = [r for r in rows if r["error"] is None and r["verdict"] is None]
        if errors:
            raise ValueError(f"{cohort.model} has {len(errors)} transport errors")
        if pending:
            raise ValueError(f"{cohort.model} has {len(pending)} ungraded rows")

        by_cell: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            by_cell.setdefault((row["benchmark"], row["contract"]), []).append(row)
        expected_cells = {(b, c) for b in BENCHMARKS for c in CONTRACTS}
        if set(by_cell) != expected_cells:
            missing = sorted(expected_cells - set(by_cell))
            raise ValueError(f"{cohort.model} is missing cells: {missing}")

        for benchmark in BENCHMARKS:
            for contract in CONTRACTS:
                cell = by_cell[(benchmark, contract)]
                if len(cell) != cohort.expected_n:
                    raise ValueError(
                        f"{cohort.model} {benchmark}/{contract}: "
                        f"expected {cohort.expected_n}, found {len(cell)}")
                metrics = summarize_cell(cell)
                exported.append({"model": cohort.model,
                                 "benchmark": benchmark,
                                 "contract": contract, **metrics})
                total_cost += float(metrics["cost_usd"])
                total_responses += int(metrics["n"])

    metadata = {
        "pulled": "2026-08-22",
        "benchmarks": list(BENCHMARKS),
        "contracts": list(CONTRACTS),
        "models": [{"model": c.model, "n_per_condition": c.expected_n,
                    "reasoning": c.reasoning, "database": c.filename}
                   for c in cohorts],
        "model_benchmark_comparisons": len(cohorts) * len(BENCHMARKS),
        "cells": len(exported),
        "responses": total_responses,
        "generation_cost_usd": round(total_cost, 6),
        "score": "quadratic confidence-calibrated score with c=0.09",
    }
    return exported, metadata


def main() -> None:
    rows, metadata = export()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with open(META, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    print(f"wrote {OUT}: {len(rows)} cells, {metadata['responses']:,} responses")
    print(f"generation cost: ${metadata['generation_cost_usd']:.2f}")


if __name__ == "__main__":
    main()
