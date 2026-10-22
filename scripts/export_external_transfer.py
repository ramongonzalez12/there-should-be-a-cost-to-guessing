#!/usr/bin/env python3
"""Export external transfer levels and matched within-seed contrasts.

The three test families stay separate because calibration, honesty under
pressure, and instruction hierarchy are different estimands.  The long-form
CSV keeps that distinction explicit while giving the site builder one stable
schema to read.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "runs" / "finetune" / "external_transfer_v1" / "summary.json"
LEVELS_OUT = ROOT / "data" / "processed" / "external_transfer_levels.csv"
CONTRASTS_OUT = ROOT / "data" / "processed" / "external_transfer_contrasts.csv"
MANIFEST_OUT = ROOT / "data" / "processed" / "external_transfer_manifest.json"

IDENTITY_FIELDS = (
    "checkpoint",
    "training_objective",
    "training_seed",
    "family",
    "task",
    "setting",
)
METRIC_FIELDS = (
    "n",
    "parse_rate",
    "accuracy",
    "accuracy_when_answered",
    "coverage",
    "brier_loss",
    "confidence_calibrated_score",
    "high_confidence_wrong_rate",
    "mean_confidence",
    "belief_parse_rate",
    "belief_accuracy",
    "belief_brier_loss",
    "pressure_parse_rate",
    "pressure_truth_rate",
    "pressure_brier_loss",
    "honesty_given_known",
    "pressure_flip_rate",
    "known_n",
    "paired_n",
    "attack_success_rate",
    "secret_leak_rate",
)
LEVEL_FIELDS = IDENTITY_FIELDS + METRIC_FIELDS
CONTRAST_FIELDS = (
    "training_seed",
    "treatment_objective",
    "control_objective",
    "family",
    "task",
    "setting",
) + tuple(f"{metric}_change" for metric in METRIC_FIELDS if metric not in {"n", "known_n", "paired_n"})


def _write(path: pathlib.Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _level(
    checkpoint: str,
    cell: dict[str, object],
    family: str,
    task: str,
    setting: str,
    metrics: dict[str, object],
) -> dict[str, object]:
    row: dict[str, object] = {
        "checkpoint": checkpoint,
        "training_objective": cell["training_objective"],
        "training_seed": "" if cell.get("training_seed") is None else cell["training_seed"],
        "family": family,
        "task": task,
        "setting": setting,
    }
    row.update({metric: "" if metrics.get(metric) is None else metrics.get(metric) for metric in METRIC_FIELDS})
    return row


def _delta(control: object, treatment: object) -> float | str:
    if control in (None, "") or treatment in (None, ""):
        return ""
    return float(treatment) - float(control)


def export(summary_path: pathlib.Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    levels: list[dict[str, object]] = []
    for checkpoint, cell in payload["by_checkpoint"].items():
        for benchmark, metrics in cell["freeform"].items():
            # For answered binary outcomes, the strictly proper quadratic
            # payoff is accuracy minus Brier loss.  Export that reader-facing
            # score explicitly so the report never relabels raw confidence as
            # calibration quality.
            derived = {
                **metrics,
                "confidence_calibrated_score": (
                    float(metrics["accuracy"]) - float(metrics["brier_loss"])
                ),
            }
            levels.append(_level(checkpoint, cell, "calibration transfer", benchmark, "short answer", derived))
        for config, metrics in cell["mask"].items():
            levels.append(_level(checkpoint, cell, "honesty under pressure", "MASK", config, metrics))
        for identity, metrics in cell["iheval"].items():
            task, setting = identity.split("|", maxsplit=1)
            levels.append(_level(checkpoint, cell, "instruction hierarchy", task, setting, metrics))
    levels.sort(
        key=lambda row: (
            row["training_seed"] == "",
            str(row["training_seed"]),
            str(row["training_objective"]),
            str(row["family"]),
            str(row["task"]),
            str(row["setting"]),
        )
    )
    by_identity = {
        (
            str(row["training_objective"]),
            str(row["training_seed"]),
            str(row["family"]),
            str(row["task"]),
            str(row["setting"]),
        ): row
        for row in levels
    }
    conditions = sorted(
        {
            (str(row["family"]), str(row["task"]), str(row["setting"]))
            for row in levels
            if row["training_seed"] != ""
        }
    )
    contrasts: list[dict[str, object]] = []
    delta_metrics = tuple(metric for metric in METRIC_FIELDS if metric not in {"n", "known_n", "paired_n"})
    seeds = sorted(
        {seed for objective, seed, *_rest in by_identity if objective == "binary" and seed},
        key=int,
    )
    treatment_objectives = tuple(
        objective
        for objective in ("quadratic", "quad_cost_0.09")
        if any(key[0] == objective for key in by_identity)
    )
    for seed in seeds:
        for family, task, setting in conditions:
            control = by_identity[("binary", seed, family, task, setting)]
            for objective in treatment_objectives:
                key = (objective, seed, family, task, setting)
                if key not in by_identity:
                    continue
                treatment = by_identity[key]
                row: dict[str, object] = {
                    "training_seed": seed,
                    "treatment_objective": objective,
                    "control_objective": "binary",
                    "family": family,
                    "task": task,
                    "setting": setting,
                }
                row.update(
                    {
                        f"{metric}_change": _delta(control[metric], treatment[metric])
                        for metric in delta_metrics
                    }
                )
                contrasts.append(row)
    return levels, contrasts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=pathlib.Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    levels, contrasts = export(args.summary)
    _write(LEVELS_OUT, LEVEL_FIELDS, levels)
    _write(CONTRASTS_OUT, CONTRAST_FIELDS, contrasts)
    payload = json.loads(args.summary.read_text(encoding="utf-8"))
    responses = args.summary.with_name("responses.jsonl")
    manifest = {
        "schema_version": 1,
        "source_run": str(args.summary.parent.relative_to(ROOT)),
        "completed_at": payload["completed_at"],
        "records": payload["records"],
        "spend": payload["spend"],
        "design": payload["design"],
        "raw_responses_sha256": hashlib.sha256(responses.read_bytes()).hexdigest(),
        "committed_outputs": [
            str(LEVELS_OUT.relative_to(ROOT)),
            str(CONTRASTS_OUT.relative_to(ROOT)),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {LEVELS_OUT}: {len(levels)} checkpoint-condition cells")
    print(f"wrote {CONTRASTS_OUT}: {len(contrasts)} matched contrasts")
    print(f"wrote {MANIFEST_OUT}: raw response hash and frozen design")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
