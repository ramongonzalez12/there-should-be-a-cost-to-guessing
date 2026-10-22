"""Test embedded prompt-time abstention against deterministic thresholding.

The preserved crossed evaluation applied three prompt contracts to the same
Qwen checkpoints and held-out items. This script uses the two relevant prompts:
quadratic confidence only, and quadratic confidence plus an assertion cost.
It makes no paid calls and writes a compact, hashed audit trail to
``data/processed``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import statistics
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from analyze_policy_architecture import (
    PRIMARY_THRESHOLD,
    _portable_path,
    decision_metrics,
    native_action,
    normalize_response,
    percentile,
    threshold_action,
)

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
# Recovery archive beside the repo checkout; the manifest's sha256 entries are
# the real identity check, the path is only a locator.
ARCHIVE = ROOT.parent / "below-zero-recovery-20260821-final"
SEED_ROOTS = {
    2: ARCHIVE / "raw" / "seed2",
    4: ARCHIVE / "untracked" / "finetune" / "runs" / "finetune"
       / "qwen_seed_replication_seed4",
    5: ARCHIVE / "untracked" / "finetune" / "runs" / "finetune"
       / "qwen_seed_replication_seed5",
}
DOSES = (125, 250, 300, 375, 500)
TRAINING_ARMS = ("quadratic", "quad_cost_0.09")
PROMPTS = ("quadratic", "quad_cost_0.09")
PRIMARY_DOSE = 500
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260824

EXPECTED_HASHES = {
    (2, 125): "fe30191f6dca0d08043075226c4417f7939f6fbfd476a0745ce51ae2824ffba7",
    (2, 250): "13a15be7ff83f7e3d9630dc1b2d6cbe0059346db27ca8a976de700834c95064b",
    (2, 300): "b2f60620f733bf5adc62539405fc11818da5cace6e73c924599a436c7b08da9d",
    (2, 375): "f0e3c946991565a6f9180eb436e9cc83aa81d7fff281791e1dc6f0eee6ce0fe6",
    (2, 500): "a8f4e19bdd2db3cb84c3da81986bc45f14415a03f5e0f8cd6221991c64f20bcd",
    (4, 125): "511411c5877e0b60f3087840f42693a79aecdfb8cc4bcdb2a55820b4290cf3b7",
    (4, 250): "4d7f4b10dbd8fc3265c9ab416fb1bf04ffaf12700fb2fd927e94d050b4e77046",
    (4, 300): "b6f6a9f3541997c2bab02bdd6a7ecf5b7ce3acf655130cc4289fe842f8d7ee26",
    (4, 375): "eabc0281afbd449d2a98e0f2cc7d7e48963a79cae56e8795020140f3a92392c5",
    (4, 500): "610ba75e1897453915718e5871be0e9ad8e3741804bc8af539658aebccabca58",
    (5, 125): "38a19c49be2b5cc23e02223bff4232d1c2c4cbbdcdb0c2b83d45dfd6ea86a751",
    (5, 250): "ddadca6c1f4cddab1151001d2627fd4fec1af32e5b1d42301b79e08ec8280617",
    (5, 300): "0124f29a8390558db18d66364e7a20c9ec483602a268e682c8b53ba543cca766",
    (5, 375): "adf0784393559313fc61307d1e21509e319c51476a64741452db395d6235dad2",
    (5, 500): "a970d02dddf22bc2c18b3ab1cd568b04ff0f56b53c7754ef1c258b6e00754fd9",
}


def source_path(seed: int, dose: int) -> Path:
    """Resolve one immutable crossed-prompt response file."""
    return SEED_ROOTS[seed] / f"evaluation_step_{dose}_crossed" / "responses.jsonl"


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for source verification."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows() -> tuple[list[dict], dict[str, str]]:
    """Load only the frozen two-by-two prompt and training comparison."""
    rows: list[dict] = []
    hashes: dict[str, str] = {}
    for seed in SEED_ROOTS:
        for dose in DOSES:
            path = source_path(seed, dose)
            observed_hash = sha256_file(path)
            if observed_hash != EXPECTED_HASHES[(seed, dose)]:
                raise ValueError(
                    f"source hash mismatch for seed {seed}, dose {dose}: "
                    f"{observed_hash}"
                )
            hashes[f"seed{seed}_step{dose}"] = observed_hash
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    original = json.loads(line)
                    if (original.get("checkpoint") not in TRAINING_ARMS or
                            original.get("prompt_condition") not in PROMPTS):
                        continue
                    row = normalize_response(original)
                    row["_source"] = str(path)
                    row["_line"] = line_number
                    rows.append(row)
    return rows, hashes


def validate_rows(rows: Sequence[dict]) -> list[str]:
    """Fail closed unless every paired cell contains the same 100 items."""
    expected_cells = {
        (seed, dose, arm, prompt)
        for seed in SEED_ROOTS
        for dose in DOSES
        for arm in TRAINING_ARMS
        for prompt in PROMPTS
    }
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    identities: set[tuple] = set()
    for row in rows:
        cell = (int(row["training_seed"]), int(row["dose"]),
                row["checkpoint"], row["prompt_condition"])
        identity = (*cell, row["item_id"], row.get("repetition"))
        if identity in identities:
            raise ValueError(f"duplicate response identity: {identity}")
        identities.add(identity)
        grouped[cell].append(row)
        if row.get("failure") is not None or not row.get("formatted"):
            raise ValueError(f"unhandled invalid response: {identity}")
        if row.get("probability") is None or row.get("correct") is None:
            raise ValueError(f"missing analysis field: {identity}")

    if set(grouped) != expected_cells:
        raise ValueError(f"crossed cell mismatch: {set(grouped) ^ expected_cells}")
    for cell, cell_rows in grouped.items():
        if len(cell_rows) != 100:
            raise ValueError(f"expected 100 rows in {cell}, found {len(cell_rows)}")

    item_sets = {cell: {row["item_id"] for row in cell_rows}
                 for cell, cell_rows in grouped.items()}
    reference = next(iter(item_sets.values()))
    if len(reference) != 100:
        raise ValueError(f"expected 100 unique item identities, found {len(reference)}")
    mismatches = [cell for cell, item_ids in item_sets.items()
                  if item_ids != reference]
    if mismatches:
        raise ValueError(f"item pairing differs in {mismatches}")
    return sorted(reference)


def group_rows(rows: Sequence[dict]) -> dict[tuple, list[dict]]:
    """Index responses in stable item order for paired contrasts."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (int(row["training_seed"]), int(row["dose"]),
               row["checkpoint"], row["prompt_condition"])
        grouped[key].append(row)
    for cell in grouped.values():
        cell.sort(key=lambda row: row["item_id"])
    return dict(grouped)


