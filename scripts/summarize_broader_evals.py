#!/usr/bin/env python3
"""Export the broader Tinker screens and tuned comparisons to tidy CSVs.

The raw response JSONL remains the audit authority. These tables are compact
inputs for the report and can always be regenerated from the completed summary
files without another model call.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import tempfile

CELL_FIELDS = (
    "n",
    "accuracy",
    "coverage",
    "abstention",
    "invalid",
    "mean_confidence",
    "confidence_std",
    "signed_calibration_gap",
    "expected_calibration_error",
    "brier",
    "confidence_auroc",
)

SCORE_FIELDS = tuple(
    f"score_{rule}"
    for rule in (
        "binary",
        "quadratic",
        "quad_cost_0.04",
        "quad_cost_0.09",
        "quad_cost_0.16",
    )
)
CONTRAST_FIELDS = CELL_FIELDS[1:] + SCORE_FIELDS


def _load(path: pathlib.Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_csv(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    """Write one complete table, then replace the prior version atomically."""
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)


def _atomic_json(path: pathlib.Path, payload: object) -> None:
    """Write compact provenance data without leaving a partial manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)


def _cell_row(
    *,
    model: str,
    benchmark: str,
    checkpoint: str,
    metadata: dict[str, object],
    cell: dict[str, object],
) -> dict[str, object]:
    row = {
        "model": model,
        "benchmark": benchmark,
        "checkpoint": checkpoint,
        "arm": metadata.get("arm"),
        "dose": metadata.get("dose"),
        "training_seed": metadata.get("training_seed"),
    }
    row.update({field: cell.get(field) for field in CELL_FIELDS})
    scores = cell.get("mean_scores") or {}
    for rule in (
        "binary",
        "quadratic",
        "quad_cost_0.04",
        "quad_cost_0.09",
        "quad_cost_0.16",
    ):
        row[f"score_{rule}"] = scores.get(rule)
    return row


