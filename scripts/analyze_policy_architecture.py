"""Compare embedded and external confidence-threshold policies.

This analysis uses a frozen matrix of matched confidence-only and
confidence-plus-cost checkpoints. It never calls a model. The item-level source
responses remain in the verified recovery archive; compact results and source
hashes are written to ``data/processed``.

The comparison keeps two experimental axes separate:

* training reward: quadratic confidence only versus quadratic plus assertion cost;
* deployment rule: the model's native answer/abstain choice versus a deterministic
  threshold applied to its saved probability.

Run from the repository root::

    python scripts/analyze_policy_architecture.py \
      --truth-ethics /path/to/tuned_truth_ethics_200/responses.jsonl \
      --bbq /path/to/tuned_bbq_500/responses.jsonl

No third-party packages are required.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def _portable_path(path: Path) -> str:
    """Manifest paths are labels; the sha256 recorded beside them is the
    identity. Record repo-relative (or sibling-archive-relative) strings so a
    committed manifest never contains an absolute home directory."""
    p = Path(path).resolve()
    for base in (ROOT, ROOT.parent):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return p.name

# The raw rollouts live in a recovery archive kept outside the repo, beside
# the checkout on the lab machine. The path is only a default label; the
# sha256 gate below is the real identity check, so a wrong or missing archive
# fails loudly rather than silently analysing the wrong files.
DEFAULT_ARCHIVE = ROOT.parent / "below-zero-recovery-20260821-final" / "raw" / "broader-eval"
DEFAULT_TRUTH_ETHICS = DEFAULT_ARCHIVE / "tuned_truth_ethics_200/responses.jsonl"
DEFAULT_BBQ = DEFAULT_ARCHIVE / "tuned_bbq_500/responses.jsonl"

EXPECTED_HASHES = {
    "truth_ethics": "14bde0a80b8eb51b3c5734d935afe65d473dc292f2115ed76eaf2f3908985795",
    "bbq": "8978d9f6c24b0eeee8d4464db01d0cbfa457947ae55e06d6e0b607f67149bd34",
}
EXPECTED_SEEDS = (0, 1, 2, 4, 5)
EXPECTED_COUNTS = {"truthfulqa_mc": 200, "ethics_hard": 200, "bbq": 500}
ARMS = ("quadratic", "quad_cost_0.09")
THRESHOLDS = (0.30, 0.50, 0.70, 0.80, 0.90)
PRIMARY_THRESHOLD = 0.30
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260824


def sha256_file(path: Path) -> str:
    """Hash a source artifact so later replays cannot silently change inputs."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_response(row: dict) -> dict:
    """Conservatively score a malformed attempted answer as maximally confident wrong.

    A deterministic filter must not gain an advantage merely because it cannot
    parse the probability. Assigning 100% makes the bad attempt pass every gate.
    The original fields remain alongside the normalized analysis fields.
    """
    normalized = dict(row)
    if row.get("failure") == "format" or not row.get("formatted"):
        normalized.update({
            "_format_failure": True,
            "_original_failure": row.get("failure"),
            "_original_formatted": row.get("formatted"),
            "_original_probability": row.get("probability"),
            "_original_outcome": row.get("outcome"),
            "failure": None,
            "formatted": True,
            "probability": 1.0,
            "outcome": "INCORRECT",
            "correct": False,
            "abstained": False,
        })
    else:
        normalized["_format_failure"] = False
    return normalized


def load_rows(paths: Sequence[Path]) -> list[dict]:
    """Read JSON Lines and retain the two matched training arms."""
    rows: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                row = normalize_response(json.loads(line))
                if row.get("arm") not in ARMS:
                    continue
                row["_source"] = str(path)
                row["_line"] = line_number
                rows.append(row)
    return rows


