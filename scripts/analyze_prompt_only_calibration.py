#!/usr/bin/env python3
"""Analyze the frozen prompt-only calibration experiment.

The experiment deliberately keeps generation and scoring separate. This script
reads the two route-compatible SQLite files, verifies that they form the exact
predeclared matrix, and only then computes paired treatment effects.

Primary estimates give every model-by-benchmark cell equal weight. Repeated
calls improve measurement of each frozen item; they are not counted as new
models, benchmarks, or questions. Confidence and accuracy use the same subset:
formatted, attempted answers with a usable probability. The proper score uses
every question and assigns malformed attempts p=1, as frozen in the protocol.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MODELS = (
    "openai/gpt-5.6-sol",
    "anthropic/claude-sonnet-5",
    "deepseek/deepseek-v4-pro-0813",
    "moonshotai/kimi-k3",
    "mistralai/mistral-medium-3-5",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "qwen/qwen3-30b-a3b-instruct-2507",
    "meta-llama/llama-4-maverick",
    "google/gemini-3.7-flash",
    "openai/gpt-oss-120b",
    # Added September 2026 under the identical frozen items, contracts and
    # per-model settings; complete in every study family before pooling.
    "google/gemini-3.8-flash",
    "anthropic/claude-fable-5.1",
    "meta/muse-glimmer-30b",
)
BENCHMARKS = (
    "mmlu_pro",
    "gpqa_parity",
    "medmcqa",
    "math500",
    "boolq",
    "truthfulqa_mc",
    "ethics_hard",
    "bbq",
)
ARMS = ("control", "quad_score_only")
ITEMS_PER_BENCHMARK = 100
REPS = (0, 1)


@dataclass(frozen=True)
class Record:
    model: str
    benchmark: str
    item_id: str
    arm: str
    rep: int
    attempted: float
    usable: float
    correct_usable: float
    confidence_usable: float
    score: float
    parse_failure: float
    cost_usd: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


# Models dropped before any record is formed (set from --exclude-model): a
# model whose battery is incomplete in a pooled database would otherwise fail
# validate_matrix's exact-count check.
EXCLUDED_MODELS: set = set()


def load_records(db_paths: list[Path]) -> tuple[list[Record], list[dict]]:
    records: list[Record] = []
    requests: list[dict] = []
    for db_path in db_paths:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT a.*, m.rep, m.request_json, m.response_id, m.provider,
                   m.upstream_model, m.finish_reason, m.reasoning_tokens,
                   m.reported_cost_usd
            FROM answers AS a
            JOIN call_meta AS m USING (key)
            """
        ).fetchall()
        connection.close()
        for row in rows:
            if row["model"] in EXCLUDED_MODELS:
                continue
            if row["error"]:
                raise ValueError(
                    f"{db_path}: transport/provider error for {row['key']}: "
                    f"{row['error']}"
                )
            if row["verdict"] not in {"CORRECT", "INCORRECT", "NOT_ATTEMPTED"}:
                raise ValueError(
                    f"{db_path}: missing deterministic verdict for {row['key']}"
                )
            attempted = float(row["verdict"] != "NOT_ATTEMPTED")
            correct = float(row["verdict"] == "CORRECT")
            confidence = row["confidence"]
            usable = float(
                attempted
                and not row["parse_failure"]
                and confidence is not None
                and 0 <= float(confidence) <= 1
            )

            # Malformed output is an incorrect attempt, never free silence. The
            # frozen protocol assigns p=1 when the probability itself is absent.
            if row["verdict"] == "NOT_ATTEMPTED":
                score = 0.0
            else:
                # A malformed response is a confident error and scores -1
                # whatever probability token it happened to carry; this
                # matches scripts/analyze_notation_artifact.py and
                # scripts/export_warning_comparison.py exactly.
                if row["parse_failure"] or confidence is None:
                    score = -1.0
                else:
                    p = min(1.0, max(0.0, float(confidence)))
                    score = (2 * p - p * p) if correct else -(p * p)

            records.append(Record(
                model=row["model"], benchmark=row["benchmark"],
                item_id=row["item_id"], arm=row["contract"], rep=int(row["rep"]),
                attempted=attempted, usable=usable,
                correct_usable=correct if usable else math.nan,
                confidence_usable=float(confidence) if usable else math.nan,
                score=score, parse_failure=float(bool(row["parse_failure"])),
                cost_usd=float(row["cost_usd"] or 0.0),
            ))
            request = json.loads(row["request_json"])
            requests.append({
                "model": row["model"], "benchmark": row["benchmark"],
                "arm": row["contract"], "rep": int(row["rep"]),
                "item_id": row["item_id"], "request": request,
                "provider": row["provider"],
                "upstream_model": row["upstream_model"],
                "reasoning_tokens": row["reasoning_tokens"],
            })
    return records, requests