def comparison_cells(grouped: dict[tuple, list[dict]]) -> list[dict]:
    """Compute within-checkpoint embedded-minus-external policy levels."""
    out: list[dict] = []
    for seed in SEED_ROOTS:
        for dose in DOSES:
            for arm in TRAINING_ARMS:
                confidence_rows = grouped[(seed, dose, arm, "quadratic")]
                embedded_rows = grouped[(seed, dose, arm, "quad_cost_0.09")]
                if [r["item_id"] for r in confidence_rows] != [
                        r["item_id"] for r in embedded_rows]:
                    raise ValueError(f"item order mismatch: {seed}, {dose}, {arm}")

                separated_actions = [threshold_action(row, PRIMARY_THRESHOLD)
                                     for row in confidence_rows]
                confidence_native_actions = [native_action(row)
                                             for row in confidence_rows]
                embedded_actions = [native_action(row) for row in embedded_rows]
                separated = decision_metrics(
                    confidence_rows, separated_actions, PRIMARY_THRESHOLD)
                confidence_native = decision_metrics(
                    confidence_rows, confidence_native_actions, PRIMARY_THRESHOLD)
                embedded = decision_metrics(
                    embedded_rows, embedded_actions, PRIMARY_THRESHOLD)

                record = {"seed": seed, "dose": dose, "training_arm": arm,
                          "n": len(confidence_rows)}
                for prefix, metrics in (("embedded", embedded),
                                        ("confidence_native", confidence_native),
                                        ("separated", separated)):
                    for field in ("answered", "coverage", "accuracy_when_answered",
                                  "correct_per_question", "wrong_per_question",
                                  "utility_per_question"):
                        record[f"{prefix}_{field}"] = metrics[field]
                record.update({
                    "utility_change": (separated["utility_per_question"]
                                       - embedded["utility_per_question"]),
                    "wrong_change": (separated["wrong_per_question"]
                                     - embedded["wrong_per_question"]),
                    "coverage_change": separated["coverage"] - embedded["coverage"],
                    "prompt_only_utility_change": (
                        confidence_native["utility_per_question"]
                        - embedded["utility_per_question"]),
                    "prompt_only_wrong_change": (
                        confidence_native["wrong_per_question"]
                        - embedded["wrong_per_question"]),
                    "gate_marginal_utility_change": (
                        separated["utility_per_question"]
                        - confidence_native["utility_per_question"]),
                    "gate_marginal_wrong_change": (
                        separated["wrong_per_question"]
                        - confidence_native["wrong_per_question"]),
                    "embedded_format_failures": sum(
                        bool(row["_format_failure"]) for row in embedded_rows),
                    "separated_format_failures": sum(
                        bool(row["_format_failure"]) for row in confidence_rows),
                })
                out.append(record)
    return out