def validate_rows(rows: Sequence[dict]) -> None:
    """Fail closed on missing cells, duplicate identities, or unusable outputs."""
    seen: set[tuple] = set()
    counts: dict[tuple, int] = defaultdict(int)
    failures: list[str] = []

    for row in rows:
        key = (row.get("checkpoint"), row.get("benchmark"), row.get("item_id"),
               row.get("prompt_condition"), row.get("repetition"))
        if key in seen:
            raise ValueError(f"duplicate response identity: {key}")
        seen.add(key)

        seed = row.get("training_seed")
        arm = row.get("arm")
        benchmark = row.get("benchmark")
        counts[(seed, benchmark, arm)] += 1

        if row.get("failure") is not None:
            failures.append(f"generation failure at {key}: {row['failure']}")
        if not row.get("formatted"):
            failures.append(f"unformatted attempted response at {key}")
        if row.get("probability") is None:
            failures.append(f"missing probability at {key}")
        # Historical evaluators used NOT_ATTEMPTED; the broader-evaluation
        # runner uses ABSTAINED for the same explicit I-DON'T-KNOW action.
        if row.get("outcome") not in {
                "CORRECT", "INCORRECT", "NOT_ATTEMPTED", "ABSTAINED"}:
            failures.append(f"unknown outcome at {key}: {row.get('outcome')}")

    if failures:
        sample = "\n".join(failures[:10])
        raise ValueError(f"{len(failures)} unusable responses; first failures:\n{sample}")

    expected = {
        (seed, benchmark, arm): n
        for seed in EXPECTED_SEEDS
        for benchmark, n in EXPECTED_COUNTS.items()
        for arm in ARMS
    }
    if counts != expected:
        missing = {k: v for k, v in expected.items() if counts.get(k) != v}
        unexpected = {k: v for k, v in counts.items() if k not in expected}
        raise ValueError(f"cell count mismatch; missing/wrong={missing}, unexpected={unexpected}")


def native_action(row: dict) -> bool:
    """The embedded policy acts unless the model explicitly abstained."""
    return not bool(row["abstained"])


def threshold_action(row: dict, threshold: float) -> bool:
    """Code acts only when an answer exists and its probability clears the gate."""
    return native_action(row) and float(row["probability"]) >= threshold


def decision_metrics(rows: Sequence[dict], actions: Sequence[bool],
                     threshold: float) -> dict[str, float | int]:
    """Measure safety and utility with explicit per-question denominators."""
    if len(rows) != len(actions):
        raise ValueError("rows and actions must have the same length")
    n = len(rows)
    answered = sum(actions)
    correct = sum(bool(action and row["correct"])
                  for row, action in zip(rows, actions))
    wrong = answered - correct
    wrong_cost = threshold / (1.0 - threshold)
    return {
        "n": n,
        "answered": answered,
        "coverage": answered / n,
        "correct_answers": correct,
        "wrong_answers": wrong,
        "accuracy_when_answered": correct / answered if answered else math.nan,
        "correct_per_question": correct / n,
        "wrong_per_question": wrong / n,
        "wrong_cost_relative_to_correct": wrong_cost,
        "utility_per_question": (correct - wrong_cost * wrong) / n,
    }


def tie_key(seed: int, benchmark: str, item_id: str) -> str:
    """Break equal-probability ranks without consulting correctness."""
    value = f"{seed}|{benchmark}|{item_id}".encode()
    return hashlib.sha256(value).hexdigest()


def top_k_actions(rows: Sequence[dict], k: int, seed: int,
                  benchmark: str) -> list[bool]:
    """Retain exactly k native answers, ordered by confidence then a frozen hash."""
    eligible = [i for i, row in enumerate(rows) if native_action(row)]
    if k > len(eligible):
        raise ValueError(f"cannot select {k} actions from {len(eligible)} answers")
    ranked = sorted(
        eligible,
        key=lambda i: (-float(rows[i]["probability"]),
                       tie_key(seed, benchmark, str(rows[i]["item_id"])))
    )
    selected = set(ranked[:k])
    return [i in selected for i in range(len(rows))]


def group_rows(rows: Sequence[dict]) -> dict[tuple[int, str, str], list[dict]]:
    """Index rows by seed, benchmark, and training arm in stable item order."""
    grouped: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["training_seed"]), row["benchmark"], row["arm"])].append(row)
    for cell in grouped.values():
        cell.sort(key=lambda row: row["item_id"])
    return dict(grouped)


