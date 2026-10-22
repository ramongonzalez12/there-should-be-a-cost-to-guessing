#!/usr/bin/env python3
"""Export the plural-prudence battery from its preserved raw run state.

The outputs retain every behavioral endpoint separately. Checkpoint levels,
within-seed training contrasts, and within-checkpoint prompt contrasts are
written as distinct tables so evaluation-time prompting cannot be mistaken for
an effect of fine-tuning.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "runs" / "finetune" / "plural_prudence_v1" / "summary.json"
LEVELS_OUT = ROOT / "data" / "processed" / "plural_prudence_levels.csv"
CONTRASTS_OUT = ROOT / "data" / "processed" / "plural_prudence_contrasts.csv"
PROMPTS_OUT = ROOT / "data" / "processed" / "plural_prudence_prompt_contrasts.csv"
MANIFEST_OUT = ROOT / "data" / "processed" / "plural_prudence_manifest.json"

# Every metric has a track prefix in the flat exports. This avoids adjacent
# percentages with different denominators looking interchangeable.
TRACK_METRICS = {
    "prudence": (
        "n", "parse_rate", "substantive_n", "accuracy", "brier_loss",
        "execute_rate", "verify_rate", "defer_rate", "wrong_execution_rate",
        "high_confidence_wrong_execution_rate", "realized_utility",
        "stated_belief_optimal_rate",
    ),
    "evidence": (
        "n", "initial_parse_rate", "update_parse_rate", "initial_absolute_error",
        "posterior_absolute_error", "correct_direction_rate",
        "threshold_action_accuracy", "unsupported_movement", "irrelevant_movement",
    ),
    "plural": (
        "n", "parse_rate", "best_permitted_rate", "hard_constraint_violation_rate",
        "narrow_kpi_rate", "dominated_rate", "overcautious_rate",
    ),
    "integrity": (
        "n", "parse_rate", "unauthorized_shortcut_rate", "tamper_rate",
        "benign_tool_success", "prohibited_n", "concealment_given_prohibited",
        "truthful_audit_rate",
    ),
    "goal": (
        "n", "parse_rate", "appropriate_action_rate", "goal_dogmatism_rate",
        "covert_resistance_rate", "untrusted_goal_adoption_rate",
        "ambiguity_clarification_rate",
    ),
}

IDENTITY_FIELDS = ("checkpoint", "training_objective", "training_seed", "framing")
METRIC_FIELDS = tuple(
    f"{track}_{metric}"
    for track, metrics in TRACK_METRICS.items()
    for metric in metrics
)
LEVEL_FIELDS = IDENTITY_FIELDS + METRIC_FIELDS
CONTRAST_FIELDS = (
    "training_seed", "framing", "treatment_objective", "control_objective"
) + tuple(f"{field}_change" for field in METRIC_FIELDS)
PROMPT_FIELDS = (
    "checkpoint", "training_objective", "training_seed", "framing", "reference_framing"
) + tuple(f"{field}_change" for field in METRIC_FIELDS)


def _write(path: pathlib.Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _flatten(cell: dict[str, object]) -> dict[str, object]:
    row: dict[str, object] = {
        "checkpoint": cell["checkpoint"],
        "training_objective": cell["training_objective"],
        "training_seed": "" if cell.get("training_seed") is None else cell["training_seed"],
        "framing": cell["framing"],
    }
    for track, metrics in TRACK_METRICS.items():
        values = cell[track]
        for metric in metrics:
            value = values.get(metric)
            row[f"{track}_{metric}"] = "" if value is None else value
    return row


def _delta(left: object, right: object) -> float | str:
    """Return right minus left, leaving undefined endpoints visibly blank."""
    if left in (None, "") or right in (None, ""):
        return ""
    return float(right) - float(left)


def export(
    summary_path: pathlib.Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    levels = [_flatten(cell) for cell in payload["by_cell"].values()]
    levels.sort(
        key=lambda row: (
            row["training_seed"] == "",
            str(row["training_seed"]),
            str(row["training_objective"]),
            str(row["framing"]),
        )
    )
    by_identity = {
        (str(row["training_objective"]), str(row["training_seed"]), str(row["framing"])): row
        for row in levels
    }
    contrasts: list[dict[str, object]] = []
    seeds = sorted(
        {
            seed
            for objective, seed, framing in by_identity
            if objective == "binary" and seed and framing == "neutral"
        },
        key=int,
    )
    treatment_objectives = tuple(
        objective
        for objective in ("quadratic", "quad_cost_0.09")
        if any(key[0] == objective for key in by_identity)
    )
    for seed in seeds:
        for framing in ("neutral", "plural", "prudence", "combined"):
            control = by_identity[("binary", seed, framing)]
            for objective in treatment_objectives:
                if (objective, seed, framing) not in by_identity:
                    continue
                treatment = by_identity[(objective, seed, framing)]
                row: dict[str, object] = {
                    "training_seed": seed,
                    "framing": framing,
                    "treatment_objective": objective,
                    "control_objective": "binary",
                }
                row.update(
                    {
                        f"{field}_change": _delta(control[field], treatment[field])
                        for field in METRIC_FIELDS
                    }
                )
                contrasts.append(row)

    prompt_contrasts: list[dict[str, object]] = []
    by_checkpoint = {(str(row["checkpoint"]), str(row["framing"])): row for row in levels}
    for checkpoint in sorted({str(row["checkpoint"]) for row in levels}):
        neutral = by_checkpoint[(checkpoint, "neutral")]
        for framing in ("plural", "prudence", "combined"):
            treatment = by_checkpoint[(checkpoint, framing)]
            row = {
                "checkpoint": checkpoint,
                "training_objective": treatment["training_objective"],
                "training_seed": treatment["training_seed"],
                "framing": framing,
                "reference_framing": "neutral",
            }
            row.update(
                {
                    f"{field}_change": _delta(neutral[field], treatment[field])
                    for field in METRIC_FIELDS
                }
            )
            prompt_contrasts.append(row)
    return levels, contrasts, prompt_contrasts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=pathlib.Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    levels, contrasts, prompt_contrasts = export(args.summary)
    _write(LEVELS_OUT, LEVEL_FIELDS, levels)
    _write(CONTRASTS_OUT, CONTRAST_FIELDS, contrasts)
    _write(PROMPTS_OUT, PROMPT_FIELDS, prompt_contrasts)
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
            str(PROMPTS_OUT.relative_to(ROOT)),
        ],
    }
    MANIFEST_OUT.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {LEVELS_OUT}: {len(levels)} checkpoint-framing cells")
    print(f"wrote {CONTRASTS_OUT}: {len(contrasts)} matched training contrasts")
    print(f"wrote {PROMPTS_OUT}: {len(prompt_contrasts)} prompt contrasts")
    print(f"wrote {MANIFEST_OUT}: raw response hash and frozen design")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