def mean_field(rows: Sequence[dict], field: str) -> float:
    """Average a field without weighting one checkpoint more than another."""
    return statistics.mean(float(row[field]) for row in rows)


def bootstrap_primary(grouped: dict[tuple, list[dict]], draws: int) -> dict:
    """Bootstrap paired items while keeping seeds as the independent unit."""
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = {field: [] for field in
                 ("utility_change", "wrong_change", "coverage_change",
                  "prompt_only_utility_change", "prompt_only_wrong_change",
                  "gate_marginal_utility_change", "gate_marginal_wrong_change")}
    for _ in range(draws):
        indices = [rng.randrange(100) for _ in range(100)]
        seed_values: dict[str, list[float]] = {
            field: [] for field in estimates
        }
        for seed in SEED_ROOTS:
            arm_values: dict[str, list[float]] = {
                field: [] for field in estimates
            }
            for arm in TRAINING_ARMS:
                confidence = grouped[(seed, PRIMARY_DOSE, arm, "quadratic")]
                embedded = grouped[(seed, PRIMARY_DOSE, arm, "quad_cost_0.09")]
                confidence_draw = [confidence[i] for i in indices]
                embedded_draw = [embedded[i] for i in indices]
                separated_actions = [threshold_action(row, PRIMARY_THRESHOLD)
                                     for row in confidence_draw]
                confidence_native_actions = [native_action(row)
                                             for row in confidence_draw]
                embedded_actions = [native_action(row) for row in embedded_draw]
                separated_metrics = decision_metrics(
                    confidence_draw, separated_actions, PRIMARY_THRESHOLD)
                confidence_native_metrics = decision_metrics(
                    confidence_draw, confidence_native_actions, PRIMARY_THRESHOLD)
                embedded_metrics = decision_metrics(
                    embedded_draw, embedded_actions, PRIMARY_THRESHOLD)
                arm_values["utility_change"].append(
                    separated_metrics["utility_per_question"]
                    - embedded_metrics["utility_per_question"])
                arm_values["wrong_change"].append(
                    separated_metrics["wrong_per_question"]
                    - embedded_metrics["wrong_per_question"])
                arm_values["coverage_change"].append(
                    separated_metrics["coverage"] - embedded_metrics["coverage"])
                arm_values["prompt_only_utility_change"].append(
                    confidence_native_metrics["utility_per_question"]
                    - embedded_metrics["utility_per_question"])
                arm_values["prompt_only_wrong_change"].append(
                    confidence_native_metrics["wrong_per_question"]
                    - embedded_metrics["wrong_per_question"])
                arm_values["gate_marginal_utility_change"].append(
                    separated_metrics["utility_per_question"]
                    - confidence_native_metrics["utility_per_question"])
                arm_values["gate_marginal_wrong_change"].append(
                    separated_metrics["wrong_per_question"]
                    - confidence_native_metrics["wrong_per_question"])
            for field in estimates:
                seed_values[field].append(statistics.mean(arm_values[field]))
        for field, values in estimates.items():
            values.append(statistics.mean(seed_values[field]))
    return {
        field: {"lower_95": percentile(values, 0.025),
                "upper_95": percentile(values, 0.975)}
        for field, values in estimates.items()
    }


