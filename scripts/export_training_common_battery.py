#!/usr/bin/env python3
"""Export the matched eight-benchmark evaluation of trained checkpoints.

The model families were evaluated separately, but all use the same 800 frozen
question identities. Each retains its native training-time renderer and
answer-plus-probability contract. This exporter keeps response-level
denominators explicit and only forms training contrasts within a family and
training seed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
PROMPT_DB = ROOT / "runs" / "matched_prompt_interventions_8b20b_20260831.db"
RUNS = {
    "Qwen3 8B": ROOT / "runs" / "evaluations" / "training_common_battery_qwen_native2048_20260831",
    "GPT-OSS 20B": ROOT / "runs" / "evaluations" / "training_common_battery_gptoss_native_20260831",
}
# The third family (protocol notes/2026-09-06-nemotron-common-battery.md) is
# wired here ahead of its paid evaluation. `runs/` is gitignored, so on any
# checkout without that directory the family simply does not exist and this
# exporter reproduces today's CSVs unchanged. Adding it unconditionally would
# make the export fail on every machine until the run lands.
NEMOTRON_RUN = ROOT / "runs" / "evaluations" / "training_common_battery_nemotron_20260906"
if (NEMOTRON_RUN / "evaluation.json").exists():
    RUNS["Nemotron 3 Nano 30B"] = NEMOTRON_RUN
# Each family's untuned reference is whatever its reward arms actually branched
# from, and that differs by family. Qwen3 8B's arms branch from the raw
# pretrained model. GPT-OSS 20B and Nemotron 3 Nano 30B both failed the response
# format gate untouched, so both were given a knowledge-free syntax-only warm-up
# first and both reward arms branch from THAT checkpoint. Calling either one
# "raw_base" would overstate what the training contrast controls for, so the
# control type is named per family instead of hard-coded in the row builder.
CONTROL_TYPES = {
    "Qwen3 8B": "raw_base",
    "GPT-OSS 20B": "shared_format_control",
    "Nemotron 3 Nano 30B": "shared_format_control",
}
PROMPT_RUNS = {
    "Qwen3 8B": ROOT / "runs" / "evaluations" / "training_prompt_common_battery_qwen_native2048_20260831",
    "GPT-OSS 20B": ROOT / "runs" / "evaluations" / "training_prompt_common_battery_gptoss_native_20260831",
}
TRAINING_BENCHMARK_OVERRIDES = {
    "Qwen3 8B": {
        "math500": (
            ROOT
            / "runs"
            / "evaluations"
            / "training_common_battery_qwen_math4096_20260831",
        )
    },
    "GPT-OSS 20B": {
        "ethics_hard": tuple(
            ROOT
            / "runs"
            / "evaluations"
            / f"training_common_battery_gptoss_ethics_s{shard}_20260831"
            for shard in range(3)
        ) + (
            ROOT
            / "runs"
            / "evaluations"
            / "training_common_battery_gptoss_ethics_missing_20260831",
        ),
        "bbq": tuple(
            ROOT
            / "runs"
            / "evaluations"
            / f"training_common_battery_gptoss_bbq_s{shard}_20260831"
            for shard in range(3)
        ) + (
            ROOT
            / "runs"
            / "evaluations"
            / "training_common_battery_gptoss_bbq_missing_20260831",
        ),
    },
}
PROMPT_BENCHMARK_OVERRIDES = {
    "Qwen3 8B": {
        "math500": (
            ROOT
            / "runs"
            / "evaluations"
            / "training_prompt_common_battery_qwen_math4096_20260831",
        )
    }
}
PROMPT_CONDITIONS = ("native_control", "native_rule", "native_direct")
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
ITEMS_PER_BENCHMARK = 100


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def metrics(rows: list[dict[str, object]]) -> dict[str, float | int]:
    """Calculate the essay's three endpoints from one scheduled cohort."""
    n = len(rows)
    usable = [
        row
        for row in rows
        if row["outcome"] in {"CORRECT", "INCORRECT"}
        and row.get("probability") is not None
    ]
    correct = sum(row["outcome"] == "CORRECT" for row in usable)
    confidence = sum(float(row["probability"]) for row in usable)
    high_confidence_errors = sum(
        row["outcome"] == "INCORRECT"
        and row.get("probability") is not None
        and float(row["probability"]) >= 0.90
        for row in rows
    )
    accuracy = correct / len(usable) if usable else 0.0
    mean_confidence = confidence / len(usable) if usable else 0.0
    return {
        "scheduled_n": n,
        "usable_attempt_n": len(usable),
        "answer_rate": len(usable) / n,
        "accuracy_on_usable_attempts": accuracy,
        "mean_confidence_on_usable_attempts": mean_confidence,
        "signed_overconfidence_gap": mean_confidence - accuracy,
        "confidence_adjusted_accuracy": sum(
            float(row["scores"]["quadratic"]) for row in rows
        )
        / n,
        "high_confidence_error_90_count": high_confidence_errors,
        "high_confidence_error_90_rate": high_confidence_errors / n,
        "invalid_rate": sum(row["outcome"] == "INVALID" for row in rows) / n,
        "abstention_rate": sum(row["outcome"] == "ABSTAINED" for row in rows) / n,
    }


