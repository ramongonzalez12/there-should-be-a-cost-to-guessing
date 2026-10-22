#!/usr/bin/env python3
"""Combine complete Tinker evaluation matrices without selecting a training seed.

The single-seed evaluator deliberately owns generation and per-seed summaries.
This script runs afterwards, reads only saved responses, and preserves the
training-seed axis in the confirmatory comparison. It never imports Tinker and
cannot make a model call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import subprocess
from collections import defaultdict
from statistics import mean

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIMARY_PROMPT = "neutral"
BASELINE = "binary"
TREATMENT = "quadratic"
PRIMARY_SCORE = "quadratic"
CHECKPOINTS = ("base", "binary", "quadratic", "quad_cost")
PROMPT_CONDITIONS = ("neutral", "binary", "quadratic", "quad_cost")


def _sha256(path: pathlib.Path) -> str:
    """Return a content hash so the combined result identifies every input."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: pathlib.Path, payload: dict[str, object]) -> None:
    """Write a JSON artifact atomically so interruption cannot leave partial output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _git_commit() -> str | None:
    """Record the analysis code version when the script runs inside a git clone."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _parse_evaluation(value: str) -> tuple[str, pathlib.Path]:
    """Parse LABEL=PATH while keeping human-readable seed labels in the output."""
    if "=" not in value:
        raise argparse.ArgumentTypeError("--evaluation must use LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label or not raw_path:
        raise argparse.ArgumentTypeError("--evaluation must use nonempty LABEL=PATH")
    return label, pathlib.Path(raw_path)


def _load_matrix(
    label: str,
    directory: pathlib.Path,
    *,
    expected_items_sha256: str,
    expected_offset: int,
) -> dict[str, object]:
    """Load one complete final matrix and reject any provenance mismatch."""
    manifest_path = directory / "evaluation.json"
    responses_path = directory / "responses.jsonl"
    summary_path = directory / "summary.json"
    for path in (manifest_path, responses_path, summary_path):
        if not path.exists():
            raise FileNotFoundError(f"{label} is missing {path.name}: {path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE":
        raise ValueError(f"{label} evaluation is not COMPLETE")
    if manifest.get("split_label") != "final":
        raise ValueError(f"{label} evaluation is not labeled final")
    if manifest.get("item_offset_per_benchmark") != expected_offset:
        raise ValueError(f"{label} evaluation used a different item offset")
    workload = manifest.get("workload", {})
    if workload.get("items_sha256") != expected_items_sha256:
        raise ValueError(f"{label} evaluation used a different final item set")
    if tuple(workload.get("checkpoints", ())) != CHECKPOINTS:
        raise ValueError(f"{label} evaluation has a different checkpoint matrix")
    if tuple(workload.get("prompt_conditions", ())) != PROMPT_CONDITIONS:
        raise ValueError(f"{label} evaluation has a different prompt matrix")
    if workload.get("generation_cells_per_item") != len(CHECKPOINTS) * len(
        PROMPT_CONDITIONS
    ):
        raise ValueError(f"{label} evaluation has an incomplete item matrix")

    rows = [
        json.loads(line)
        for line in responses_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected_responses = int(workload.get("generation_calls", 0))
    if len(rows) != expected_responses:
        raise ValueError(
            f"{label} saved {len(rows)} responses; expected {expected_responses}"
        )
    identity = lambda row: (
        str(row["benchmark"]),
        str(row["item_id"]),
        str(row["checkpoint"]),
        str(row["prompt_condition"]),
        int(row["repetition"]),
    )
    identities = {identity(row) for row in rows}
    if len(identities) != len(rows):
        raise ValueError(f"{label} evaluation contains duplicate response identities")
    expected_cells = {
        (checkpoint, prompt)
        for checkpoint in CHECKPOINTS
        for prompt in PROMPT_CONDITIONS
    }
    cells_by_item_repetition: dict[tuple[str, str, int], set[tuple[str, str]]] = (
        defaultdict(set)
    )
    for row in rows:
        item_key = (
            str(row["benchmark"]),
            str(row["item_id"]),
            int(row["repetition"]),
        )
        cells_by_item_repetition[item_key].add(
            (str(row["checkpoint"]), str(row["prompt_condition"]))
        )
    if any(cells != expected_cells for cells in cells_by_item_repetition.values()):
        raise ValueError(f"{label} evaluation contains an incomplete crossed item")
    distinct_items = {(benchmark, item_id) for benchmark, item_id, _ in cells_by_item_repetition}
    if len(distinct_items) != int(workload.get("items", 0)):
        raise ValueError(f"{label} evaluation contains a different item count")

    return {
        "label": label,
        "directory": str(directory),
        "seed": int(manifest["seed"]),
        "model": str(manifest["model"]),
        "renderer": str(manifest["renderer"]),
        "assertion_cost": float(manifest["assertion_cost"]),
        "temperature": float(manifest["temperature"]),
        "max_tokens": int(manifest["max_tokens"]),
        "prompt_hashes": manifest["prompt_hashes"],
        "checkpoint_paths": manifest["checkpoint_paths"],
        "workload": workload,
        "rows": rows,
        "artifact_sha256": {
            "evaluation": _sha256(manifest_path),
            "responses": _sha256(responses_path),
            "summary": _sha256(summary_path),
        },
    }


def _item_differences(rows: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    """Return treatment-minus-baseline endpoints averaged within each final item."""
    selected = [
        row
        for row in rows
        if row["prompt_condition"] == PRIMARY_PROMPT
        and row["checkpoint"] in {BASELINE, TREATMENT}
    ]
    by_identity = {
        (
            str(row["benchmark"]),
            str(row["item_id"]),
            str(row["checkpoint"]),
            int(row["repetition"]),
        ): row
        for row in selected
    }
    item_repetitions: dict[tuple[str, str], set[int]] = defaultdict(set)
    for benchmark, item_id, _checkpoint, repetition in by_identity:
        item_repetitions[(benchmark, item_id)].add(repetition)

    result: dict[str, dict[str, float]] = {}
    for (benchmark, item_id), repetitions in sorted(item_repetitions.items()):
        differences: dict[str, list[float]] = defaultdict(list)
        for repetition in sorted(repetitions):
            baseline_key = (benchmark, item_id, BASELINE, repetition)
            treatment_key = (benchmark, item_id, TREATMENT, repetition)
            if baseline_key not in by_identity or treatment_key not in by_identity:
                raise ValueError(f"incomplete primary pair for {benchmark}:{item_id}")
            baseline = by_identity[baseline_key]
            treatment = by_identity[treatment_key]
            differences["quadratic_score"].append(
                float(treatment["scores"][PRIMARY_SCORE])
                - float(baseline["scores"][PRIMARY_SCORE])
            )
            differences["accuracy"].append(
                float(treatment["outcome"] == "CORRECT")
                - float(baseline["outcome"] == "CORRECT")
            )
            differences["invalid_rate"].append(
                float(treatment["outcome"] == "INVALID")
                - float(baseline["outcome"] == "INVALID")
            )
        result[f"{benchmark}:{item_id}"] = {
            endpoint: mean(values) for endpoint, values in differences.items()
        }
    if not result:
        raise ValueError("evaluation contains no paired neutral-prompt primary cells")
    return result


def _interval(
    values: list[float], *, label: str, bootstrap_samples: int
) -> list[float] | None:
    """Bootstrap final items with a deterministic seed derived from the label."""
    if len(values) < 2 or bootstrap_samples <= 0:
        return None
    seed_bytes = hashlib.sha256(label.encode("utf-8")).digest()[:8]
    rng = random.Random(int.from_bytes(seed_bytes, byteorder="big"))
    draws = []
    for _ in range(bootstrap_samples):
        draws.append(mean(rng.choice(values) for _ in values))
    draws.sort()
    return [
        draws[int(0.025 * (bootstrap_samples - 1))],
        draws[int(0.975 * (bootstrap_samples - 1))],
    ]


def _endpoint_summary(
    item_values: dict[str, dict[str, float]],
    endpoint: str,
    *,
    label: str,
    bootstrap_samples: int,
) -> dict[str, object]:
    """Summarize one additive paired endpoint over final items."""
    values = [item_values[item][endpoint] for item in sorted(item_values)]
    return {
        "estimate": mean(values),
        "confidence_interval_95": _interval(
            values, label=label, bootstrap_samples=bootstrap_samples
        ),
        "paired_items": len(values),
        "bootstrap_samples": bootstrap_samples if len(values) >= 2 else 0,
    }


def summarize(
    evaluations: list[tuple[str, pathlib.Path]],
    *,
    expected_items_sha256: str,
    expected_offset: int,
    bootstrap_samples: int,
    minimum_combined_quadratic: float,
    minimum_seed_quadratic: float,
    minimum_combined_accuracy: float,
    minimum_seed_accuracy: float,
    maximum_invalid_change: float,
    protocol_path: pathlib.Path,
) -> dict[str, object]:
    """Validate all promoted seeds, combine their paired effects, and apply gates."""
    if len(evaluations) < 2:
        raise ValueError("final analysis requires at least two promoted evaluations")
    labels = [label for label, _path in evaluations]
    if len(labels) != len(set(labels)):
        raise ValueError("evaluation labels must be unique")

    loaded = [
        _load_matrix(
            label,
            path,
            expected_items_sha256=expected_items_sha256,
            expected_offset=expected_offset,
        )
        for label, path in evaluations
    ]
    seeds = [matrix["seed"] for matrix in loaded]
    if len(seeds) != len(set(seeds)):
        raise ValueError("promoted evaluations must use distinct sampling seeds")
    comparable_fields = (
        "model",
        "renderer",
        "assertion_cost",
        "temperature",
        "max_tokens",
        "prompt_hashes",
        "workload",
    )
    reference = loaded[0]
    for matrix in loaded[1:]:
        for field in comparable_fields:
            if matrix[field] != reference[field]:
                raise ValueError(f"promoted evaluations differ on {field}")

    by_seed_items = {
        str(matrix["label"]): _item_differences(matrix["rows"]) for matrix in loaded
    }
    item_sets = [set(items) for items in by_seed_items.values()]
    if any(items != item_sets[0] for items in item_sets[1:]):
        raise ValueError("promoted evaluations do not contain the same final items")

    endpoints = ("quadratic_score", "accuracy", "invalid_rate")
    by_seed = {
        label: {
            endpoint: _endpoint_summary(
                items,
                endpoint,
                label=f"{expected_items_sha256}|{label}|{endpoint}",
                bootstrap_samples=bootstrap_samples,
            )
            for endpoint in endpoints
        }
        for label, items in by_seed_items.items()
    }
    combined_items = {
        item: {
            endpoint: mean(by_seed_items[label][item][endpoint] for label in labels)
            for endpoint in endpoints
        }
        for item in sorted(item_sets[0])
    }
    combined = {
        endpoint: _endpoint_summary(
            combined_items,
            endpoint,
            label=f"{expected_items_sha256}|combined|{endpoint}",
            bootstrap_samples=bootstrap_samples,
        )
        for endpoint in endpoints
    }

    quadratic_interval = combined["quadratic_score"]["confidence_interval_95"]
    gates = {
        "combined_quadratic_positive_with_interval": {
            "threshold": minimum_combined_quadratic,
            "observed": combined["quadratic_score"],
            "passed": bool(
                combined["quadratic_score"]["estimate"] > minimum_combined_quadratic
                and quadratic_interval
                and quadratic_interval[0] > minimum_combined_quadratic
            ),
        },
        "every_seed_quadratic_positive": {
            "threshold": minimum_seed_quadratic,
            "observed": {
                label: by_seed[label]["quadratic_score"]["estimate"] for label in labels
            },
            "passed": all(
                by_seed[label]["quadratic_score"]["estimate"]
                > minimum_seed_quadratic
                for label in labels
            ),
        },
        "combined_accuracy_noninferior": {
            "threshold": minimum_combined_accuracy,
            "observed": combined["accuracy"],
            "passed": combined["accuracy"]["estimate"] >= minimum_combined_accuracy,
        },
        "every_seed_accuracy_noninferior": {
            "threshold": minimum_seed_accuracy,
            "observed": {
                label: by_seed[label]["accuracy"]["estimate"] for label in labels
            },
            "passed": all(
                by_seed[label]["accuracy"]["estimate"] >= minimum_seed_accuracy
                for label in labels
            ),
        },
        "invalid_rate_change_acceptable": {
            "threshold": maximum_invalid_change,
            "observed": combined["invalid_rate"],
            "passed": combined["invalid_rate"]["estimate"] <= maximum_invalid_change,
        },
    }
    passed = all(bool(gate["passed"]) for gate in gates.values())

    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "analysis_code_commit": _git_commit(),
        "protocol": {
            "path": str(protocol_path),
            "sha256": _sha256(protocol_path),
        },
        "primary": {
            "prompt_condition": PRIMARY_PROMPT,
            "treatment": TREATMENT,
            "versus": BASELINE,
            "score": PRIMARY_SCORE,
            "items_sha256": expected_items_sha256,
            "item_offset_per_benchmark": expected_offset,
            "paired_training_seeds": seeds,
            "paired_items": len(combined_items),
        },
        "decision_rule": {
            "minimum_combined_quadratic": minimum_combined_quadratic,
            "minimum_seed_quadratic": minimum_seed_quadratic,
            "minimum_combined_accuracy": minimum_combined_accuracy,
            "minimum_seed_accuracy": minimum_seed_accuracy,
            "maximum_invalid_change": maximum_invalid_change,
            "bootstrap_samples": bootstrap_samples,
        },
        "by_seed": by_seed,
        "combined": combined,
        "gates": gates,
        "verdict": "PASS" if passed else "FAIL",
        "inputs": [
            {
                key: value
                for key, value in matrix.items()
                if key not in {"rows"}
            }
            for matrix in loaded
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evaluation",
        action="append",
        required=True,
        type=_parse_evaluation,
        help="promoted final matrix as LABEL=PATH; provide once per training seed",
    )
    parser.add_argument("--out", required=True, type=pathlib.Path)
    parser.add_argument("--protocol", required=True, type=pathlib.Path)
    parser.add_argument("--expected-items-sha256", required=True)
    parser.add_argument("--expected-offset", required=True, type=int)
    parser.add_argument("--bootstrap-samples", required=True, type=int)
    parser.add_argument("--minimum-combined-quadratic", required=True, type=float)
    parser.add_argument("--minimum-seed-quadratic", required=True, type=float)
    parser.add_argument("--minimum-combined-accuracy", required=True, type=float)
    parser.add_argument("--minimum-seed-accuracy", required=True, type=float)
    parser.add_argument("--maximum-invalid-change", required=True, type=float)
    args = parser.parse_args(argv)
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    if not args.protocol.exists():
        parser.error(f"protocol does not exist: {args.protocol}")

    try:
        result = summarize(
            args.evaluation,
            expected_items_sha256=args.expected_items_sha256,
            expected_offset=args.expected_offset,
            bootstrap_samples=args.bootstrap_samples,
            minimum_combined_quadratic=args.minimum_combined_quadratic,
            minimum_seed_quadratic=args.minimum_seed_quadratic,
            minimum_combined_accuracy=args.minimum_combined_accuracy,
            minimum_seed_accuracy=args.minimum_seed_accuracy,
            maximum_invalid_change=args.maximum_invalid_change,
            protocol_path=args.protocol,
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    _atomic_json(args.out, result)
    print(json.dumps({"status": result["status"], "verdict": result["verdict"], "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
