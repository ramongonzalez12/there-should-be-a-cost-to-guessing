#!/usr/bin/env python3
"""Analyze the prompt-arm identification study (hedge placebo vs worked example).

The integrated prompt-only study found that explaining the quadratic score
compresses stated confidence without improving calibration. A two-arm design
cannot say WHY. This study's two arms separate the mechanisms:

  hedge_placebo        confidence-lowering pressure with zero rule content
  quad_worked_example  the rule plus a two-line numeric worked example

Each arm ran on the identical frozen matrix (same 10 models, same 8 benchmarks,
same 100-item slices, one call per permutation). The comparison baseline is the
integrated study's committed cell table, NOT its raw databases: the response
DBs behind the integrated study were believed lost (they were later recovered
from a sibling worktree on 2026-09-02); the pre-specified comparison
here is at the model-by-benchmark cell level (80 cells per arm), which is also
the integrated study's primary weighting. That limitation is recorded in the
manifest.

Analysis conventions are frozen to match scripts/analyze_prompt_only_calibration.py:
  - equal weight per model-benchmark cell;
  - accuracy and confidence computed over formatted, attempted answers with a
    usable probability;
  - the proper score uses every question; malformed output is an incorrect
    attempt (never silence) and scores at p = 1 when the probability is absent;
  - transport errors are fatal, not skippable.

Outputs (data/processed/):
  prompt_arm_identification_cells.csv      per model x benchmark x arm metrics
  prompt_arm_identification_reliability_bins.csv  pooled bins per arm
  prompt_arm_identification_summary.json   arm summaries, contrasts, bootstrap CIs
  prompt_arm_identification_manifest.json  provenance (DB hashes, git commit, spend)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

# The frozen pre-registered databases. Later cohorts that ran the SAME two
# arms on the same 8 benchmarks and 100-item slices can be pooled in at the
# command line with --extra-db; nothing here is edited for them, so a run with
# no flags reproduces the committed tables byte for byte.
DBS = (
    ROOT / "runs" / "prompt_arm_ident_main_off_20260827.db",
    ROOT / "runs" / "prompt_arm_ident_main_low_20260827.db",
)

# The frozen pre-registered model cohort. These ten are the only models with
# committed Aug 26 / Aug 27 baseline cells, so the contrasts below are always
# computed over exactly this tuple. Models that arrive with an --extra-db are
# named at the command line with --extra-model: they are validated and pooled
# into the cell table and the arm summaries, but they cannot enter a contrast
# that has no baseline for them. The tuple itself gets edited only once the
# new runs are complete and their baselines are committed.
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
    "mmlu_pro", "gpqa_parity", "medmcqa", "math500",
    "boolq", "truthfulqa_mc", "ethics_hard", "bbq",
)
NEW_ARMS = ("hedge_placebo", "quad_worked_example")
ITEMS_PER_BENCHMARK = 100
# The integrated study's committed cell table supplies the pre-specified
# baselines (Aug 26, two calls per question). The Aug 27 notation re-run
# supplies a second, same-day control whose raw responses were always retained;
# contrasts are reported against both so the reader can see how much of the
# warning effect depends on which control is used.
BASELINE_CELLS = PROCESSED / "prompt_only_calibration_cells.csv"
RERUN_CELLS = PROCESSED / "notation_artifact_cells.csv"
BASELINE_ARMS = ("control", "quad_score_only")
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260827


@dataclass(frozen=True)
class Record:
    model: str
    benchmark: str
    item_id: str
    arm: str
    attempted: float
    usable: float
    correct_usable: float
    confidence_usable: float
    confidence_any: float  # confidence whenever parsable, for the bin table
    score: float
    parse_failure: float
    cost_usd: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


# Models dropped before any record is formed (set from --exclude-model): a
# model whose battery is incomplete in a pooled database would otherwise fail
# the matrix validation or be pooled as a partial cell.
EXCLUDED_MODELS: set = set()


def load_records(dbs) -> list[Record]:
    """Read every graded response out of `dbs` and reduce it to a Record.

    `dbs` is passed in rather than closed over so extra cohort databases can
    be pooled with the frozen two without touching the module constant.
    """
    records: list[Record] = []
    for db_path in dbs:
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT a.*, m.rep FROM answers AS a JOIN call_meta AS m USING (key)"
        ).fetchall()
        connection.close()
        for row in rows:
            if row["model"] in EXCLUDED_MODELS:
                continue
            if row["error"]:
                raise ValueError(f"{db_path}: transport error for {row['key']}")
            if row["verdict"] not in {"CORRECT", "INCORRECT", "NOT_ATTEMPTED"}:
                raise ValueError(f"{db_path}: missing verdict for {row['key']}")
            if int(row["rep"]) != 0:
                raise ValueError(f"{db_path}: unexpected rep for {row['key']}")
            attempted = float(row["verdict"] != "NOT_ATTEMPTED")
            correct = float(row["verdict"] == "CORRECT")
            confidence = row["confidence"]
            usable = float(
                attempted
                and not row["parse_failure"]
                and confidence is not None
                and 0 <= float(confidence) <= 1
            )
            # Malformed output is an incorrect attempt, never free silence; a
            # missing probability scores at p = 1, exactly as frozen upstream.
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
                item_id=row["item_id"], arm=row["contract"],
                attempted=attempted, usable=usable,
                correct_usable=correct if usable else math.nan,
                confidence_usable=float(confidence) if usable else math.nan,
                confidence_any=(
                    float(confidence) if confidence is not None else math.nan
                ),
                score=score, parse_failure=float(bool(row["parse_failure"])),
                cost_usd=float(row["cost_usd"] or 0.0),
            ))
    return records


def validate_matrix(records: list[Record], models) -> None:
    """Every model in `models` must contribute a complete, un-duplicated grid.

    `models` is the frozen tuple plus whatever --extra-model added, so a
    pooled cohort is held to exactly the same completeness bar as the
    pre-registered one. The duplicate-item check below is also the per-model
    reasoning-route guard: a model may appear in the reasoning-off database or
    the reasoning-low one, never both, because a second copy of an item id in
    the same (model, benchmark, arm) cell raises here.
    """
    expected = len(models) * len(BENCHMARKS) * len(NEW_ARMS) * ITEMS_PER_BENCHMARK
    if len(records) != expected:
        raise ValueError(f"expected {expected:,} rows, found {len(records):,}")
    if {r.model for r in records} != set(models):
        raise ValueError("model set mismatch")
    if {r.benchmark for r in records} != set(BENCHMARKS):
        raise ValueError("benchmark set mismatch")
    if {r.arm for r in records} != set(NEW_ARMS):
        raise ValueError("arm set mismatch")
    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for r in records:
        key = (r.model, r.benchmark, r.arm)
        if r.item_id in seen[key]:
            raise ValueError(f"duplicate response in {key}: {r.item_id}")
        seen[key].add(r.item_id)
    for key, items in seen.items():
        if len(items) != ITEMS_PER_BENCHMARK:
            raise ValueError(f"incomplete cell {key}: {len(items)} items")
    # Both arms must see the identical frozen items within each model/benchmark.
    for model in models:
        for benchmark in BENCHMARKS:
            a = seen[(model, benchmark, NEW_ARMS[0])]
            b = seen[(model, benchmark, NEW_ARMS[1])]
            if a != b:
                raise ValueError(f"arms use different items in {model}/{benchmark}")


def metric_row(group: list[Record]) -> dict[str, float]:
    usable = [r for r in group if r.usable]
    row = {
        "responses": float(len(group)),
        "answer_rate": sum(r.attempted for r in group) / len(group),
        "usable_confidence_rate": len(usable) / len(group),
        "accuracy": (
            sum(r.correct_usable for r in usable) / len(usable)
            if usable else math.nan
        ),
        "confidence": (
            sum(r.confidence_usable for r in usable) / len(usable)
            if usable else math.nan
        ),
        "calibrated_score": sum(r.score for r in group) / len(group),
        "parse_failure_rate": sum(r.parse_failure for r in group) / len(group),
    }
    row["confidence_gap"] = row["confidence"] - row["accuracy"]
    return row


def cell_rows(records: list[Record]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
    for r in records:
        groups[(r.model, r.benchmark, r.arm)].append(r)
    rows = []
    for (model, benchmark, arm), group in sorted(groups.items()):
        row = {"model": model, "benchmark": benchmark, "arm": arm}
        row.update(metric_row(group))
        rows.append(row)
    return rows


def reliability_bins(records: list[Record]) -> list[dict]:
    """Pooled bins per arm, same rounding as the integrated study:
    round stated confidence to the nearest 0.1 (bin 0.0 means conf < 0.05)."""
    rows = []
    for arm in NEW_ARMS:
        bins: dict[float, list[Record]] = defaultdict(list)
        for r in records:
            if r.arm != arm or not r.usable:
                continue
            bins[min(1.0, math.floor(r.confidence_usable * 10 + 0.5) / 10)].append(r)
        for b in sorted(bins):
            group = bins[b]
            rows.append({
                "arm": arm, "confidence_bin": b,
                "responses": len(group),
                "mean_stated_confidence": (
                    sum(r.confidence_usable for r in group) / len(group)
                ),
                "accuracy": sum(r.correct_usable for r in group) / len(group),
            })
    return rows


def load_baseline_cells() -> dict[tuple[str, str, str], dict]:
    cells: dict[tuple[str, str, str], dict] = {}
    with BASELINE_CELLS.open() as handle:
        for row in csv.DictReader(handle):
            key = (row["model"], row["benchmark"], row["arm"])
            cells[key] = {
                field: float(row[field])
                for field in ("accuracy", "confidence", "confidence_gap",
                              "calibrated_score", "answer_rate")
            }
    for model in MODELS:
        for benchmark in BENCHMARKS:
            for arm in BASELINE_ARMS:
                if (model, benchmark, arm) not in cells:
                    raise ValueError(f"baseline cell missing: {model}/{benchmark}/{arm}")
    return cells


def load_rerun_control_cells() -> dict[tuple[str, str], dict]:
    """Aug 27 re-run control arm, corrected notation, keyed by (model, benchmark)."""
    cells: dict[tuple[str, str], dict] = {}
    if not RERUN_CELLS.exists():
        return cells
    with RERUN_CELLS.open() as handle:
        for row in csv.DictReader(handle):
            if row["study"] != "rerun" or row["arm"] != "control":
                continue
            cells[(row["model"], row["benchmark"])] = {
                "accuracy": float(row["corrected_accuracy"]),
                "confidence": float(row["corrected_confidence"]),
                "confidence_gap": float(row["corrected_confidence_gap"]),
                "calibrated_score": float(row["corrected_calibrated_score"]),
            }
    for model in MODELS:
        for benchmark in BENCHMARKS:
            if (model, benchmark) not in cells:
                raise ValueError(f"re-run control cell missing: {model}/{benchmark}")
    return cells


def arm_summary(cells: list[dict], arm: str) -> dict:
    selected = [row for row in cells if row["arm"] == arm]
    summary = {"arm": arm, "model_benchmark_cells": len(selected)}
    for measure in ("answer_rate", "usable_confidence_rate", "accuracy",
                    "confidence", "confidence_gap", "calibrated_score",
                    "parse_failure_rate"):
        summary[measure] = sum(row[measure] for row in selected) / len(selected)
    summary["mean_absolute_confidence_gap"] = (
        sum(abs(row["confidence_gap"]) for row in selected) / len(selected)
    )
    return summary


def contrast(new_cells: dict[tuple[str, str], dict],
             base_cells: dict[tuple[str, str], dict]) -> dict:
    """Cell-level paired contrast with a paired bootstrap over the 80 cells.

    The bootstrap resamples model-benchmark cells (the unit of the primary
    weighting) because the integrated study's item-level responses are no
    longer available for item-paired resampling.
    """
    pairs = [(new_cells[key], base_cells[key])
             for key in sorted(new_cells)]
    def deltas(sample: list[tuple[dict, dict]]) -> dict[str, float]:
        n = len(sample)
        return {
            "confidence": sum(a["confidence"] - b["confidence"] for a, b in sample) / n,
            "accuracy": sum(a["accuracy"] - b["accuracy"] for a, b in sample) / n,
            "signed_gap": sum(a["confidence_gap"] - b["confidence_gap"] for a, b in sample) / n,
            "absolute_gap": sum(
                abs(a["confidence_gap"]) - abs(b["confidence_gap"]) for a, b in sample
            ) / n,
            "calibrated_score": sum(
                a["calibrated_score"] - b["calibrated_score"] for a, b in sample
            ) / n,
        }
    point = deltas(pairs)
    rng = random.Random(BOOTSTRAP_SEED)
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        for measure, value in deltas(sample).items():
            draws[measure].append(value)
    result = {}
    for measure, value in point.items():
        ordered = sorted(draws[measure])
        result[measure] = {
            "delta": value,
            "ci_low": ordered[int(0.025 * BOOTSTRAP_DRAWS)],
            "ci_high": ordered[int(0.975 * BOOTSTRAP_DRAWS)],
        }
    result["cells_gap_closer"] = sum(
        abs(a["confidence_gap"]) < abs(b["confidence_gap"]) for a, b in pairs
    )
    result["cells_score_improved"] = sum(
        a["calibrated_score"] > b["calibrated_score"] for a, b in pairs
    )
    return result


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze the prompt-arm identification study.")
    parser.add_argument(
        "--extra-db", action="append", default=[], metavar="PATH",
        help="pool an additional response database with the frozen ones. "
             "Repeatable. The database must carry the same two arms, the same "
             "8 benchmarks and 100-item slices; new models in it must also be "
             "declared with --extra-model.")
    parser.add_argument(
        "--exclude-model", action="append", default=[], metavar="ID",
        help="drop every row of this model before analysis (repeatable): for "
             "a model whose battery is incomplete in a pooled database.")
    parser.add_argument(
        "--extra-model", action="append", default=[], metavar="ID",
        help="a model id that arrives with --extra-db. Repeatable. Extra "
             "models are validated and pooled into the cell table and the arm "
             "summaries; they are excluded from the baseline contrasts, which "
             "have committed cells only for the frozen ten.")
    return parser.parse_args(argv)


def _manifest_path(path: Path) -> str:
    """Repo-relative when we can, absolute otherwise: an extra database may
    legitimately sit outside the checkout, and provenance must not crash."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv=None) -> None:
    args = parse_args(argv)
    EXCLUDED_MODELS.update(args.exclude_model)

    # Extra databases extend the frozen tuple; with no flag `dbs` IS the frozen
    # tuple, so the outputs are byte-identical to the committed tables.
    dbs = list(DBS)
    for raw in args.extra_db:
        path = Path(raw).expanduser()
        if not path.exists():
            raise SystemExit(f"--extra-db not found: {path}")
        dbs.append(path)

    # Same for the model cohort. A duplicate is rejected rather than silently
    # deduplicated, because it would mean the caller believes a frozen model is
    # new and their expected-row arithmetic is wrong somewhere else too.
    models = list(MODELS)
    for model in args.extra_model:
        if model in models:
            raise SystemExit(f"--extra-model already frozen in MODELS: {model}")
        models.append(model)
    models = tuple(models)

    records = load_records(dbs)
    validate_matrix(records, models)
    cells = cell_rows(records)
    bins = reliability_bins(records)
    baseline = load_baseline_cells()

    summaries = [arm_summary(cells, arm) for arm in NEW_ARMS]
    by_key = {(row["model"], row["benchmark"], row["arm"]): row for row in cells}
    contrasts = {}
    for arm in NEW_ARMS:
        new_cells = {(m, b): by_key[(m, b, arm)] for m in MODELS for b in BENCHMARKS}
        for base_arm in BASELINE_ARMS:
            base_cells = {
                (m, b): baseline[(m, b, base_arm)] for m in MODELS for b in BENCHMARKS
            }
            contrasts[f"{arm}_vs_{base_arm}"] = contrast(new_cells, base_cells)
    rerun_control = load_rerun_control_cells()
    if rerun_control:
        for arm in NEW_ARMS:
            new_cells = {(m, b): by_key[(m, b, arm)] for m in MODELS for b in BENCHMARKS}
            contrasts[f"{arm}_vs_rerun_control"] = contrast(new_cells, rerun_control)

    total_cost = sum(r.cost_usd for r in records)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    fields = ["model", "benchmark", "arm", "responses", "answer_rate",
              "usable_confidence_rate", "accuracy", "confidence",
              "confidence_gap", "calibrated_score", "parse_failure_rate"]
    with (PROCESSED / "prompt_arm_identification_cells.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cells)
    with (PROCESSED / "prompt_arm_identification_reliability_bins.csv").open(
        "w", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "arm", "confidence_bin", "responses", "mean_stated_confidence", "accuracy",
        ])
        writer.writeheader()
        writer.writerows(bins)
    with (PROCESSED / "prompt_arm_identification_summary.json").open("w") as handle:
        json.dump({
            "arm_summaries": summaries,
            "contrasts_vs_integrated_cells": contrasts,
            "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
                          "unit": "model_benchmark_cell"},
        }, handle, indent=2)
    with (PROCESSED / "prompt_arm_identification_manifest.json").open("w") as handle:
        json.dump({
            "protocol": "notes/2026-08-27-prompt-arm-identification-protocol.md",
            "databases": [
                {"path": _manifest_path(p), "sha256": _sha256(p)} for p in dbs
            ],
            "responses": len(records),
            "total_cost_usd": round(total_cost, 4),
            "git_commit": _git_commit(),
            "baseline": str(BASELINE_CELLS.relative_to(ROOT)),
            "limitation": (
                f"Contrasts are cell-level ({len(MODELS) * len(BENCHMARKS)} model-benchmark cells), matching the "
                "integrated study's primary equal-cell weighting. The Aug 26 "
                "baseline and the Aug 27 arms were generated on different days, so "
                "the paired bootstrap understates between-run drift; the same-day "
                "re-run control contrast is reported alongside for that reason."
            ),
        }, handle, indent=2)

    for summary in summaries:
        print(f"{summary['arm']}: conf {summary['confidence']:.3f}  "
              f"acc {summary['accuracy']:.3f}  gap {summary['confidence_gap']:.3f}  "
              f"|gap| {summary['mean_absolute_confidence_gap']:.3f}  "
              f"score {summary['calibrated_score']:.3f}")
    # Contrasts are always over the frozen grid (80 cells), never the pooled
    # one, so this denominator does not move when --extra-model is used.
    contrast_cells = len(MODELS) * len(BENCHMARKS)
    for name, result in contrasts.items():
        c = result["confidence"]; g = result["absolute_gap"]; s = result["calibrated_score"]
        print(f"{name}: dConf {c['delta']:+.3f} ({c['ci_low']:+.3f}..{c['ci_high']:+.3f})  "
              f"d|gap| {g['delta']:+.3f} ({g['ci_low']:+.3f}..{g['ci_high']:+.3f})  "
              f"dScore {s['delta']:+.3f} ({s['ci_low']:+.3f}..{s['ci_high']:+.3f})  "
              f"closer {result['cells_gap_closer']}/{contrast_cells}  "
              f"score+ {result['cells_score_improved']}/{contrast_cells}")
    print(f"total spend in DBs: ${total_cost:.2f}")


if __name__ == "__main__":
    main()