def mean(rows: list[dict[str, object]], column: str) -> float:
    return sum(float(row[column]) for row in rows) / len(rows)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty export: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def source_entry(
    family: str,
    run_dir: Path,
    *,
    study: str,
    replaced_benchmark: str = "",
) -> dict[str, object]:
    """Record every source artifact, including benchmark-level replacements."""
    evaluation = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
    spend = json.loads((run_dir / "spend.json").read_text(encoding="utf-8"))
    return {
        "model_family": family,
        "study": study,
        "status": evaluation.get("status"),
        "replaced_benchmark": replaced_benchmark,
        "run_dir": str(run_dir.relative_to(ROOT)),
        "responses": len(read_jsonl(run_dir / "responses.jsonl")),
        "spent_usd": spend["spent_usd"],
        "cap_usd": spend["cap_usd"],
        "checkpoints": evaluation["design"]["checkpoints"],
        "items_sha256": evaluation["design"]["items_sha256"],
        "max_tokens": evaluation["design"]["max_tokens"],
        "responses_sha256": sha256(run_dir / "responses.jsonl"),
        "evaluation_sha256": sha256(run_dir / "evaluation.json"),
    }


def prompt_item_pairs() -> set[tuple[str, str]]:
    connection = sqlite3.connect(PROMPT_DB)
    pairs = {
        (str(benchmark), str(item_id))
        for benchmark, item_id in connection.execute(
            "SELECT DISTINCT benchmark, item_id FROM answers"
        )
    }
    connection.close()
    return pairs


# The second training programme (2026-09-12): three families x five seed
# pairs, one recipe, evaluated on this battery by the checkpoint-grid evaluation
# into one run directory per family, base included, no benchmark overrides.
# Qwen's precedent ceiling on this battery (2,048 tokens, 4,096 on MATH-500)
# makes its re-run about $14, so `--qwen-shared reuse` keeps the first
# programme's Qwen rows (same recipe, five pairs, same 800 items) and only
# GPT-OSS and Nemotron come from the new run.
SECOND_PROGRAMME = ROOT / "runs" / "finetune" / "second_programme_v1"
SECOND_RUNS = {
    "Qwen3 8B": SECOND_PROGRAMME / "qwen" / "eval_shared_battery",
    "GPT-OSS 20B": SECOND_PROGRAMME / "gpt_oss" / "eval_shared_battery",
    "Nemotron 3 Nano 30B": SECOND_PROGRAMME / "nemotron" / "eval_shared_battery",
}
SECOND_PROMPT_RUNS = {
    "Nemotron 3 Nano 30B": SECOND_PROGRAMME / "nemotron" / "eval_control_prompt_arms",
}