def benchmark_rows(summaries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Flatten every neutral benchmark/checkpoint cell."""
    rows = []
    for summary in summaries:
        design = summary["design"]
        model = str(design["model"])
        checkpoints = design["checkpoints"]
        for benchmark, benchmark_summary in summary["by_benchmark"].items():
            for checkpoint, metadata in checkpoints.items():
                cell = benchmark_summary["cells"].get(f"{checkpoint}|neutral")
                if cell is not None:
                    rows.append(
                        _cell_row(
                            model=model,
                            benchmark=benchmark,
                            checkpoint=checkpoint,
                            metadata=metadata,
                            cell=cell,
                        )
                    )
    return rows


def bbq_rows(summaries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Flatten BBQ bias endpoints, retaining the official context split."""
    rows = []
    for summary in summaries:
        if "bbq" not in summary.get("by_benchmark", {}):
            continue
        design = summary["design"]
        for checkpoint, metadata in design["checkpoints"].items():
            contexts = summary["by_benchmark"]["bbq"]["bias"].get(
                f"{checkpoint}|neutral", {}
            )
            for context, metrics in contexts.items():
                rows.append(
                    {
                        "model": design["model"],
                        "checkpoint": checkpoint,
                        "arm": metadata.get("arm"),
                        "dose": metadata.get("dose"),
                        "training_seed": metadata.get("training_seed"),
                        "context_condition": context,
                        **metrics,
                    }
                )
    return rows


def bbq_contrast_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pair BBQ accuracy and signed bias endpoints with binary within seed."""
    keyed = {
        (row["context_condition"], row["training_seed"], row["arm"]): row
        for row in rows
    }
    metrics = (
        "accuracy",
        "non_unknown_attempts",
        "raw_bias_score",
        "accuracy_scaled_bias_score",
    )
    contrasts = []
    for treatment in rows:
        seed = treatment["training_seed"]
        arm = treatment["arm"]
        if seed is None or arm in ("base", "binary"):
            continue
        context = treatment["context_condition"]
        control = keyed.get((context, seed, "binary"))
        if control is None:
            raise ValueError(
                f"missing BBQ binary control for {context}, seed {seed}, arm {arm}"
            )
        result = {
            "model": treatment["model"],
            "context_condition": context,
            "training_seed": seed,
            "treatment_arm": arm,
            "control_arm": "binary",
            "treatment_checkpoint": treatment["checkpoint"],
            "control_checkpoint": control["checkpoint"],
            "n_treatment": treatment["n"],
            "n_control": control["n"],
        }
        for metric in metrics:
            left = treatment.get(metric)
            right = control.get(metric)
            result[f"delta_{metric}"] = (
                None if left is None or right is None else float(left) - float(right)
            )
        contrasts.append(result)
    return contrasts


def stratum_rows(summaries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Flatten benchmark subtasks without pooling away sign reversals.

    ETHICS contains five meaningfully different judgment tasks, while BBQ's
    category and context pairs can move in opposite directions. Keeping the
    benchmark-native stratum label in a tidy table makes those reversals
    inspectable instead of letting a pooled benchmark average hide them.
    """
    rows = []
    for summary in summaries:
        design = summary["design"]
        model = str(design["model"])
        checkpoints = design["checkpoints"]
        for benchmark, benchmark_summary in summary["by_benchmark"].items():
            for stratum, cells in benchmark_summary.get("by_stratum", {}).items():
                for checkpoint, metadata in checkpoints.items():
                    cell = cells.get(f"{checkpoint}|neutral")
                    if cell is not None:
                        rows.append(
                            {
                                "stratum": stratum,
                                **_cell_row(
                                    model=model,
                                    benchmark=benchmark,
                                    checkpoint=checkpoint,
                                    metadata=metadata,
                                    cell=cell,
                                ),
                            }
                        )
    return rows


def contrast_rows(
    rows: list[dict[str, object]], *, identity_fields: tuple[str, ...]
) -> list[dict[str, object]]:
    """Compare each confidence-aware checkpoint with binary at the same seed.

    Every checkpoint answered the same frozen items. The export nevertheless
    retains one row per seed instead of pooling first, because the sign and
    range across stochastic training runs are part of the result.
    """
    keyed = {
        tuple(row[field] for field in identity_fields)
        + (row["training_seed"], row["arm"]): row
        for row in rows
    }
    contrasts = []
    for treatment in rows:
        seed = treatment["training_seed"]
        arm = treatment["arm"]
        if seed is None or arm in ("base", "binary"):
            continue
        identity = tuple(treatment[field] for field in identity_fields)
        control = keyed.get(identity + (seed, "binary"))
        if control is None:
            raise ValueError(
                f"missing binary control for {identity}, seed {seed}, arm {arm}"
            )
        result = {
            **{field: treatment[field] for field in identity_fields},
            "training_seed": seed,
            "treatment_arm": arm,
            "control_arm": "binary",
            "treatment_checkpoint": treatment["checkpoint"],
            "control_checkpoint": control["checkpoint"],
            "n_treatment": treatment["n"],
            "n_control": control["n"],
        }
        for field in CONTRAST_FIELDS:
            left = treatment.get(field)
            right = control.get(field)
            result[f"delta_{field}"] = (
                None if left is None or right is None else float(left) - float(right)
            )
        contrasts.append(result)
    return contrasts


def export_item_manifests(
    runs: list[pathlib.Path], *, output: pathlib.Path
) -> dict[str, pathlib.Path]:
    """Commit-sized manifests for the exact benchmark items each run used."""
    by_benchmark: dict[str, set[str]] = collections.defaultdict(set)
    seen: set[str] = set()
    for run in runs:
        items_path = run / "items.jsonl"
        if not items_path.exists():
            raise FileNotFoundError(f"completed run is missing {items_path}")
        with items_path.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                item_id = str(item["item_id"])
                if item_id in seen:
                    raise ValueError(f"duplicate final item ID across runs: {item_id}")
                seen.add(item_id)
                by_benchmark[str(item["benchmark"])].add(item_id)
    written = {}
    for benchmark, item_ids in sorted(by_benchmark.items()):
        path = output / f"{benchmark}_broader_final_{len(item_ids)}.json"
        _atomic_json(path, sorted(item_ids))
        written[benchmark] = path
    return written


def _summary_files(root: pathlib.Path) -> list[pathlib.Path]:
    files = sorted(root.glob("screen_*/summary.json"))
    if not files:
        raise FileNotFoundError(f"no completed screen summaries under {root}")
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen-root", type=pathlib.Path, required=True)
    parser.add_argument("--tuned", type=pathlib.Path, nargs="*", default=[])
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument(
        "--slice-out",
        type=pathlib.Path,
        help="optional directory for exact final item-ID manifests",
    )
    args = parser.parse_args(argv)

    screen = [_load(path) for path in _summary_files(args.screen_root)]
    tuned = [_load(path / "summary.json") for path in args.tuned]
    _atomic_csv(args.out / "broader_model_screen.csv", benchmark_rows(screen))
    _atomic_csv(
        args.out / "broader_model_screen_strata.csv", stratum_rows(screen)
    )
    _atomic_csv(args.out / "broader_model_screen_bbq_bias.csv", bbq_rows(screen))
    if tuned:
        tuned_benchmarks = benchmark_rows(tuned)
        tuned_strata = stratum_rows(tuned)
        _atomic_csv(args.out / "broader_tuned_benchmarks.csv", tuned_benchmarks)
        _atomic_csv(
            args.out / "broader_tuned_strata.csv", tuned_strata
        )
        tuned_bbq = bbq_rows(tuned)
        _atomic_csv(args.out / "broader_tuned_bbq_bias.csv", tuned_bbq)
        _atomic_csv(
            args.out / "broader_tuned_bbq_contrasts.csv",
            bbq_contrast_rows(tuned_bbq),
        )
        _atomic_csv(
            args.out / "broader_tuned_contrasts.csv",
            contrast_rows(tuned_benchmarks, identity_fields=("benchmark",)),
        )
        _atomic_csv(
            args.out / "broader_tuned_strata_contrasts.csv",
            contrast_rows(
                tuned_strata, identity_fields=("benchmark", "stratum")
            ),
        )
        if args.slice_out is not None:
            export_item_manifests(args.tuned, output=args.slice_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