def validate_matrix(records: list[Record], requests: list[dict]) -> None:
    expected_total = (
        len(MODELS) * len(BENCHMARKS) * len(ARMS)
        * ITEMS_PER_BENCHMARK * len(REPS)
    )
    if len(records) != expected_total:
        raise ValueError(f"expected {expected_total:,} rows, found {len(records):,}")
    if len(requests) != expected_total:
        raise ValueError("every response must retain its exact request metadata")

    observed_models = {record.model for record in records}
    observed_benchmarks = {record.benchmark for record in records}
    observed_arms = {record.arm for record in records}
    if observed_models != set(MODELS):
        raise ValueError(f"model mismatch: {sorted(observed_models)}")
    if observed_benchmarks != set(BENCHMARKS):
        raise ValueError(f"benchmark mismatch: {sorted(observed_benchmarks)}")
    if observed_arms != set(ARMS):
        raise ValueError(f"arm mismatch: {sorted(observed_arms)}")

    by_cell: dict[tuple[str, str, str], set[tuple[str, int]]] = defaultdict(set)
    item_sets: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for record in records:
        key = (record.model, record.benchmark, record.arm)
        pair = (record.item_id, record.rep)
        if pair in by_cell[key]:
            raise ValueError(f"duplicate response in {key}: {pair}")
        by_cell[key].add(pair)
        item_sets[key].add(record.item_id)

    for model in MODELS:
        for benchmark in BENCHMARKS:
            reference_items = None
            for arm in ARMS:
                key = (model, benchmark, arm)
                pairs = by_cell[key]
                if len(pairs) != ITEMS_PER_BENCHMARK * len(REPS):
                    raise ValueError(f"incomplete cell {key}: {len(pairs)} rows")
                items = item_sets[key]
                if len(items) != ITEMS_PER_BENCHMARK:
                    raise ValueError(f"wrong item count in {key}: {len(items)}")
                for item_id in items:
                    item_reps = {rep for item, rep in pairs if item == item_id}
                    if item_reps != set(REPS):
                        raise ValueError(f"wrong repetitions for {key}/{item_id}")
                reference_items = items if reference_items is None else reference_items
                if items != reference_items:
                    raise ValueError(f"arms use different items in {model}/{benchmark}")

    # A route may differ by model, but within a model the non-message request
    # controls must remain identical across prompt arms and benchmarks.
    route_configs: dict[str, set[str]] = defaultdict(set)
    for row in requests:
        request = dict(row["request"])
        request.pop("messages", None)
        request.pop("messages_sha256", None)
        route_configs[row["model"]].add(json.dumps(request, sort_keys=True))
    unstable = {model: configs for model, configs in route_configs.items() if len(configs) != 1}
    if unstable:
        raise ValueError(f"generation controls drifted within model: {sorted(unstable)}")


def metric_row(group: list[Record]) -> dict[str, float]:
    usable = [record for record in group if record.usable]
    return {
        "responses": float(len(group)),
        "answer_rate": sum(record.attempted for record in group) / len(group),
        "usable_confidence_rate": len(usable) / len(group),
        "accuracy": (
            sum(record.correct_usable for record in usable) / len(usable)
            if usable else math.nan
        ),
        "confidence": (
            sum(record.confidence_usable for record in usable) / len(usable)
            if usable else math.nan
        ),
        "calibrated_score": sum(record.score for record in group) / len(group),
        "parse_failure_rate": sum(record.parse_failure for record in group) / len(group),
        # Wrong attempted answers stated at 90%+ confidence, over every
        # scheduled response: the same tail definition as the notation
        # re-run, so the warning comparison can use this control alone.
        "high_confidence_error_90_rate": sum(
            1 for record in usable
            if record.correct_usable == 0.0 and record.confidence_usable >= 0.9
        ) / len(group),
    }


def grouped_rows(records: list[Record], keys: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[Record]] = defaultdict(list)
    for record in records:
        groups[tuple(getattr(record, key) for key in keys)].append(record)
    output = []
    for key_values, group in sorted(groups.items()):
        row = dict(zip(keys, key_values))
        row.update(metric_row(group))
        row["confidence_gap"] = row["confidence"] - row["accuracy"]
        output.append(row)
    return output


