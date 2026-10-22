"""Explain why the integrated prompt study has a higher headline accuracy.

The earlier prompt pilot and the integrated study used different model cohorts
and benchmark sets. This script creates explicit bridge tables so a change in
the pooled level is not mistaken for a treatment effect. It also reports the
new paired prompt contrast across a transparent sweep of benchmark-difficulty
cutoffs instead of selecting one favorable "hard" subset after seeing results.

Inputs are committed analysis outputs. No model calls or judge calls occur.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

NEW_CELLS = PROCESSED / "prompt_only_calibration_cells.csv"
OLD_LEVELS = PROCESSED / "prompt_estimation_levels.csv"

DIFFICULTY_OUTPUT = PROCESSED / "prompt_only_calibration_difficulty_sensitivity.csv"
COMPOSITION_OUTPUT = PROCESSED / "prompt_only_calibration_composition_bridge.csv"
EFFECT_OUTPUT = PROCESSED / "prompt_only_calibration_effect_bridge.csv"
SUMMARY_OUTPUT = PROCESSED / "prompt_only_calibration_interpretation.json"

CONTROL = "control"
NEW_TREATMENT = "quad_score_only"
OLD_TREATMENT = "quad_formula"

OLD_BENCHMARKS = ("mmlu_pro", "gpqa_parity", "medmcqa")
OVERLAP_MODELS = (
    "deepseek/deepseek-v4-pro-0813",
    "google/gemini-3.7-flash",
)

NUMERIC_NEW_FIELDS = (
    "responses",
    "answer_rate",
    "usable_confidence_rate",
    "accuracy",
    "confidence",
    "calibrated_score",
    "parse_failure_rate",
    "confidence_gap",
)

NUMERIC_OLD_FIELDS = (
    "n",
    "answered_rate",
    "accuracy_when_answered",
    "confidence_when_answered",
    "confidence_gap",
    "confidence_calibrated_score",
    "parse_failure_rate",
)


def read_csv(path: Path, numeric_fields: tuple[str, ...]) -> list[dict]:
    """Read a CSV and convert the explicitly named numeric columns to floats."""

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in numeric_fields:
            row[field] = float(row[field])
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write a stable CSV whose columns follow the first row's insertion order."""

    if not rows:
        raise ValueError(f"Refusing to write empty output: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def new_summary(rows: list[dict], models: set[str], benchmarks: set[str], arm: str) -> dict:
    """Equal-weight model-by-benchmark cells, matching the integrated study."""

    selected = [
        row
        for row in rows
        if row["arm"] == arm
        and row["model"] in models
        and row["benchmark"] in benchmarks
    ]
    expected = len(models) * len(benchmarks)
    if len(selected) != expected:
        raise ValueError(f"Expected {expected} cells for {arm}; found {len(selected)}")

    return {
        "model_count": len(models),
        "benchmark_count": len(benchmarks),
        "cell_count": len(selected),
        "responses": int(sum(row["responses"] for row in selected)),
        "accuracy": mean(row["accuracy"] for row in selected),
        "confidence": mean(row["confidence"] for row in selected),
        "gap": mean(row["confidence_gap"] for row in selected),
        "absolute_gap": mean(abs(row["confidence_gap"]) for row in selected),
        "score": mean(row["calibrated_score"] for row in selected),
        "answer_rate": mean(row["answer_rate"] for row in selected),
        "usable_confidence_rate": mean(row["usable_confidence_rate"] for row in selected),
    }


def old_summary(rows: list[dict], models: set[str], benchmarks: set[str], contract: str) -> dict:
    """Reproduce the earlier pilot's response-weighted published summary."""

    selected = [
        row
        for row in rows
        if row["contract"] == contract
        and row["model"] in models
        and row["benchmark"] in benchmarks
    ]
    expected = len(models) * len(benchmarks)
    if len(selected) != expected:
        raise ValueError(f"Expected {expected} old cells for {contract}; found {len(selected)}")

    answered = sum(row["n"] * row["answered_rate"] for row in selected)
    questions = sum(row["n"] for row in selected)
    accuracy = sum(
        row["n"] * row["answered_rate"] * row["accuracy_when_answered"]
        for row in selected
    ) / answered
    confidence = sum(
        row["n"] * row["answered_rate"] * row["confidence_when_answered"]
        for row in selected
    ) / answered

    return {
        "model_count": len(models),
        "benchmark_count": len(benchmarks),
        "cell_count": len(selected),
        "responses": int(questions),
        "accuracy": accuracy,
        "confidence": confidence,
        "gap": confidence - accuracy,
        "absolute_gap": mean(abs(row["confidence_gap"]) for row in selected),
        "score": sum(
            row["n"] * row["confidence_calibrated_score"] for row in selected
        ) / questions,
        "answer_rate": answered / questions,
        "usable_confidence_rate": "",
    }


def level_row(label: str, study: str, scope: str, summary: dict) -> dict:
    """Flatten a summary for the composition bridge CSV."""

    return {
        "label": label,
        "study": study,
        "scope": scope,
        **summary,
    }


def effect_row(label: str, study: str, scope: str, control: dict, treatment: dict) -> dict:
    """Build an apples-to-apples prompt contrast within a fixed study slice."""

    gap_closed = control["gap"] - treatment["gap"]
    share_closed = gap_closed / control["gap"] if control["gap"] else ""
    return {
        "label": label,
        "study": study,
        "scope": scope,
        "models": control["model_count"],
        "benchmarks": control["benchmark_count"],
        "cells": control["cell_count"],
        "responses_both_arms": control["responses"] + treatment["responses"],
        "control_accuracy": control["accuracy"],
        "treatment_accuracy": treatment["accuracy"],
        "change_accuracy": treatment["accuracy"] - control["accuracy"],
        "control_confidence": control["confidence"],
        "treatment_confidence": treatment["confidence"],
        "change_confidence": treatment["confidence"] - control["confidence"],
        "control_gap": control["gap"],
        "treatment_gap": treatment["gap"],
        "change_gap": treatment["gap"] - control["gap"],
        "share_signed_gap_closed": share_closed,
        "control_absolute_gap": control["absolute_gap"],
        "treatment_absolute_gap": treatment["absolute_gap"],
        "change_absolute_gap": treatment["absolute_gap"] - control["absolute_gap"],
        "control_score": control["score"],
        "treatment_score": treatment["score"],
        "change_score": treatment["score"] - control["score"],
    }


def main() -> None:
    new_rows = read_csv(NEW_CELLS, NUMERIC_NEW_FIELDS)
    old_rows = read_csv(OLD_LEVELS, NUMERIC_OLD_FIELDS)

    new_models = {row["model"] for row in new_rows}
    new_benchmarks = {row["benchmark"] for row in new_rows}
    old_models = {row["model"] for row in old_rows}

    if set(OVERLAP_MODELS) != new_models.intersection(old_models):
        raise ValueError("The exact old/new model overlap changed; update the bridge deliberately")

    # Benchmark difficulty is defined once using aggregate control-arm accuracy.
    # This is descriptive and post-hoc, so the outputs retain the entire cutoff
    # sweep rather than selecting a single cutoff because it looks favorable.
    grouped_control: dict[str, list[float]] = defaultdict(list)
    for row in new_rows:
        if row["arm"] == CONTROL:
            grouped_control[row["benchmark"]].append(row["accuracy"])
    benchmark_accuracy = {
        benchmark: mean(values) for benchmark, values in grouped_control.items()
    }

    cutoff_specs = (
        ("below_70", 0.70),
        ("below_75", 0.75),
        ("below_85", 0.85),
        ("below_90", 0.90),
        ("all", 1.01),
    )
    difficulty_rows = []
    for label, cutoff in cutoff_specs:
        selected_benchmarks = {
            benchmark
            for benchmark, accuracy in benchmark_accuracy.items()
            if accuracy < cutoff
        }
        control = new_summary(new_rows, new_models, selected_benchmarks, CONTROL)
        treatment = new_summary(
            new_rows, new_models, selected_benchmarks, NEW_TREATMENT
        )
        selected_cells = [
            (model, benchmark)
            for model in new_models
            for benchmark in selected_benchmarks
        ]
        difficulty_rows.append(
            {
                "difficulty_view": label,
                "definition": (
                    "all benchmarks"
                    if label == "all"
                    else f"benchmark-level control accuracy below {cutoff:.0%}"
                ),
                "benchmark_names": ";".join(
                    sorted(selected_benchmarks, key=benchmark_accuracy.get)
                ),
                **effect_row(label, "integrated", "difficulty sweep", control, treatment),
                "cells_closer_to_zero": sum(
                    abs(
                        next(
                            row["confidence_gap"]
                            for row in new_rows
                            if row["model"] == model
                            and row["benchmark"] == benchmark
                            and row["arm"] == NEW_TREATMENT
                        )
                    )
                    < abs(
                        next(
                            row["confidence_gap"]
                            for row in new_rows
                            if row["model"] == model
                            and row["benchmark"] == benchmark
                            and row["arm"] == CONTROL
                        )
                    )
                    for model, benchmark in selected_cells
                ),
                "cells_score_improved": sum(
                    next(
                        row["calibrated_score"]
                        for row in new_rows
                        if row["model"] == model
                        and row["benchmark"] == benchmark
                        and row["arm"] == NEW_TREATMENT
                    )
                    > next(
                        row["calibrated_score"]
                        for row in new_rows
                        if row["model"] == model
                        and row["benchmark"] == benchmark
                        and row["arm"] == CONTROL
                    )
                    for model, benchmark in selected_cells
                ),
            }
        )

    old_benchmarks = set(OLD_BENCHMARKS)
    overlap_models = set(OVERLAP_MODELS)
    added_benchmarks = new_benchmarks - old_benchmarks

    old_all_control = old_summary(old_rows, old_models, old_benchmarks, CONTROL)
    old_overlap_control = old_summary(
        old_rows, overlap_models, old_benchmarks, CONTROL
    )
    new_overlap_control = new_summary(
        new_rows, overlap_models, old_benchmarks, CONTROL
    )
    new_old_bench_control = new_summary(
        new_rows, new_models, old_benchmarks, CONTROL
    )
    new_added_bench_control = new_summary(
        new_rows, new_models, added_benchmarks, CONTROL
    )
    new_all_control = new_summary(new_rows, new_models, new_benchmarks, CONTROL)

    composition_rows = [
        level_row(
            "Earlier pilot, published headline",
            "earlier pilot",
            "5 models on MMLU-Pro, GPQA, and MedMCQA",
            old_all_control,
        ),
        level_row(
            "Earlier pilot, exact overlap",
            "earlier pilot",
            "DeepSeek V4 Pro and Gemini 3.7 Flash on the same 3 benchmarks",
            old_overlap_control,
        ),
        level_row(
            "Integrated study, exact overlap",
            "integrated study",
            "DeepSeek V4 Pro and Gemini 3.7 Flash on the same 3 benchmarks",
            new_overlap_control,
        ),
        level_row(
            "Integrated study, earlier 3 benchmarks",
            "integrated study",
            "10 models on MMLU-Pro, GPQA, and MedMCQA",
            new_old_bench_control,
        ),
        level_row(
            "Integrated study, 5 added benchmarks",
            "integrated study",
            "10 models on MATH-500, BoolQ, TruthfulQA, ETHICS hard, and BBQ",
            new_added_bench_control,
        ),
        level_row(
            "Integrated study, published headline",
            "integrated study",
            "10 models on all 8 benchmarks",
            new_all_control,
        ),
    ]

    old_all_treatment = old_summary(
        old_rows, old_models, old_benchmarks, OLD_TREATMENT
    )
    old_overlap_treatment = old_summary(
        old_rows, overlap_models, old_benchmarks, OLD_TREATMENT
    )
    new_overlap_treatment = new_summary(
        new_rows, overlap_models, old_benchmarks, NEW_TREATMENT
    )
    new_old_bench_treatment = new_summary(
        new_rows, new_models, old_benchmarks, NEW_TREATMENT
    )
    new_all_treatment = new_summary(
        new_rows, new_models, new_benchmarks, NEW_TREATMENT
    )

    effect_rows = [
        effect_row(
            "Earlier pilot headline",
            "earlier pilot",
            "5 models on the earlier 3 benchmarks",
            old_all_control,
            old_all_treatment,
        ),
        effect_row(
            "Earlier exact overlap",
            "earlier pilot",
            "2 exact-overlap models on the earlier 3 benchmarks",
            old_overlap_control,
            old_overlap_treatment,
        ),
        effect_row(
            "Integrated exact overlap",
            "integrated study",
            "2 exact-overlap models on the earlier 3 benchmarks",
            new_overlap_control,
            new_overlap_treatment,
        ),
        effect_row(
            "Integrated earlier-benchmark slice",
            "integrated study",
            "10 models on the earlier 3 benchmarks",
            new_old_bench_control,
            new_old_bench_treatment,
        ),
        effect_row(
            "Integrated full matrix",
            "integrated study",
            "10 models on all 8 benchmarks",
            new_all_control,
            new_all_treatment,
        ),
    ]

    write_csv(DIFFICULTY_OUTPUT, difficulty_rows)
    write_csv(COMPOSITION_OUTPUT, composition_rows)
    write_csv(EFFECT_OUTPUT, effect_rows)

    summary = {
        "analysis_date": "2026-08-26",
        "inputs": [str(NEW_CELLS.relative_to(ROOT)), str(OLD_LEVELS.relative_to(ROOT))],
        "outputs": [
            str(DIFFICULTY_OUTPUT.relative_to(ROOT)),
            str(COMPOSITION_OUTPUT.relative_to(ROOT)),
            str(EFFECT_OUTPUT.relative_to(ROOT)),
        ],
        "exact_overlap": {
            "models": list(OVERLAP_MODELS),
            "benchmarks": list(OLD_BENCHMARKS),
            "earlier_control_accuracy": old_overlap_control["accuracy"],
            "integrated_control_accuracy": new_overlap_control["accuracy"],
            "change": new_overlap_control["accuracy"] - old_overlap_control["accuracy"],
        },
        "integrated_benchmark_control_accuracy": dict(
            sorted(benchmark_accuracy.items(), key=lambda item: item[1])
        ),
        "interpretation_guardrails": [
            "Compare prompts only within a fixed study slice.",
            "Treat difficulty cutoffs as post-hoc sensitivity analyses, not a replacement primary outcome.",
            "Report signed gap together with absolute gap and the proper score.",
        ],
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {DIFFICULTY_OUTPUT.relative_to(ROOT)}")
    print(f"Wrote {COMPOSITION_OUTPUT.relative_to(ROOT)}")
    print(f"Wrote {EFFECT_OUTPUT.relative_to(ROOT)}")
    print(f"Wrote {SUMMARY_OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
