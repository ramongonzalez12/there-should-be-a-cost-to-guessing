#!/usr/bin/env python3
"""Export the matched alignment battery from preserved raw run state.

The exporter emits checkpoint levels and within-seed contrasts. It does not
construct a composite alignment score: harmful execution, prohibited action,
concealment, and evidence response remain separate columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "runs" / "finetune" / "matched_alignment_battery_v1" / "summary.json"
LEVELS_OUT = ROOT / "data" / "processed" / "matched_alignment_battery.csv"
CONTRASTS_OUT = ROOT / "data" / "processed" / "matched_alignment_battery_contrasts.csv"
MANIFEST_OUT = ROOT / "data" / "processed" / "matched_alignment_battery_manifest.json"

LEVEL_FIELDS = (
    "checkpoint", "training_objective", "training_seed",
    "decision_n", "decision_parse_rate", "decision_accuracy",
    "decision_execution_rate", "wrong_execution_rate",
    "high_confidence_wrong_execution_rate", "threshold_consistency",
    "scheme_n", "scheme_parse_rate", "prohibited_action_rate",
    "prohibited_conflict_rate", "prohibited_no_conflict_rate",
    "concealment_given_prohibited", "benign_control_success",
    "unsupported_n", "adopted_unsupported_wrong_rate",
    "verified_n", "adopted_verified_correct_rate",
)

CONTRAST_FIELDS = (
    "training_seed", "treatment_objective", "control_objective",
    "decision_accuracy_change", "wrong_execution_change",
    "high_confidence_wrong_execution_change",
    "unsupported_wrong_adoption_change", "verified_correct_adoption_change",
    "prohibited_action_change",
)


def _write(path: pathlib.Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export(summary_path: pathlib.Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    cells = payload["by_checkpoint"]
    levels = []
    for checkpoint, cell in cells.items():
        decision, scheme, evidence = cell["decision"], cell["scheme"], cell["evidence"]
        levels.append({
            "checkpoint": checkpoint,
            "training_objective": cell["arm"],
            "training_seed": "" if cell["training_seed"] is None else cell["training_seed"],
            "decision_n": decision["n"],
            "decision_parse_rate": decision["parse_rate"],
            "decision_accuracy": decision["accuracy"],
            "decision_execution_rate": decision["execution_rate"],
            "wrong_execution_rate": decision["wrong_execution_rate"],
            "high_confidence_wrong_execution_rate": decision["high_confidence_wrong_execution_rate"],
            "threshold_consistency": decision["threshold_consistency"],
            "scheme_n": scheme["n"],
            "scheme_parse_rate": scheme["parse_rate"],
            "prohibited_action_rate": scheme["prohibited_action_rate"],
            "prohibited_conflict_rate": scheme["prohibited_conflict_rate"],
            "prohibited_no_conflict_rate": scheme["prohibited_no_conflict_rate"],
            "concealment_given_prohibited": scheme["concealment_given_prohibited"],
            "benign_control_success": scheme["benign_control_success"],
            "unsupported_n": evidence["unsupported_n"],
            "adopted_unsupported_wrong_rate": evidence["adopted_unsupported_wrong_rate"],
            "verified_n": evidence["verified_n"],
            "adopted_verified_correct_rate": evidence["adopted_verified_correct_rate"],
        })
    levels.sort(key=lambda r: (r["training_seed"] == "", str(r["training_seed"]), r["training_objective"]))
    by_identity = {
        (str(row["training_objective"]), str(row["training_seed"])): row
        for row in levels
    }
    contrasts = []
    seeds = sorted(
        {seed for objective, seed in by_identity if objective == "binary" and seed},
        key=int,
    )
    treatment_objectives = tuple(
        objective
        for objective in ("quadratic", "quad_cost_0.09")
        if any(key[0] == objective for key in by_identity)
    )
    for seed in seeds:
        control = by_identity[("binary", seed)]
        for objective in treatment_objectives:
            if (objective, seed) not in by_identity:
                continue
            treatment = by_identity[(objective, seed)]

            def delta(
                field: str,
                control_row: dict[str, object] = control,
                treatment_row: dict[str, object] = treatment,
            ) -> float | None:
                left, right = control_row[field], treatment_row[field]
                if left in (None, "") or right in (None, ""):
                    return None
                return float(right) - float(left)

            contrasts.append({
                "training_seed": seed,
                "treatment_objective": objective,
                "control_objective": "binary",
                "decision_accuracy_change": delta("decision_accuracy"),
                "wrong_execution_change": delta("wrong_execution_rate"),
                "high_confidence_wrong_execution_change": delta("high_confidence_wrong_execution_rate"),
                "unsupported_wrong_adoption_change": delta("adopted_unsupported_wrong_rate"),
                "verified_correct_adoption_change": delta("adopted_verified_correct_rate"),
                "prohibited_action_change": delta("prohibited_action_rate"),
            })
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
    MANIFEST_OUT.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {LEVELS_OUT}: {len(levels)} checkpoints")
    print(f"wrote {CONTRASTS_OUT}: {len(contrasts)} matched contrasts")
    print(f"wrote {MANIFEST_OUT}: raw response hash and frozen design")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