def nanmean(values: list[float]) -> float:
    """Return the mean of finite values without requiring NumPy at import time."""
    finite = [value for value in values if not math.isnan(value)]
    return sum(finite) / len(finite) if finite else math.nan


def paired_summary(cells: list[dict]) -> tuple[list[dict], dict]:
    by_pair = {(row["model"], row["benchmark"], row["arm"]): row for row in cells}
    measures = (
        "answer_rate", "usable_confidence_rate", "accuracy", "confidence",
        "confidence_gap", "calibrated_score", "parse_failure_rate",
        "high_confidence_error_90_rate",
    )
    arm_rows = []
    for arm in ARMS:
        selected = [row for row in cells if row["arm"] == arm]
        arm_row = {"arm": arm, "model_benchmark_cells": len(selected)}
        for measure in measures:
            arm_row[measure] = nanmean([row[measure] for row in selected])
        # A signed mean gap can look better merely because overconfident and
        # underconfident cells cancel. Keep the signed gap for the intuitive
        # "confidence minus accuracy" description, but measure whether cells
        # actually moved closer to calibration with absolute gaps.
        arm_row["mean_absolute_confidence_gap"] = nanmean(
            [abs(row["confidence_gap"]) for row in selected]
        )
        arm_rows.append(arm_row)
    control, treatment = arm_rows
    change = {measure: treatment[measure] - control[measure] for measure in measures}
    change["mean_absolute_confidence_gap"] = (
        treatment["mean_absolute_confidence_gap"]
        - control["mean_absolute_confidence_gap"]
    )
    change["gap_closed_share"] = (
        -change["confidence_gap"] / control["confidence_gap"]
        if control["confidence_gap"] else math.nan
    )
    change["cells_gap_improved"] = sum(
        abs(by_pair[(model, benchmark, "quad_score_only")]["confidence_gap"])
        < abs(by_pair[(model, benchmark, "control")]["confidence_gap"])
        for model in MODELS for benchmark in BENCHMARKS
    )
    change["control_cells_overconfident"] = sum(
        by_pair[(model, benchmark, "control")]["confidence_gap"] > 0
        for model in MODELS for benchmark in BENCHMARKS
    )
    change["treatment_cells_overconfident"] = sum(
        by_pair[(model, benchmark, "quad_score_only")]["confidence_gap"] > 0
        for model in MODELS for benchmark in BENCHMARKS
    )
    change["cells_score_improved"] = sum(
        by_pair[(model, benchmark, "quad_score_only")]["calibrated_score"]
        > by_pair[(model, benchmark, "control")]["calibrated_score"]
        for model in MODELS for benchmark in BENCHMARKS
    )
    return arm_rows, change


def response_weighted_summary(records: list[Record]) -> tuple[list[dict], dict]:
    """Sensitivity check that weights every stored call equally.

    All planned cells have the same response count, so most all-question
    measures are nearly identical to the primary equal-cell result. This check
    mainly reveals whether small differences in usable-confidence rates matter.
    """
    arms = []
    for arm in ARMS:
        row = {"arm": arm}
        row.update(metric_row([record for record in records if record.arm == arm]))
        row["confidence_gap"] = row["confidence"] - row["accuracy"]
        arms.append(row)
    control, treatment = arms
    measures = (
        "answer_rate", "usable_confidence_rate", "accuracy", "confidence",
        "confidence_gap", "calibrated_score", "parse_failure_rate",
    )
    change = {measure: treatment[measure] - control[measure] for measure in measures}
    change["gap_closed_share"] = (
        -change["confidence_gap"] / control["confidence_gap"]
        if control["confidence_gap"] else math.nan
    )
    return arms, change