def well_formatted_sensitivity(grouped: dict[tuple, list[dict]]) -> dict:
    """Describe the primary contrast where both paired outputs parsed.

    This is a post-result mechanism diagnostic, not a replacement estimand. The
    complex prompt's formatting failures are themselves policy outcomes, so
    dropping them selects on a treatment consequence. Reporting the restricted
    result only shows whether formatting accounts for the entire primary gap.
    """
    cell_changes: list[dict] = []
    paired_responses = 0
    for seed in SEED_ROOTS:
        for arm in TRAINING_ARMS:
            confidence = grouped[(seed, PRIMARY_DOSE, arm, "quadratic")]
            embedded = grouped[(seed, PRIMARY_DOSE, arm, "quad_cost_0.09")]
            pairs = [(c_row, e_row) for c_row, e_row in zip(confidence, embedded)
                     if not c_row["_format_failure"] and
                     not e_row["_format_failure"]]
            confidence_kept = [c_row for c_row, _ in pairs]
            embedded_kept = [e_row for _, e_row in pairs]
            paired_responses += len(pairs)
            separated = decision_metrics(
                confidence_kept,
                [threshold_action(row, PRIMARY_THRESHOLD)
                 for row in confidence_kept],
                PRIMARY_THRESHOLD,
            )
            embedded_metrics = decision_metrics(
                embedded_kept,
                [native_action(row) for row in embedded_kept],
                PRIMARY_THRESHOLD,
            )
            cell_changes.append({
                "utility_change": (separated["utility_per_question"]
                                   - embedded_metrics["utility_per_question"]),
                "wrong_change": (separated["wrong_per_question"]
                                 - embedded_metrics["wrong_per_question"]),
                "coverage_change": separated["coverage"] - embedded_metrics["coverage"],
            })
    return {
        "status": "post_result_mechanism_diagnostic_not_primary",
        "paired_item_checkpoint_responses": paired_responses,
        **{field: mean_field(cell_changes, field)
           for field in ("utility_change", "wrong_change", "coverage_change")},
    }