def primary_cells(grouped: dict[tuple[int, str, str], list[dict]]) -> list[dict]:
    """Compute the frozen 30% and matched-coverage comparisons in every cell."""
    out: list[dict] = []
    for seed in EXPECTED_SEEDS:
        for benchmark in EXPECTED_COUNTS:
            belief = grouped[(seed, benchmark, "quadratic")]
            embedded = grouped[(seed, benchmark, "quad_cost_0.09")]
            if [r["item_id"] for r in belief] != [r["item_id"] for r in embedded]:
                raise ValueError(f"item mismatch for seed {seed}, {benchmark}")

            embedded_actions = [native_action(row) for row in embedded]
            separated_actions = [threshold_action(row, PRIMARY_THRESHOLD)
                                 for row in belief]
            em = decision_metrics(embedded, embedded_actions, PRIMARY_THRESHOLD)
            sep = decision_metrics(belief, separated_actions, PRIMARY_THRESHOLD)

            # Use the largest action count both checkpoints can actually supply,
            # then apply the same external top-confidence policy to both arms.
            k = min(sum(native_action(row) for row in belief),
                    sum(native_action(row) for row in embedded))
            belief_matched_actions = top_k_actions(belief, k, seed, benchmark)
            embedded_matched_actions = top_k_actions(embedded, k, seed, benchmark)
            matched = decision_metrics(belief, belief_matched_actions,
                                       PRIMARY_THRESHOLD)
            embedded_matched = decision_metrics(embedded, embedded_matched_actions,
                                                PRIMARY_THRESHOLD)

            row = {"seed": seed, "benchmark": benchmark, "n": len(belief)}
            for prefix, metrics in (("embedded", em), ("separated", sep),
                                    ("embedded_matched", embedded_matched),
                                    ("separated_matched", matched)):
                for field in ("answered", "coverage", "accuracy_when_answered",
                              "correct_per_question", "wrong_per_question",
                              "utility_per_question"):
                    row[f"{prefix}_{field}"] = metrics[field]
            row.update({
                "utility_change": sep["utility_per_question"] - em["utility_per_question"],
                "wrong_change": sep["wrong_per_question"] - em["wrong_per_question"],
                "coverage_change": sep["coverage"] - em["coverage"],
                "matched_error_change": (
                    (1.0 - matched["accuracy_when_answered"])
                    - (1.0 - embedded_matched["accuracy_when_answered"])
                ),
                "matched_coverage_informative": k < len(embedded),
            })
            out.append(row)
    return out


def threshold_cells(grouped: dict[tuple[int, str, str], list[dict]]) -> list[dict]:
    """Build the two-training-arm by native/external-policy threshold grid."""
    out: list[dict] = []
    for seed in EXPECTED_SEEDS:
        for benchmark in EXPECTED_COUNTS:
            for arm in ARMS:
                rows = grouped[(seed, benchmark, arm)]
                for threshold in THRESHOLDS:
                    for policy in ("native", "external"):
                        actions = ([native_action(row) for row in rows]
                                   if policy == "native" else
                                   [threshold_action(row, threshold) for row in rows])
                        metrics = decision_metrics(rows, actions, threshold)
                        out.append({"seed": seed, "benchmark": benchmark,
                                    "arm": arm, "policy": policy,
                                    "threshold": threshold, **metrics})
    return out


def equal_benchmark_average(cells: Sequence[dict], field: str,
                            seed: int | None = None) -> float:
    """Average benchmark means equally so the 500-item BBQ set cannot dominate."""
    selected = [row for row in cells if seed is None or row["seed"] == seed]
    by_benchmark: dict[str, list[float]] = defaultdict(list)
    for row in selected:
        by_benchmark[row["benchmark"]].append(float(row[field]))
    return statistics.mean(statistics.mean(values)
                           for values in by_benchmark.values())