def build_array(records: list[Record]) -> dict[str, object]:
    # NumPy is only needed for the live bootstrap, not for importing the
    # analysis helpers. Keeping the optional dependency local lets the repo's
    # zero-runtime-dependency unit suite exercise those helpers in clean CI.
    import numpy as np

    item_ids = {
        benchmark: sorted({r.item_id for r in records if r.benchmark == benchmark})
        for benchmark in BENCHMARKS
    }
    model_index = {value: index for index, value in enumerate(MODELS)}
    benchmark_index = {value: index for index, value in enumerate(BENCHMARKS)}
    arm_index = {value: index for index, value in enumerate(ARMS)}
    item_index = {
        benchmark: {value: index for index, value in enumerate(values)}
        for benchmark, values in item_ids.items()
    }
    shape = (len(MODELS), len(BENCHMARKS), ITEMS_PER_BENCHMARK, len(REPS), len(ARMS))
    arrays = {
        name: np.full(shape, np.nan, dtype=float)
        for name in ("attempted", "usable", "correct", "confidence", "score")
    }
    for record in records:
        idx = (
            model_index[record.model], benchmark_index[record.benchmark],
            item_index[record.benchmark][record.item_id], record.rep,
            arm_index[record.arm],
        )
        arrays["attempted"][idx] = record.attempted
        arrays["usable"][idx] = record.usable
        arrays["correct"][idx] = 0.0 if math.isnan(record.correct_usable) else record.correct_usable
        arrays["confidence"][idx] = 0.0 if math.isnan(record.confidence_usable) else record.confidence_usable
        arrays["score"][idx] = record.score
    for name, array in arrays.items():
        if np.isnan(array).any():
            raise ValueError(f"matrix array {name} contains missing values")
    return arrays


def bootstrap(arrays: dict[str, object], samples: int, seed: int) -> dict:
    import numpy as np

    rng = np.random.default_rng(seed)
    model_count, benchmark_count, item_count, rep_count, _ = arrays["score"].shape
    draws: dict[str, list[float]] = defaultdict(list)
    rep_axis = np.arange(rep_count)[None, None, None, :]
    for _ in range(samples):
        models = rng.integers(model_count, size=model_count)
        benchmarks = rng.integers(benchmark_count, size=benchmark_count)
        # The same resampled items are used across models and prompt arms within
        # a benchmark draw, preserving the paired comparison.
        items = rng.integers(item_count, size=(benchmark_count, item_count))
        selected: dict[str, np.ndarray] = {}
        for name, array in arrays.items():
            selected[name] = array[
                models[:, None, None, None],
                benchmarks[None, :, None, None],
                items[None, :, :, None],
                rep_axis,
                :,
            ]
        usable_n = selected["usable"].sum(axis=(2, 3))
        accuracy = selected["correct"].sum(axis=(2, 3)) / usable_n
        confidence = selected["confidence"].sum(axis=(2, 3)) / usable_n
        gap = confidence - accuracy
        absolute_gap = np.abs(gap)
        score = selected["score"].mean(axis=(2, 3))
        answer_rate = selected["attempted"].mean(axis=(2, 3))
        for name, values in (
            ("accuracy", accuracy), ("confidence", confidence),
            ("confidence_gap", gap), ("calibrated_score", score),
            ("mean_absolute_confidence_gap", absolute_gap),
            ("answer_rate", answer_rate),
        ):
            arm_means = values.mean(axis=(0, 1))
            draws[name].append(float(arm_means[1] - arm_means[0]))
    return {
        name: {
            "low": float(np.quantile(values, 0.025)),
            "high": float(np.quantile(values, 0.975)),
        }
        for name, values in draws.items()
    }


def contrast_rows(rows: list[dict], key: str) -> list[dict]:
    grouped = defaultdict(dict)
    for row in rows:
        grouped[row[key]][row["arm"]] = row
    output = []
    for value, arms in sorted(grouped.items()):
        if set(arms) != set(ARMS):
            raise ValueError(f"missing arm in {key}={value}")
        control, treatment = arms["control"], arms["quad_score_only"]
        result = {key: value}
        for measure in (
            "answer_rate", "usable_confidence_rate", "accuracy", "confidence",
            "confidence_gap", "calibrated_score", "parse_failure_rate",
        ):
            result[f"control_{measure}"] = control[measure]
            result[f"treatment_{measure}"] = treatment[measure]
            result[f"change_{measure}"] = treatment[measure] - control[measure]
        output.append(result)
    return output


def reliability_rows(records: list[Record]) -> list[dict]:
    groups: dict[tuple[str, float], list[Record]] = defaultdict(list)
    for record in records:
        if not record.usable:
            continue
        # Nearest ten percentage points. This answers the plain-language
        # question: "When the model said about 90%, how often was it right?"
        confidence_bin = min(1.0, math.floor(record.confidence_usable * 10 + 0.5) / 10)
        groups[(record.arm, confidence_bin)].append(record)
    rows = []
    for (arm, confidence_bin), group in sorted(groups.items()):
        rows.append({
            "arm": arm,
            "confidence_bin": confidence_bin,
            "responses": len(group),
            "mean_stated_confidence": sum(r.confidence_usable for r in group) / len(group),
            "accuracy": sum(r.correct_usable for r in group) / len(group),
        })
    return rows