def summarize(cells: Sequence[dict], intervals: dict) -> dict:
    """Aggregate the frozen primary and dose-consistency verdicts."""
    primary = [row for row in cells if row["dose"] == PRIMARY_DOSE]
    headline = {field: mean_field(primary, field) for field in
                ("utility_change", "wrong_change", "coverage_change",
                 "prompt_only_utility_change", "prompt_only_wrong_change",
                 "gate_marginal_utility_change", "gate_marginal_wrong_change")}
    for prefix in ("embedded", "confidence_native", "separated"):
        for field in ("coverage", "accuracy_when_answered",
                      "wrong_per_question", "utility_per_question"):
            headline[f"{prefix}_{field}"] = mean_field(
                primary, f"{prefix}_{field}")
    headline["embedded_format_failures"] = sum(
        int(row["embedded_format_failures"]) for row in primary)
    headline["separated_format_failures"] = sum(
        int(row["separated_format_failures"]) for row in primary)

    seed_estimates = {}
    for seed in SEED_ROOTS:
        selected = [row for row in primary if row["seed"] == seed]
        seed_estimates[str(seed)] = {
            field: mean_field(selected, field)
            for field in ("utility_change", "wrong_change", "coverage_change")
        }
    favorable_seed_counts = {
        "higher_utility": sum(v["utility_change"] > 0
                              for v in seed_estimates.values()),
        "lower_wrong_exposure": sum(v["wrong_change"] < 0
                                    for v in seed_estimates.values()),
        "seeds": len(seed_estimates),
    }

    seed_dose = []
    for seed in SEED_ROOTS:
        for dose in DOSES:
            selected = [row for row in cells
                        if row["seed"] == seed and row["dose"] == dose]
            seed_dose.append({"seed": seed, "dose": dose,
                              **{field: mean_field(selected, field)
                                 for field in ("utility_change", "wrong_change",
                                               "coverage_change")}})
    dose_counts = {
        "higher_utility": sum(row["utility_change"] > 0 for row in seed_dose),
        "lower_wrong_exposure": sum(row["wrong_change"] < 0 for row in seed_dose),
        "seed_dose_cells": len(seed_dose),
        "independent_seeds": len(SEED_ROOTS),
    }

    point_pass = (headline["utility_change"] > 0 and
                  headline["wrong_change"] < 0 and
                  favorable_seed_counts["higher_utility"] >= 2 and
                  favorable_seed_counts["lower_wrong_exposure"] >= 2)
    interval_pass = (intervals["utility_change"]["lower_95"] > 0 and
                     intervals["wrong_change"]["upper_95"] < 0)
    verdict = ("STRONG_PASS" if point_pass and interval_pass else
               "DIRECTIONAL_PASS" if point_pass else "DOES_NOT_PASS")
    return {
        "verdict": verdict,
        "primary_dose": PRIMARY_DOSE,
        "primary_threshold": PRIMARY_THRESHOLD,
        "headline": headline,
        "confidence_intervals_95": intervals,
        "seed_estimates": seed_estimates,
        "favorable_seed_counts": favorable_seed_counts,
        "dose_consistency": dose_counts,
        "seed_dose_estimates": seed_dose,
        "bootstrap": {"draws": BOOTSTRAP_DRAWS,
                      "seed": BOOTSTRAP_SEED,
                      "scope": "paired held-out items; conditional on three seeds"},
    }


def git_head() -> str:
    """Record the source revision used for the analysis."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def write_csv(path: Path, rows: Sequence[dict]) -> None:
    """Write a rectangular audit table with stable column ordering."""
    if not rows:
        raise ValueError(f"refusing to write empty output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows, hashes = load_rows()
    item_ids = validate_rows(rows)
    grouped = group_rows(rows)
    cells = comparison_cells(grouped)
    intervals = bootstrap_primary(grouped, BOOTSTRAP_DRAWS)
    summary = summarize(cells, intervals)
    summary["well_formatted_pair_sensitivity"] = well_formatted_sensitivity(grouped)
    manifest = {
        "schema_version": 1,
        "analysis_date": "2026-08-24",
        "analysis_git_head": git_head(),
        "analysis_script_sha256": sha256_file(Path(__file__)),
        "protocol": "notes/2026-08-24-prompt-threshold-factorial-protocol.md",
        "model_family": "Qwen3 8B",
        "training_seeds": list(SEED_ROOTS),
        "training_doses": list(DOSES),
        "training_arms": list(TRAINING_ARMS),
        "prompt_conditions": list(PROMPTS),
        "held_out_benchmark": "mmlu_pro",
        "held_out_items": len(item_ids),
        "relevant_responses": len(rows),
        "source_files": {f"seed{seed}_step{dose}": _portable_path(source_path(seed, dose))
                         for seed in SEED_ROOTS for dose in DOSES},
        "source_sha256": hashes,
        "malformed_attempts_forced_wrong": sum(
            bool(row["_format_failure"]) for row in rows),
        "cost_usd": 0.0,
    }

    PROCESSED.mkdir(parents=True, exist_ok=True)
    with (PROCESSED / "prompt_threshold_factorial_summary.json").open(
            "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    with (PROCESSED / "prompt_threshold_factorial_manifest.json").open(
            "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    write_csv(PROCESSED / "prompt_threshold_factorial_cells.csv", cells)
    print(json.dumps({"verdict": summary["verdict"],
                      "headline": summary["headline"],
                      "favorable_seed_counts": summary["favorable_seed_counts"],
                      "dose_consistency": summary["dose_consistency"]}, indent=2))


if __name__ == "__main__":
    main()
