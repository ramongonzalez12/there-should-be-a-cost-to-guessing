#!/usr/bin/env python3
"""Build an axis-preserving matrix from the saved dose-grid evaluations.

The three axes answer different questions and must remain separate:

* ``objective`` says which reward trained the checkpoint.
* ``step`` says how much training that policy received.
* ``scoring_rule`` says how a stored response is evaluated after generation.

All calculations in this script are offline.  The raw responses are sufficient
statistics for rescoring, so this analysis never makes a model or network call.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import pathlib
import statistics
import sys
from collections.abc import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from belowzero.rules import RULES


def _portable_path(path) -> str:
    """Manifest paths are labels; the sha256 recorded beside them is the
    identity. Record repo-relative (or sibling-archive-relative) strings so a
    committed manifest never contains an absolute home directory."""
    p = pathlib.Path(path).resolve()
    for base in (ROOT, ROOT.parent):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return p.name
from belowzero.training_contract import rescore_stored_outcome

OBJECTIVES = (
    "binary",
    "quadratic",
    "quad_cost_0.04",
    "quad_cost_0.09",
    "quad_cost_0.16",
)
STEPS = tuple(range(25, 501, 25))
SCORING_RULES = (
    "binary",
    "quadratic",
    "quad_cost_0.04",
    "quad_cost_0.09",
    "quad_cost_0.16",
    "log",
    "spherical",
)
COSTS = {
    "quad_cost_0.04": 0.04,
    "quad_cost_0.09": 0.09,
    "quad_cost_0.16": 0.16,
}


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    """Read a JSON-lines artifact and reject blank/malformed records normally."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: pathlib.Path) -> str:
    """Hash each raw response file so the derived matrices name their inputs."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _objective(record: dict) -> str:
    """Recover the exact cost arm instead of collapsing all three to quad_cost."""
    arm = record.get("arm")
    if arm == "base" or record.get("reward_rule") == "base":
        return "base"
    if arm in OBJECTIVES:
        return str(arm)
    text = " ".join(
        str(record.get(field, ""))
        for field in ("checkpoint", "run", "reward_rule")
    )
    for objective in OBJECTIVES:
        if objective in text:
            return objective
    raise ValueError(f"cannot recover objective from record: {record.get('checkpoint')}")


def _stored_score(record: dict, scoring_rule: str) -> float:
    """Apply one named rule to a saved knowledge or sycophancy turn."""
    if scoring_rule in COSTS:
        return rescore_stored_outcome(
            record, "quad_cost", assertion_cost=COSTS[scoring_rule]
        )
    return rescore_stored_outcome(record, scoring_rule)


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return statistics.fmean(values) if values else None


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    """Write stable-column CSV output that is easy to inspect in a spreadsheet."""
    if not rows:
        raise ValueError(f"refusing to write an empty matrix: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def knowledge_matrix(records: list[dict]) -> list[dict]:
    """One row per checkpoint with seven post-hoc score columns."""
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for record in records:
        grouped[str(record["checkpoint"])].append(record)

    rows = []
    for checkpoint, cells in grouped.items():
        objective = "base" if checkpoint == "base" else _objective(cells[0])
        step = 0 if checkpoint == "base" else int(float(cells[0]["dose"]))
        attempted = [
            cell for cell in cells if cell["outcome"] in {"CORRECT", "INCORRECT"}
        ]
        probabilities = [float(cell["probability"]) for cell in attempted]
        row = {
            "checkpoint": checkpoint,
            "objective": objective,
            "step": step,
            "n": len(cells),
            "accuracy": _mean(cell["outcome"] == "CORRECT" for cell in cells),
            "coverage": _mean(
                cell["outcome"] in {"CORRECT", "INCORRECT"} for cell in cells
            ),
            "abstention_rate": _mean(
                cell["outcome"] == "ABSTAINED" for cell in cells
            ),
            "invalid_rate": _mean(cell["outcome"] == "INVALID" for cell in cells),
            "mean_probability": _mean(probabilities),
            "brier": _mean(
                (float(cell["probability"]) - float(cell["outcome"] == "CORRECT"))
                ** 2
                for cell in attempted
            ),
        }
        for rule in SCORING_RULES:
            row[f"score_{rule}"] = _mean(_stored_score(cell, rule) for cell in cells)
        rows.append(row)
    return sorted(rows, key=lambda row: (OBJECTIVES.index(row["objective"]), row["step"]) if row["objective"] in OBJECTIVES else (-1, 0))


def _behaviour_score(record: dict, scoring_rule: str) -> float:
    """Score compliance as the event, matching the evaluator's diagnostic.

    The elicited probability is answer confidence rather than compliance
    confidence.  These are therefore diagnostic columns, not primary outcomes.
    Records without a reported probability are excluded exactly as they are in
    ``evaluate_behaviour.py``.
    """
    probability = float(record["probability"])
    correct = not bool(record["violated"])
    if scoring_rule in COSTS:
        return float(RULES["quad_cost"](probability, correct, c=COSTS[scoring_rule]))
    return float(RULES[scoring_rule](probability, correct))


def behaviour_matrix(records: list[dict]) -> list[dict]:
    """One row per checkpoint with primary violations and score diagnostics."""
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for record in records:
        grouped[str(record["checkpoint"])].append(record)

    rows = []
    for checkpoint, cells in grouped.items():
        usable = [cell for cell in cells if cell.get("probability") is not None]
        row = {
            "checkpoint": checkpoint,
            "objective": _objective(cells[0]),
            "step": int(cells[0]["step"]),
            "n": len(cells),
            "confidence_weighted_n": len(usable),
            "violation_rate": _mean(float(cell["violated"]) for cell in cells),
            "invalid_rate": _mean(not cell["formatted"] for cell in cells),
            "abstention_rate": _mean(cell["abstained"] for cell in cells),
            "mean_probability": _mean(float(cell["probability"]) for cell in usable),
        }
        by_category: dict[str, list[dict]] = collections.defaultdict(list)
        for cell in cells:
            by_category[str(cell["category"])].append(cell)
        for category, category_cells in sorted(by_category.items()):
            row[f"violation_{category}"] = _mean(
                float(cell["violated"]) for cell in category_cells
            )
        for rule in SCORING_RULES:
            row[f"compliance_score_{rule}"] = _mean(
                _behaviour_score(cell, rule) for cell in usable
            )
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            (OBJECTIVES.index(row["objective"]), row["step"])
            if row["objective"] in OBJECTIVES
            else (-1, 0)
        ),
    )


def sycophancy_matrix(records: list[dict], summary: dict) -> list[dict]:
    """One row per checkpoint and pressure arm, with seven score deltas."""
    grouped: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for record in records:
        grouped[(str(record["checkpoint"]), str(record["arm"]))].append(record)

    rows = []
    for (checkpoint, pressure_arm), cells in grouped.items():
        saved = summary["by_checkpoint_arm"][f"{checkpoint}|{pressure_arm}"]
        row = {
            "checkpoint": checkpoint,
            "objective": _objective(cells[0]),
            "step": int(cells[0]["step"]),
            "pressure_arm": pressure_arm,
            "n": saved["n"],
            "n_usable": saved["n_usable"],
            "adoption_rate": saved["adoption_rate"],
            "flip_rate": saved["flip_rate"],
            "first_accuracy": saved["accuracy_first"],
            "second_accuracy": saved["accuracy_second"],
            "second_turn_invalid_rate": saved["second_turn_invalid_rate"],
            "abandoned_correct_rate": saved.get("abandoned_correct_rate"),
            "corrected_wrong_rate": saved.get("corrected_wrong_rate"),
        }
        for rule in SCORING_RULES:
            row[f"score_delta_{rule}"] = _mean(
                _stored_score(cell["second"], rule)
                - _stored_score(cell["first"], rule)
                for cell in cells
            )
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            OBJECTIVES.index(row["objective"]),
            row["step"],
            row["pressure_arm"],
        ),
    )


def long_matrix(
    knowledge: list[dict], behaviour: list[dict], sycophancy: list[dict]
) -> list[dict]:
    """Normalize all outputs without merging the distinct experimental axes."""
    rows: list[dict] = []

    def add(source: str, row: dict, metric: str, value, *, context="neutral", rule=""):
        rows.append(
            {
                "evaluation": source,
                "objective": row["objective"],
                "step": row["step"],
                "checkpoint": row["checkpoint"],
                "response_context": context,
                "metric": metric,
                "scoring_rule": rule,
                "value": value,
                "n": row["n"],
            }
        )

    for row in knowledge:
        for metric in (
            "accuracy",
            "coverage",
            "abstention_rate",
            "invalid_rate",
            "mean_probability",
            "brier",
        ):
            add("knowledge", row, metric, row[metric])
        for rule in SCORING_RULES:
            add("knowledge", row, "expected_score", row[f"score_{rule}"], rule=rule)

    for row in behaviour:
        for metric in (
            "violation_rate",
            "invalid_rate",
            "abstention_rate",
            "mean_probability",
        ):
            add("behaviour", row, metric, row[metric])
        for key, value in row.items():
            if key.startswith("violation_") and key != "violation_rate":
                add("behaviour", row, key, value)
        for rule in SCORING_RULES:
            add(
                "behaviour",
                row,
                "diagnostic_compliance_score",
                row[f"compliance_score_{rule}"],
                rule=rule,
            )

    for row in sycophancy:
        context = row["pressure_arm"]
        for metric in (
            "adoption_rate",
            "flip_rate",
            "first_accuracy",
            "second_accuracy",
            "second_turn_invalid_rate",
            "abandoned_correct_rate",
            "corrected_wrong_rate",
        ):
            if row[metric] is not None:
                add("sycophancy", row, metric, row[metric], context=context)
        for rule in SCORING_RULES:
            add(
                "sycophancy",
                row,
                "score_delta",
                row[f"score_delta_{rule}"],
                context=context,
                rule=rule,
            )
    return rows


def _validate_grid(rows: list[dict], *, include_base: bool = False) -> None:
    """Fail closed if any objective/step cell is missing or duplicated."""
    observed = collections.Counter(
        (row["objective"], int(row["step"]))
        for row in rows
        if row["objective"] != "base"
    )
    expected = {(objective, step) for objective in OBJECTIVES for step in STEPS}
    if set(observed) != expected or any(count != 1 for count in observed.values()):
        raise ValueError("matrix does not contain exactly one row per objective/step")
    if include_base and not any(row["objective"] == "base" for row in rows):
        raise ValueError("knowledge matrix is missing the base model")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behaviour", type=pathlib.Path, required=True)
    parser.add_argument(
        "--behaviour-base",
        type=pathlib.Path,
        help="optional matching untuned-base evaluation directory",
    )
    parser.add_argument("--sycophancy", type=pathlib.Path, required=True)
    parser.add_argument("--knowledge", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

    behaviour_path = args.behaviour / "responses.jsonl"
    behaviour_paths = [behaviour_path]
    if args.behaviour_base is not None:
        behaviour_paths.append(args.behaviour_base / "responses.jsonl")
    sycophancy_path = args.sycophancy / "responses.jsonl"
    knowledge_path = args.knowledge / "responses.jsonl"
    sycophancy_summary = json.loads(
        (args.sycophancy / "summary.json").read_text(encoding="utf-8")
    )

    knowledge = knowledge_matrix(_read_jsonl(knowledge_path))
    behaviour = behaviour_matrix(
        [record for path in behaviour_paths for record in _read_jsonl(path)]
    )
    sycophancy = sycophancy_matrix(
        _read_jsonl(sycophancy_path), sycophancy_summary
    )
    _validate_grid(knowledge, include_base=True)
    _validate_grid(behaviour, include_base=args.behaviour_base is not None)
    # Sycophancy has two pressure-arm rows per objective/step. Validate each arm
    # independently so a missing arm cannot be hidden by a duplicate other arm.
    for arm in ("wrong", "right"):
        _validate_grid([row for row in sycophancy if row["pressure_arm"] == arm])

    args.out.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out / "knowledge_matrix.csv", knowledge)
    _write_csv(args.out / "behaviour_matrix.csv", behaviour)
    _write_csv(args.out / "sycophancy_matrix.csv", sycophancy)
    combined = long_matrix(knowledge, behaviour, sycophancy)
    _write_csv(args.out / "comparison_matrix_long.csv", combined)

    manifest = {
        "schema_version": 1,
        "axes": {
            "objectives": list(OBJECTIVES),
            "steps": list(STEPS),
            "scoring_rules": list(SCORING_RULES),
            "response_contexts": ["neutral", "wrong", "right"],
        },
        "inputs": {
            "behaviour": [
                {"path": _portable_path(path), "sha256": _sha256(path)}
                for path in behaviour_paths
            ],
            "sycophancy": {"path": _portable_path(sycophancy_path),
                           "sha256": _sha256(sycophancy_path)},
            "knowledge": {"path": _portable_path(knowledge_path),
                          "sha256": _sha256(knowledge_path)},
        },
        "row_counts": {
            "knowledge": len(knowledge),
            "behaviour": len(behaviour),
            "sycophancy": len(sycophancy),
            "long": len(combined),
        },
        "notes": {
            "behaviour_scores": "Diagnostic only: reported probability concerns answer correctness, not compliance.",
            "scoring": "All score columns are post-hoc applications to the same stored neutral response; they are not prompt conditions.",
            "sycophancy": "Wrong and right pressure arms stay separate because abandoning a correct answer and correcting a wrong answer have opposite meanings.",
        },
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["row_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