def aggregate_policy_rows(rows: Sequence[dict]) -> dict[str, float]:
    """Aggregate counts within benchmark, then weight the three benchmarks equally."""
    benchmark_metrics = []
    for benchmark in EXPECTED_COUNTS:
        selected = [row for row in rows if row["benchmark"] == benchmark]
        n = sum(int(row["n"]) for row in selected)
        answered = sum(int(row["answered"]) for row in selected)
        correct = sum(int(row["correct_answers"]) for row in selected)
        wrong = sum(int(row["wrong_answers"]) for row in selected)
        # Every selected row uses the same threshold and therefore the same
        # wrong-answer cost. Recover it from the first row for count-weighted utility.
        wrong_cost = float(selected[0]["wrong_cost_relative_to_correct"])
        benchmark_metrics.append({
            "coverage": answered / n,
            "accuracy_when_answered": correct / answered if answered else math.nan,
            "correct_per_question": correct / n,
            "wrong_per_question": wrong / n,
            "utility_per_question": (correct - wrong_cost * wrong) / n,
        })

    result = {}
    for field in benchmark_metrics[0]:
        finite = [row[field] for row in benchmark_metrics if math.isfinite(row[field])]
        result[field] = statistics.mean(finite) if finite else math.nan
    return result


def percentile(values: Sequence[float], q: float) -> float:
    """Return a linearly interpolated percentile without NumPy."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_intervals(grouped: dict[tuple[int, str, str], list[dict]],
                        draws: int = BOOTSTRAP_DRAWS,
                        seed: int = BOOTSTRAP_SEED) -> dict[str, dict[str, float]]:
    """Bootstrap paired outcomes under policy actions frozen from confidence.

    Confidence ranks and threshold actions do not use correctness, so a deployed
    policy would keep them fixed. Resampling the paired outcomes underneath those
    actions measures item uncertainty without repeatedly refitting the policy.
    """
    rng = random.Random(seed)
    fields = ("utility_change", "wrong_change", "coverage_change",
              "matched_error_change")
    estimates: dict[str, list[float]] = {field: [] for field in fields}

    prepared: dict[str, dict[int, dict[str, list[float | int]]]] = {}
    wrong_cost = PRIMARY_THRESHOLD / (1.0 - PRIMARY_THRESHOLD)
    for benchmark in EXPECTED_COUNTS:
        prepared[benchmark] = {}
        for training_seed in EXPECTED_SEEDS:
            belief = grouped[(training_seed, benchmark, "quadratic")]
            embedded = grouped[(training_seed, benchmark, "quad_cost_0.09")]
            separated_actions = [threshold_action(row, PRIMARY_THRESHOLD)
                                 for row in belief]
            embedded_actions = [native_action(row) for row in embedded]
            k = min(sum(native_action(row) for row in belief),
                    sum(native_action(row) for row in embedded))
            belief_matched = top_k_actions(belief, k, training_seed, benchmark)
            embedded_matched = top_k_actions(embedded, k, training_seed, benchmark)

            utility_delta = []
            wrong_delta = []
            coverage_delta = []
            for b_row, e_row, b_action, e_action in zip(
                    belief, embedded, separated_actions, embedded_actions):
                b_utility = (1.0 if b_row["correct"] else -wrong_cost) if b_action else 0.0
                e_utility = (1.0 if e_row["correct"] else -wrong_cost) if e_action else 0.0
                utility_delta.append(b_utility - e_utility)
                wrong_delta.append(int(b_action and not b_row["correct"])
                                   - int(e_action and not e_row["correct"]))
                coverage_delta.append(int(b_action) - int(e_action))

            prepared[benchmark][training_seed] = {
                "utility_delta": utility_delta,
                "wrong_delta": wrong_delta,
                "coverage_delta": coverage_delta,
                "belief_matched_action": [int(v) for v in belief_matched],
                "belief_matched_wrong": [int(a and not row["correct"])
                                           for row, a in zip(belief, belief_matched)],
                "embedded_matched_action": [int(v) for v in embedded_matched],
                "embedded_matched_wrong": [int(a and not row["correct"])
                                             for row, a in zip(embedded,
                                                               embedded_matched)],
            }

    for _ in range(draws):
        draw_values: dict[str, list[float]] = {field: [] for field in fields}
        for benchmark, n in EXPECTED_COUNTS.items():
            indices = [rng.randrange(n) for _ in range(n)]
            benchmark_values: dict[str, list[float]] = {
                field: [] for field in fields
            }
            for training_seed in EXPECTED_SEEDS:
                cell = prepared[benchmark][training_seed]
                benchmark_values["utility_change"].append(
                    sum(cell["utility_delta"][i] for i in indices) / n)
                benchmark_values["wrong_change"].append(
                    sum(cell["wrong_delta"][i] for i in indices) / n)
                benchmark_values["coverage_change"].append(
                    sum(cell["coverage_delta"][i] for i in indices) / n)

                b_answered = sum(cell["belief_matched_action"][i] for i in indices)
                e_answered = sum(cell["embedded_matched_action"][i] for i in indices)
                b_wrong = sum(cell["belief_matched_wrong"][i] for i in indices)
                e_wrong = sum(cell["embedded_matched_wrong"][i] for i in indices)
                benchmark_values["matched_error_change"].append(
                    b_wrong / b_answered - e_wrong / e_answered)

            for field in fields:
                draw_values[field].append(statistics.mean(benchmark_values[field]))

        for field in fields:
            estimates[field].append(statistics.mean(draw_values[field]))
    return {
        field: {"lower_95": percentile(values, 0.025),
                "upper_95": percentile(values, 0.975)}
        for field, values in estimates.items()
    }


def summarize(primary: Sequence[dict], thresholds: Sequence[dict],
              intervals: dict[str, dict[str, float]]) -> dict:
    """Create reader-facing headline estimates and the frozen verdict."""
    fields = ("utility_change", "wrong_change", "coverage_change",
              "matched_error_change")
    headline = {field: equal_benchmark_average(primary, field) for field in fields}
    seed_estimates = {
        str(seed): {field: equal_benchmark_average(primary, field, seed)
                    for field in fields}
        for seed in EXPECTED_SEEDS
    }
    utility_positive = sum(v["utility_change"] > 0 for v in seed_estimates.values())
    wrong_lower = sum(v["wrong_change"] < 0 for v in seed_estimates.values())
    point_pass = (headline["utility_change"] > 0 and headline["wrong_change"] < 0
                  and utility_positive >= 4 and wrong_lower >= 4)
    interval_pass = (intervals["utility_change"]["lower_95"] > 0
                     and intervals["wrong_change"]["upper_95"] < 0)
    verdict = ("STRONG_PASS" if point_pass and interval_pass else
               "DIRECTIONAL_PASS" if point_pass else "DOES_NOT_PASS")

    embedded_coverage = statistics.mean(float(r["embedded_coverage"]) for r in primary)
    informative = sum(bool(r["matched_coverage_informative"]) for r in primary)

    # Aggregate the full architecture comparison by equal benchmark weight.
    frontier = []
    policy_comparison = []
    for threshold in THRESHOLDS:
        selected = [r for r in thresholds
                    if r["arm"] == "quadratic" and r["policy"] == "external"
                    and r["threshold"] == threshold]
        values = aggregate_policy_rows(selected)
        frontier.append({"threshold": threshold,
                         "wrong_cost_relative_to_correct": threshold / (1-threshold),
                         **values})

        for approach, arm, policy in (
                ("embedded_cost_native", "quad_cost_0.09", "native"),
                ("separated_confidence_external", "quadratic", "external"),
                ("hybrid_cost_external", "quad_cost_0.09", "external"),
                ("confidence_native", "quadratic", "native")):
            rows = [r for r in thresholds if r["threshold"] == threshold
                    and r["arm"] == arm and r["policy"] == policy]
            policy_comparison.append({
                "threshold": threshold,
                "wrong_cost_relative_to_correct": threshold / (1-threshold),
                "approach": approach,
                **aggregate_policy_rows(rows),
            })

    return {
        "verdict": verdict,
        "primary_threshold": PRIMARY_THRESHOLD,
        "headline_equal_benchmark_weight": headline,
        "confidence_intervals_95": intervals,
        "seed_estimates": seed_estimates,
        "seed_direction_counts": {
            "higher_utility": utility_positive,
            "lower_wrong_exposure": wrong_lower,
            "seeds": len(EXPECTED_SEEDS),
        },
        "embedded_native_coverage": embedded_coverage,
        "embedded_threshold_expression": (
            "FAILED_TO_EXPRESS" if embedded_coverage >= 0.99 else "EXPRESSED"
        ),
        "matched_coverage_informative_cells": informative,
        "matched_coverage_total_cells": len(primary),
        "external_confidence_only_frontier": frontier,
        "policy_comparison": policy_comparison,
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
                      "scope": "paired items within benchmark; conditional on five seeds"},
    }


def write_csv(path: Path, rows: Sequence[dict]) -> None:
    """Persist rectangular evidence with stable field ordering."""
    if not rows:
        raise ValueError(f"refusing to write empty output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def git_head() -> str:
    """Record the code revision that launched the analysis."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def run(truth_ethics: Path, bbq: Path, draws: int = BOOTSTRAP_DRAWS,
        verify_hashes: bool = True) -> tuple[dict, list[dict], list[dict], dict]:
    """Validate, analyze, and return all processed artifacts."""
    paths = [truth_ethics, bbq]
    hashes = {"truth_ethics": sha256_file(truth_ethics), "bbq": sha256_file(bbq)}
    if verify_hashes and hashes != EXPECTED_HASHES:
        raise ValueError(f"source hash mismatch: observed={hashes}, expected={EXPECTED_HASHES}")

    rows = load_rows(paths)
    validate_rows(rows)
    grouped = group_rows(rows)
    primary = primary_cells(grouped)
    thresholds = threshold_cells(grouped)
    intervals = bootstrap_intervals(grouped, draws=draws)
    summary = summarize(primary, thresholds, intervals)
    summary["bootstrap"]["draws"] = draws

    manifest = {
        "schema_version": 1,
        "analysis_date": "2026-08-24",
        "source_files": {"truth_ethics": _portable_path(truth_ethics),
                         "bbq": _portable_path(bbq)},
        "source_sha256": hashes,
        "analysis_git_head": git_head(),
        "analysis_script_sha256": sha256_file(Path(__file__)),
        "model_family": "Qwen3 8B",
        "training_seeds": list(EXPECTED_SEEDS),
        "excluded_seed": {"seed": 3, "reason": "failed technical training gate"},
        "benchmarks": EXPECTED_COUNTS,
        "arms": list(ARMS),
        "relevant_responses": len(rows),
        "malformed_attempts_forced_wrong": sum(bool(row["_format_failure"])
                                                for row in rows),
        "full_preserved_matrix_responses": 16_200,
        "thresholds": list(THRESHOLDS),
        "cost_usd": 0.0,
        "protocol": "notes/2026-08-24-external-threshold-policy-protocol.md",
    }
    return summary, primary, thresholds, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth-ethics", type=Path, default=DEFAULT_TRUTH_ETHICS)
    parser.add_argument("--bbq", type=Path, default=DEFAULT_BBQ)
    parser.add_argument("--bootstrap-draws", type=int, default=BOOTSTRAP_DRAWS)
    args = parser.parse_args()

    summary, primary, thresholds, manifest = run(
        args.truth_ethics, args.bbq, draws=args.bootstrap_draws
    )
    PROCESSED.mkdir(parents=True, exist_ok=True)
    with (PROCESSED / "policy_architecture_summary.json").open(
            "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    with (PROCESSED / "policy_architecture_manifest.json").open(
            "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    write_csv(PROCESSED / "policy_architecture_cells.csv", primary)
    write_csv(PROCESSED / "policy_architecture_thresholds.csv", thresholds)
    print(json.dumps({"verdict": summary["verdict"],
                      "headline": summary["headline_equal_benchmark_weight"],
                      "embedded_native_coverage": summary["embedded_native_coverage"]},
                     indent=2))


if __name__ == "__main__":
    main()