def configure(programme: str, qwen_shared: str) -> None:
    """Point the module's run tables at the chosen programme (in place, so the
    loops below and the manifest read one set of tables)."""
    if programme == "first":
        return
    for family, run_dir in SECOND_RUNS.items():
        if family == "Qwen3 8B" and qwen_shared == "reuse":
            continue
        if not (run_dir / "evaluation.json").exists():
            raise SystemExit(f"second programme: {run_dir.relative_to(ROOT)} has no "
                             "evaluation.json yet; nothing written")
        RUNS[family] = run_dir
        # A fresh single run carries every benchmark at one ceiling; the
        # first programme's per-benchmark replacements do not apply to it.
        TRAINING_BENCHMARK_OVERRIDES.pop(family, None)
    for family, run_dir in SECOND_PROMPT_RUNS.items():
        if (run_dir / "evaluation.json").exists():
            PROMPT_RUNS[family] = run_dir


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Shared-battery training exports.")
    parser.add_argument("--programme", choices=("first", "second"), default="first",
                        help="which training programme's shared-battery runs to read "
                             "(default: the first, reproducing the committed tables)")
    parser.add_argument("--qwen-shared", choices=("reuse", "second"), default="reuse",
                        help="with --programme second: reuse the first programme's Qwen "
                             "rows (default) or read Qwen's second-programme run")
    parser.add_argument("--out-suffix", default="",
                        help="suffix for every output file name, e.g. _first_programme, "
                             "so one programme's tables can sit beside another's")
    args = parser.parse_args(argv)
    configure(args.programme, args.qwen_shared)
    suffix = args.out_suffix
    PROCESSED.mkdir(parents=True, exist_ok=True)
    cell_rows: list[dict[str, object]] = []
    source_manifest: list[dict[str, object]] = []
    common_items: set[tuple[str, str]] | None = None

    for family, run_dir in RUNS.items():
        evaluation = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
        training_overrides = TRAINING_BENCHMARK_OVERRIDES.get(family, {})
        if (
            evaluation.get("status") not in {"COMPLETE", "COMPLETED"}
            and not training_overrides
        ):
            raise ValueError(f"{family} evaluation is not complete")
        responses = read_jsonl(run_dir / "responses.jsonl")
        items = read_jsonl(run_dir / "items.jsonl")
        item_pairs = {(str(row["benchmark"]), str(row["item_id"])) for row in items}
        if len(item_pairs) != len(BENCHMARKS) * ITEMS_PER_BENCHMARK:
            raise ValueError(f"{family} does not contain 800 unique benchmark items")
        if common_items is None:
            common_items = item_pairs
        elif item_pairs != common_items:
            raise ValueError("the two training families do not share question identities")

        checkpoints = evaluation["design"]["checkpoints"]
        for benchmark, override_dirs in training_overrides.items():
            override_pairs: set[tuple[str, str]] = set()
            override_response_map: dict[
                tuple[str, str, str, int], dict[str, object]
            ] = {}
            for override_dir in override_dirs:
                override_evaluation = json.loads(
                    (override_dir / "evaluation.json").read_text(encoding="utf-8")
                )
                if override_evaluation.get("status") not in {"COMPLETE", "COMPLETED"}:
                    raise ValueError(f"{family}/{benchmark} replacement is not complete")
                if override_evaluation["design"]["checkpoints"] != checkpoints:
                    raise ValueError(f"{family}/{benchmark} replacement changed checkpoints")
                override_items = read_jsonl(override_dir / "items.jsonl")
                shard_pairs = {
                    (str(row["benchmark"]), str(row["item_id"]))
                    for row in override_items
                }
                override_pairs.update(shard_pairs)
                for row in read_jsonl(override_dir / "responses.jsonl"):
                    identity = (
                        str(row["item_id"]),
                        str(row["checkpoint"]),
                        str(row["prompt_condition"]),
                        int(row["repetition"]),
                    )
                    # Offset shards can overlap because the loader stratifies
                    # each requested slice independently. Paths are ordered,
                    # so retain the first complete response for each identity;
                    # the exclusion-backed final shard supplies every missing
                    # identity without replacing an observed one.
                    override_response_map.setdefault(identity, row)
                source_manifest.append(
                    source_entry(
                        family,
                        override_dir,
                        study="tinker_native_training_benchmark_replacement",
                        replaced_benchmark=benchmark,
                    )
                )
            expected_pairs = {pair for pair in item_pairs if pair[0] == benchmark}
            if override_pairs != expected_pairs:
                raise ValueError(f"{family}/{benchmark} replacement changed item identities")
            override_responses = list(override_response_map.values())
            if len(override_responses) != len(checkpoints) * ITEMS_PER_BENCHMARK:
                raise ValueError(f"{family}/{benchmark} replacement is incomplete")
            if any(str(row["benchmark"]) != benchmark for row in override_responses):
                raise ValueError(f"{family}/{benchmark} replacement contains another benchmark")
            responses = [
                row for row in responses if str(row["benchmark"]) != benchmark
            ] + override_responses
        expected = len(checkpoints) * len(item_pairs)
        if len(responses) != expected:
            raise ValueError(f"{family}: expected {expected:,} responses, found {len(responses):,}")
        grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        for row in responses:
            grouped[(str(row["checkpoint"]), str(row["benchmark"]))].append(row)
        for checkpoint, metadata in checkpoints.items():
            for benchmark in BENCHMARKS:
                rows = grouped[(checkpoint, benchmark)]
                if len(rows) != ITEMS_PER_BENCHMARK:
                    raise ValueError(f"incomplete cell: {family}/{checkpoint}/{benchmark}")
                cell_rows.append(
                    {
                        "model_family": family,
                        "checkpoint": checkpoint,
                        "training_objective": metadata["arm"],
                        "training_seed": metadata.get("training_seed", ""),
                        "control_type": (
                            CONTROL_TYPES[family]
                            if metadata["arm"] == "base"
                            else "trained"
                        ),
                        "benchmark": benchmark,
                        **metrics(rows),
                    }
                )
        source_manifest.append(
            source_entry(
                family,
                run_dir,
                study=(
                    "tinker_native_training_full_battery"
                    if evaluation.get("status") in {"COMPLETE", "COMPLETED"}
                    else "tinker_native_training_partial_battery_with_complete_overrides"
                ),
            )
        )

    assert common_items is not None
    if prompt_item_pairs() != common_items:
        raise ValueError("prompt and training batteries do not share exact item identities")

    endpoint_columns = (
        "answer_rate",
        "accuracy_on_usable_attempts",
        "mean_confidence_on_usable_attempts",
        "signed_overconfidence_gap",
        "confidence_adjusted_accuracy",
        "high_confidence_error_90_rate",
        "invalid_rate",
        "abstention_rate",
    )
    prompt_cell_rows: list[dict[str, object]] = []
    prompt_summary_rows: list[dict[str, object]] = []
    for family, run_dir in PROMPT_RUNS.items():
        evaluation = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
        if evaluation.get("status") not in {"COMPLETE", "COMPLETED"}:
            raise ValueError(f"{family} prompt evaluation is not complete")
        responses = read_jsonl(run_dir / "responses.jsonl")
        items = read_jsonl(run_dir / "items.jsonl")
        item_pairs = {(str(row["benchmark"]), str(row["item_id"])) for row in items}
        if item_pairs != common_items:
            raise ValueError(f"{family} prompt evaluation changed question identities")
        if set(evaluation["design"]["prompt_conditions"]) != set(PROMPT_CONDITIONS):
            raise ValueError(f"{family} prompt evaluation does not contain all three arms")
        if set(evaluation["design"]["checkpoints"]) != {"base"}:
            raise ValueError(f"{family} prompt evaluation must use only its training control")
        for benchmark, override_dirs in PROMPT_BENCHMARK_OVERRIDES.get(
            family, {}
        ).items():
            override_pairs: set[tuple[str, str]] = set()
            override_response_map: dict[
                tuple[str, str, str, int], dict[str, object]
            ] = {}
            for override_dir in override_dirs:
                override_evaluation = json.loads(
                    (override_dir / "evaluation.json").read_text(encoding="utf-8")
                )
                if override_evaluation.get("status") not in {"COMPLETE", "COMPLETED"}:
                    raise ValueError(f"{family}/{benchmark} prompt replacement is not complete")
                if set(override_evaluation["design"]["prompt_conditions"]) != set(
                    PROMPT_CONDITIONS
                ):
                    raise ValueError(f"{family}/{benchmark} prompt replacement changed arms")
                override_items = read_jsonl(override_dir / "items.jsonl")
                shard_pairs = {
                    (str(row["benchmark"]), str(row["item_id"]))
                    for row in override_items
                }
                override_pairs.update(shard_pairs)
                for row in read_jsonl(override_dir / "responses.jsonl"):
                    identity = (
                        str(row["item_id"]),
                        str(row["checkpoint"]),
                        str(row["prompt_condition"]),
                        int(row["repetition"]),
                    )
                    override_response_map.setdefault(identity, row)
                source_manifest.append(
                    source_entry(
                        family,
                        override_dir,
                        study="tinker_native_prompt_benchmark_replacement",
                        replaced_benchmark=benchmark,
                    )
                )
            expected_pairs = {pair for pair in common_items if pair[0] == benchmark}
            if override_pairs != expected_pairs:
                raise ValueError(f"{family}/{benchmark} prompt replacement changed items")
            override_responses = list(override_response_map.values())
            expected_override = len(PROMPT_CONDITIONS) * ITEMS_PER_BENCHMARK
            if len(override_responses) != expected_override:
                raise ValueError(f"{family}/{benchmark} prompt replacement is incomplete")
            responses = [
                row for row in responses if str(row["benchmark"]) != benchmark
            ] + override_responses
        expected = len(common_items) * len(PROMPT_CONDITIONS)
        if len(responses) != expected:
            raise ValueError(
                f"{family} prompt evaluation: expected {expected:,}, found {len(responses):,}"
            )
        grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        for row in responses:
            grouped[(str(row["prompt_condition"]), str(row["benchmark"]))].append(row)
        for condition in PROMPT_CONDITIONS:
            condition_rows = []
            for benchmark in BENCHMARKS:
                rows = grouped[(condition, benchmark)]
                if len(rows) != ITEMS_PER_BENCHMARK:
                    raise ValueError(f"incomplete prompt cell: {family}/{condition}/{benchmark}")
                cell = {
                    "model_family": family,
                    "prompt_condition": condition,
                    # Same per-family rule as the training cells above: the
                    # prompt arms are run on each family's own control model.
                    "control_type": CONTROL_TYPES[family],
                    "benchmark": benchmark,
                    **metrics(rows),
                }
                prompt_cell_rows.append(cell)
                condition_rows.append(cell)
            prompt_summary_rows.append(
                {
                    "model_family": family,
                    "prompt_condition": condition,
                    "scheduled_n": sum(int(row["scheduled_n"]) for row in condition_rows),
                    **{column: mean(condition_rows, column) for column in endpoint_columns},
                }
            )
        source_manifest.append(
            source_entry(family, run_dir, study="tinker_native_prompt_full_battery")
        )

    summary_rows: list[dict[str, object]] = []
    grouping: dict[tuple[str, str, object], list[dict[str, object]]] = defaultdict(list)
    for row in cell_rows:
        grouping[
            (str(row["model_family"]), str(row["training_objective"]), row["training_seed"])
        ].append(row)
    for (family, objective, seed), rows in sorted(grouping.items(), key=str):
        if len(rows) != len(BENCHMARKS):
            raise ValueError(f"summary group is not eight complete cells: {family}/{objective}/{seed}")
        summary_rows.append(
            {
                "model_family": family,
                "training_objective": objective,
                "training_seed": seed,
                "scheduled_n": sum(int(row["scheduled_n"]) for row in rows),
                **{column: mean(rows, column) for column in endpoint_columns},
            }
        )

    contrasts: list[dict[str, object]] = []
    summary_index = {
        (str(row["model_family"]), str(row["training_objective"]), row["training_seed"]): row
        for row in summary_rows
    }
    for family in RUNS:
        seeds = sorted(
            int(row["training_seed"])
            for row in summary_rows
            if row["model_family"] == family and row["training_objective"] == "binary"
        )
        for seed in seeds:
            accuracy_only = summary_index[(family, "binary", seed)]
            true_confidence = summary_index[(family, "quadratic", seed)]
            contrasts.append(
                {
                    "model_family": family,
                    "training_seed": seed,
                    "scheduled_n_per_condition": accuracy_only["scheduled_n"],
                    **{
                        f"{name}_{suffix}": value
                        for name, column in (
                            ("overconfidence_gap", "signed_overconfidence_gap"),
                            ("confidence_adjusted_accuracy", "confidence_adjusted_accuracy"),
                            ("high_confidence_error_90_rate", "high_confidence_error_90_rate"),
                        )
                        for suffix, value in (
                            ("accuracy_only", accuracy_only[column]),
                            ("true_confidence", true_confidence[column]),
                            ("change", float(true_confidence[column]) - float(accuracy_only[column])),
                        )
                    },
                }
            )

    write_csv(PROCESSED / f"training_common_battery_cells{suffix}.csv", cell_rows)
    write_csv(PROCESSED / f"training_common_battery_summary{suffix}.csv", summary_rows)
    write_csv(PROCESSED / f"training_common_battery_contrasts{suffix}.csv", contrasts)
    write_csv(PROCESSED / f"training_common_battery_prompt_cells{suffix}.csv", prompt_cell_rows)
    write_csv(PROCESSED / f"training_common_battery_prompt_summary{suffix}.csv", prompt_summary_rows)
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest = {
        "protocol": "notes/2026-08-31-matched-prompt-interventions-8b-20b.md",
        "prompt_database": {
            "path": str(PROMPT_DB.relative_to(ROOT)),
            "sha256": sha256(PROMPT_DB),
        },
        "common_items": len(common_items),
        "item_identity_matches_prompt_run": True,
        "sources": source_manifest,
        "git_commit": git_commit,
    }
    (PROCESSED / f"training_common_battery_manifest{suffix}.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    for family in RUNS:
        family_rows = [row for row in contrasts if row["model_family"] == family]
        print(f"{family}: {len(family_rows)} matched training seeds")
        for name in (
            "overconfidence_gap",
            "confidence_adjusted_accuracy",
            "high_confidence_error_90_rate",
        ):
            change = mean(family_rows, f"{name}_change")
            print(f"  {name}: mean change {change * 100:+.1f} points")


if __name__ == "__main__":
    main()