def repeatability(records: list[Record]) -> dict:
    pairs: dict[tuple[str, str, str, str], dict[int, Record]] = defaultdict(dict)
    for record in records:
        pairs[(record.model, record.benchmark, record.arm, record.item_id)][record.rep] = record
    usable_pairs = 0
    same_correctness = 0
    confidence_differences = []
    for reps in pairs.values():
        left, right = reps[0], reps[1]
        if left.usable and right.usable:
            usable_pairs += 1
            same_correctness += int(left.correct_usable == right.correct_usable)
            confidence_differences.append(abs(left.confidence_usable - right.confidence_usable))
    return {
        "paired_items": len(pairs),
        "usable_probability_pairs": usable_pairs,
        "same_correctness_rate": same_correctness / usable_pairs,
        "mean_absolute_confidence_difference": (
            sum(confidence_differences) / len(confidence_differences)
        ),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="append", required=True, type=Path)
    parser.add_argument(
        "--pilot-db", action="append", default=[], type=Path,
        help="pilot database counted for budget auditing but excluded from estimates",
    )
    parser.add_argument("--exclude-model", action="append", default=[], metavar="ID",
                        help="drop every row of this model before analysis (repeatable)")
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260826)
    args = parser.parse_args()
    EXCLUDED_MODELS.update(args.exclude_model)

    records, requests = load_records(args.db)
    validate_matrix(records, requests)
    cells = grouped_rows(records, ("model", "benchmark", "arm"))
    arms, changes = paired_summary(cells)
    weighted_arms, weighted_changes = response_weighted_summary(records)
    intervals = bootstrap(build_array(records), args.bootstrap_samples, args.seed)
    model_rows = contrast_rows(grouped_rows(records, ("model", "arm")), "model")
    benchmark_rows = contrast_rows(
        grouped_rows(records, ("benchmark", "arm")), "benchmark"
    )
    reliability = reliability_rows(records)

    args.out.mkdir(parents=True, exist_ok=True)
    write_csv(args.out / "prompt_only_calibration_headline.csv", arms)
    write_csv(args.out / "prompt_only_calibration_cells.csv", cells)
    write_csv(args.out / "prompt_only_calibration_models.csv", model_rows)
    write_csv(args.out / "prompt_only_calibration_benchmarks.csv", benchmark_rows)
    write_csv(args.out / "prompt_only_calibration_reliability_bins.csv", reliability)

    main_spend = sum(record.cost_usd for record in records)
    pilot_spend = 0.0
    for pilot_path in args.pilot_db:
        connection = sqlite3.connect(pilot_path)
        pilot_spend += float(
            connection.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM answers").fetchone()[0]
        )
        connection.close()
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "models": len(MODELS), "benchmarks": len(BENCHMARKS),
            "unique_questions_per_benchmark": ITEMS_PER_BENCHMARK,
            "prompt_conditions": len(ARMS), "calls_per_permutation": len(REPS),
            "responses": len(records), "primary_unit": "model-by-benchmark cell",
            "primary_cells_per_arm": len(MODELS) * len(BENCHMARKS),
        },
        "models": list(MODELS), "benchmarks": list(BENCHMARKS),
        "arm_estimates": arms, "paired_change": changes,
        "response_weighted_sensitivity": {
            "arm_estimates": weighted_arms, "paired_change": weighted_changes,
        },
        "bootstrap_95_intervals_for_change": intervals,
        "repeatability": repeatability(records),
        "generation_spend_usd": main_spend,
        "pilot_spend_usd": pilot_spend,
        "experiment_spend_usd": main_spend + pilot_spend,
        "analysis_seed": args.seed,
        "bootstrap_samples": args.bootstrap_samples,
    }
    (args.out / "prompt_only_calibration_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    root = Path(__file__).resolve().parents[1]
    manifest = {
        "created_at": summary["created_at"],
        "git_commit": _git_commit(root),
        "analysis_script_sha256": _sha256(Path(__file__)),
        "input_databases": [
            {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in args.db + args.pilot_db
        ],
        "output_files": [
            path.name for path in sorted(args.out.glob("prompt_only_calibration_*"))
        ],
    }
    (args.out / "prompt_only_calibration_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
