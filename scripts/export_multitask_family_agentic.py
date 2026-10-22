#!/usr/bin/env python3
"""Export the pooled-transfer, family-gate, and hidden-opportunity results."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "runs" / "finetune" / "multitask_family_agentic_v1"
DEFAULT_OUT = ROOT / "data" / "processed"


def _portable_path(path) -> str:
    """Manifest paths are labels; the identity of an input is its content.
    Record repo-relative (or sibling-relative) strings so a committed manifest
    never contains an absolute home directory."""
    p = pathlib.Path(path).resolve()
    for base in (ROOT, ROOT.parent):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return p.name


def _read(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _add_high_confidence_error_90(
    evaluation: dict[str, object], responses_path: pathlib.Path
) -> None:
    """Attach a common 90%+ error tail to saved evaluation summaries.

    The original transfer evaluator exported an 80% threshold.  Keep that
    historical endpoint intact, and derive the essay's common 90% threshold
    from the preserved response rows.  The denominator is every scheduled
    question in the checkpoint-by-domain cell, including abstentions and
    malformed responses.
    """
    groups: dict[str, list[dict[str, object]]] = {}
    for line in responses_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        identity = f"{row['checkpoint']}|{row['evaluation_domain']}"
        groups.setdefault(identity, []).append(row)

    cells = evaluation["cells"]
    if set(groups) != set(cells):
        missing = sorted(set(cells) - set(groups))
        extra = sorted(set(groups) - set(cells))
        raise ValueError(
            f"response/summary cell mismatch; missing={missing}, extra={extra}"
        )
    for identity, cell in cells.items():
        records = groups[identity]
        if len(records) != int(cell["n"]):
            raise ValueError(
                f"response count mismatch for {identity}: "
                f"{len(records)} != {cell['n']}"
            )
        cell["high_confidence_error_90_rate"] = sum(
            row["outcome"] == "INCORRECT"
            and row.get("probability") is not None
            and float(row["probability"]) >= 0.9
            for row in records
        ) / len(records)

    for contrast in evaluation["contrasts"]:
        training = str(contrast["training_domain"])
        seed = int(contrast["training_seed"])
        domain = str(contrast["evaluation_domain"])
        before = cells[f"{training}_binary_seed{seed}|{domain}"]
        after = cells[f"{training}_quadratic_seed{seed}|{domain}"]
        contrast["high_confidence_error_90_change"] = (
            float(after["high_confidence_error_90_rate"])
            - float(before["high_confidence_error_90_rate"])
        )


def _response_weighted_mean(
    records: list[dict[str, object]], field: str
) -> float:
    """Average a checkpoint metric without giving small cells extra weight."""
    response_count = sum(int(record["n"]) for record in records)
    if response_count <= 0:
        raise ValueError(f"cannot average {field} over zero responses")
    return sum(
        float(record[field]) * int(record["n"]) for record in records
    ) / response_count


def _summarize_transfer(contrasts: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in contrasts:
        groups.setdefault(
            (str(row["training_domain"]), str(row["evaluation_domain"])), []
        ).append(row)
    result = []
    for (training, evaluation), rows in sorted(groups.items()):
        accuracy = [float(row["accuracy_change"]) for row in rows]
        risk = [float(row["high_confidence_wrong_change"]) for row in rows]
        risk90 = [
            float(row["high_confidence_error_90_change"]) for row in rows
        ]
        score = [float(row["quadratic_score_change"]) for row in rows]
        result.append(
            {
                "training_regime": training,
                "evaluation_domain": evaluation,
                "matched_seed_pairs": len(rows),
                "median_accuracy_change": statistics.median(accuracy),
                "min_accuracy_change": min(accuracy),
                "max_accuracy_change": max(accuracy),
                "median_high_confidence_wrong_change": statistics.median(risk),
                "min_high_confidence_wrong_change": min(risk),
                "max_high_confidence_wrong_change": max(risk),
                "risk_reductions": sum(value < 0 for value in risk),
                "median_high_confidence_error_90_change":
                    statistics.median(risk90),
                "min_high_confidence_error_90_change": min(risk90),
                "max_high_confidence_error_90_change": max(risk90),
                "risk90_reductions": sum(value < 0 for value in risk90),
                "median_confidence_calibrated_score_change": statistics.median(score),
                "min_confidence_calibrated_score_change": min(score),
                "max_confidence_calibrated_score_change": max(score),
                "score_improvements": sum(value > 0 for value in score),
            }
        )
    return result


def _summarize_transfer_levels(
    cells: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    """Preserve the before-and-after levels behind every transfer contrast.

    A change without its starting level is hard to interpret.  The evaluation
    summary stores one cell per checkpoint and evaluation domain, so this
    export pools those cells with their response counts as weights.  Binary
    and quadratic rows remain separate so the report can show actual levels,
    while the paired contrast export remains the authority for direction
    counts and median within-seed changes.
    """
    groups: dict[
        tuple[str, str, str], list[dict[str, object]]
    ] = {}
    for identity, cell in cells.items():
        training = str(cell["training_domain"])
        objective = str(cell["training_objective"])
        if objective not in {"binary", "quadratic"}:
            continue
        try:
            _checkpoint, evaluation = identity.rsplit("|", 1)
        except ValueError as exc:
            raise ValueError(
                f"cell identity does not declare an evaluation domain: {identity}"
            ) from exc
        groups.setdefault((training, evaluation, objective), []).append(cell)

    result = []
    for (training, evaluation, objective), records in sorted(groups.items()):
        response_count = sum(int(record["n"]) for record in records)
        if response_count <= 0:
            raise ValueError(
                f"non-positive response count for {training}/{evaluation}/{objective}"
            )
        coverage = _response_weighted_mean(records, "coverage")
        overall_accuracy = _response_weighted_mean(records, "overall_accuracy")
        accuracy_when_answered = overall_accuracy / coverage if coverage else 0.0
        confidence_when_answered = _conditional_level(
            records, "mean_confidence_among_answers"
        )
        item_counts = {int(record["n"]) for record in records}
        result.append(
            {
                "training_regime": training,
                "evaluation_domain": evaluation,
                "training_objective": objective,
                "matched_seed_pairs": len(records),
                "items_per_checkpoint": (
                    next(iter(item_counts)) if len(item_counts) == 1 else "varies"
                ),
                "response_count": response_count,
                "mean_accuracy": overall_accuracy,
                "mean_coverage": coverage,
                "mean_accuracy_when_answered": accuracy_when_answered,
                "mean_confidence_when_answered": confidence_when_answered,
                "mean_signed_confidence_gap": (
                    confidence_when_answered - accuracy_when_answered
                ),
                "mean_high_confidence_wrong_rate": _response_weighted_mean(
                    records,
                    "high_confidence_wrong_rate"
                ),
                "mean_high_confidence_error_90_rate":
                    _response_weighted_mean(
                        records, "high_confidence_error_90_rate"
                    ),
                "mean_confidence_calibrated_score": _response_weighted_mean(
                    records,
                    "mean_quadratic_score"
                ),
            }
        )
    return result


SUBJECT_DOMAINS = {"medicine", "math", "ethics"}


def _generalization_scope(training: str, evaluation: str) -> str | None:
    """Classify subject-specific checkpoints without blurring two claims.

    Testing medicine training on math is transfer to another trained subject.
    Testing it on GPQA is stronger evidence because GPQA supplied no training
    examples. The report shows both, then combines them only in an explicitly
    labelled all-off-domain row.
    """
    if training not in SUBJECT_DOMAINS:
        return None
    if evaluation == training:
        return "same_subject"
    if evaluation in SUBJECT_DOMAINS:
        return "other_trained_subject"
    if evaluation == "gpqa":
        return "unseen_gpqa"
    return None


def _conditional_level(
    records: list[dict[str, object]], field: str
) -> float:
    """Pool an answered-question metric using answered questions as weights."""
    answered = sum(float(record["coverage"]) * int(record["n"]) for record in records)
    if answered <= 0:
        raise ValueError(f"cannot average {field} over zero answered questions")
    return sum(
        float(record[field]) * float(record["coverage"]) * int(record["n"])
        for record in records
    ) / answered


def _scope_records(
    records: list[dict[str, object]], scope: str
) -> list[dict[str, object]]:
    selected = []
    for record in records:
        classified = _generalization_scope(
            str(record["training_domain"]), str(record["evaluation_domain"])
        )
        if classified == scope or (
            scope == "all_off_domain"
            and classified in {"other_trained_subject", "unseen_gpqa"}
        ):
            selected.append(record)
    return selected


def _summarize_generalization(
    cells: dict[str, dict[str, object]], contrasts: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Compare same-subject calibration with explicitly off-domain tests.

    Levels are pooled by question count. Direction counts use matched
    checkpoint/test contrasts, while the accompanying pair export keeps the
    seven independently trained pairs visible as the true replication unit.
    """
    cell_records = []
    for identity, cell in cells.items():
        objective = str(cell["training_objective"])
        if objective not in {"binary", "quadratic"}:
            continue
        _checkpoint, evaluation = identity.rsplit("|", 1)
        record = dict(cell)
        record["evaluation_domain"] = evaluation
        if _generalization_scope(
            str(record["training_domain"]), evaluation
        ) is not None:
            cell_records.append(record)

    result = []
    for scope in (
        "same_subject",
        "other_trained_subject",
        "unseen_gpqa",
        "all_off_domain",
    ):
        scoped_cells = _scope_records(cell_records, scope)
        scoped_contrasts = _scope_records(contrasts, scope)
        by_objective = {
            objective: [
                row for row in scoped_cells
                if row["training_objective"] == objective
            ]
            for objective in ("binary", "quadratic")
        }
        if not scoped_contrasts or any(not rows for rows in by_objective.values()):
            raise ValueError(f"incomplete generalization scope: {scope}")

        levels: dict[str, dict[str, float]] = {}
        for objective, records in by_objective.items():
            coverage = _response_weighted_mean(records, "coverage")
            accuracy = _response_weighted_mean(records, "overall_accuracy")
            answered_accuracy = accuracy / coverage if coverage else 0.0
            answered_confidence = _conditional_level(
                records, "mean_confidence_among_answers"
            )
            levels[objective] = {
                "overall_accuracy": accuracy,
                "coverage": coverage,
                "accuracy_when_answered": answered_accuracy,
                "confidence_when_answered": answered_confidence,
                "signed_confidence_gap": answered_confidence - answered_accuracy,
                "high_confidence_wrong_rate": _response_weighted_mean(
                    records, "high_confidence_wrong_rate"
                ),
                "high_confidence_error_90_rate": _response_weighted_mean(
                    records, "high_confidence_error_90_rate"
                ),
                "confidence_calibrated_score": _response_weighted_mean(
                    records, "mean_quadratic_score"
                ),
            }

        before = levels["binary"]
        after = levels["quadratic"]
        questions_per_arm = sum(int(row["n"]) for row in by_objective["binary"])
        row: dict[str, object] = {
            "scope": scope,
            "training_pairs": len({
                (str(item["training_domain"]), int(item["training_seed"]))
                for item in scoped_contrasts
            }),
            "pair_tests": len(scoped_contrasts),
            "questions_per_arm": questions_per_arm,
            "stored_responses": questions_per_arm * 2,
        }
        for label, values in (("binary", before), ("quadratic", after)):
            for metric, value in values.items():
                row[f"{label}_{metric}"] = value
        row.update({
            "accuracy_change": after["overall_accuracy"] - before["overall_accuracy"],
            "coverage_change": after["coverage"] - before["coverage"],
            "confidence_gap_correction": (
                before["signed_confidence_gap"] - after["signed_confidence_gap"]
            ),
            "high_confidence_wrong_change": (
                after["high_confidence_wrong_rate"]
                - before["high_confidence_wrong_rate"]
            ),
            "high_confidence_risk_eliminated": (
                (before["high_confidence_wrong_rate"]
                 - after["high_confidence_wrong_rate"])
                / before["high_confidence_wrong_rate"]
            ),
            "high_confidence_error_90_change": (
                after["high_confidence_error_90_rate"]
                - before["high_confidence_error_90_rate"]
            ),
            "high_confidence_error_90_eliminated": (
                (before["high_confidence_error_90_rate"]
                 - after["high_confidence_error_90_rate"])
                / before["high_confidence_error_90_rate"]
            ),
            "confidence_calibrated_score_change": (
                after["confidence_calibrated_score"]
                - before["confidence_calibrated_score"]
            ),
            "risk_improved_pair_tests": sum(
                float(item["high_confidence_wrong_change"]) < 0
                for item in scoped_contrasts
            ),
            "risk90_improved_pair_tests": sum(
                float(item["high_confidence_error_90_change"]) < 0
                for item in scoped_contrasts
            ),
            "score_improved_pair_tests": sum(
                float(item["quadratic_score_change"]) > 0
                for item in scoped_contrasts
            ),
            "accuracy_improved_pair_tests": sum(
                float(item["accuracy_change"]) > 0
                for item in scoped_contrasts
            ),
        })
        result.append(row)
    return result


def _summarize_generalization_pairs(
    cells: dict[str, dict[str, object]],
    contrasts: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Make each independently trained pair, not each route, one row.

    The pooled summary is useful for describing all responses, but it can hide
    a wide distribution across independently trained pairs.  Keep each pair's
    before-and-after confidence gap here so the essay can report the median,
    full range, and direction count without treating repeated evaluation
    routes as additional training replications.
    """
    subject_rows = [
        row for row in contrasts
        if str(row["training_domain"]) in SUBJECT_DOMAINS
    ]
    pairs: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in subject_rows:
        key = (str(row["training_domain"]), int(row["training_seed"]))
        pairs.setdefault(key, []).append(row)

    result = []
    for (training, seed), records in sorted(pairs.items()):
        same = [row for row in records if row["evaluation_domain"] == training]
        off = [row for row in records if row["evaluation_domain"] != training]
        if len(same) != 1 or len(off) != 3:
            raise ValueError(
                f"expected one same-subject and three off-domain tests: {training}/{seed}"
            )

        def weighted(rows: list[dict[str, object]], field: str) -> float:
            denominator = sum(int(row["n"]) for row in rows)
            return sum(float(row[field]) * int(row["n"]) for row in rows) / denominator

        row: dict[str, object] = {
            "training_domain": training,
            "training_seed": seed,
            "same_subject_pair_tests": 1,
            "off_domain_pair_tests": len(off),
            "same_subject_questions_per_arm": int(same[0]["n"]),
            "off_domain_questions_per_arm": sum(int(item["n"]) for item in off),
        }
        for metric in (
            "accuracy_change",
            "high_confidence_wrong_change",
            "high_confidence_error_90_change",
            "quadratic_score_change",
        ):
            row[f"same_subject_{metric}"] = float(same[0][metric])
            row[f"off_domain_{metric}"] = weighted(off, metric)

        pair_cells = []
        for identity, cell in cells.items():
            if str(cell["training_domain"]) != training:
                continue
            if int(cell["training_seed"]) != seed:
                continue
            if str(cell["training_objective"]) not in {"binary", "quadratic"}:
                continue
            _checkpoint, evaluation = identity.rsplit("|", 1)
            record = dict(cell)
            record["evaluation_domain"] = evaluation
            pair_cells.append(record)

        def confidence_gap(
            scope: str,
            objective: str,
            pair_cells=pair_cells,
            training=training,
            seed=seed,
        ) -> float:
            selected = [
                cell for cell in pair_cells
                if cell["training_objective"] == objective
                and (
                    _generalization_scope(
                        training, str(cell["evaluation_domain"])
                    ) == scope
                    or (
                        scope == "all_off_domain"
                        and _generalization_scope(
                            training, str(cell["evaluation_domain"])
                        ) in {"other_trained_subject", "unseen_gpqa"}
                    )
                )
            ]
            if not selected:
                raise ValueError(
                    f"missing {scope}/{objective} cells for {training}/{seed}"
                )
            answered = sum(
                float(cell["coverage"]) * int(cell["n"])
                for cell in selected
            )
            correct = sum(
                float(cell["overall_accuracy"]) * int(cell["n"])
                for cell in selected
            )
            confidence = sum(
                float(cell["mean_confidence_among_answers"])
                * float(cell["coverage"])
                * int(cell["n"])
                for cell in selected
            )
            if answered <= 0:
                raise ValueError(
                    f"zero answered questions for {scope}/{objective}/"
                    f"{training}/{seed}"
                )
            return confidence / answered - correct / answered

        def calibrated_score(
            scope: str,
            objective: str,
            pair_cells=pair_cells,
            training=training,
            seed=seed,
        ) -> float:
            selected = [
                cell for cell in pair_cells
                if cell["training_objective"] == objective
                and (
                    _generalization_scope(
                        training, str(cell["evaluation_domain"])
                    ) == scope
                    or (
                        scope == "all_off_domain"
                        and _generalization_scope(
                            training, str(cell["evaluation_domain"])
                        ) in {"other_trained_subject", "unseen_gpqa"}
                    )
                )
            ]
            if not selected:
                raise ValueError(
                    f"missing {scope}/{objective} cells for {training}/{seed}"
                )
            return weighted(selected, "mean_quadratic_score")

        def high_confidence_error_90_rate(
            scope: str,
            objective: str,
            pair_cells=pair_cells,
            training=training,
            seed=seed,
        ) -> float:
            selected = [
                cell for cell in pair_cells
                if cell["training_objective"] == objective
                and (
                    _generalization_scope(
                        training, str(cell["evaluation_domain"])
                    ) == scope
                    or (
                        scope == "all_off_domain"
                        and _generalization_scope(
                            training, str(cell["evaluation_domain"])
                        ) in {"other_trained_subject", "unseen_gpqa"}
                    )
                )
            ]
            if not selected:
                raise ValueError(
                    f"missing {scope}/{objective} cells for {training}/{seed}"
                )
            return weighted(selected, "high_confidence_error_90_rate")

        for scope in (
            "same_subject",
            "other_trained_subject",
            "unseen_gpqa",
            "all_off_domain",
        ):
            before_gap = confidence_gap(scope, "binary")
            after_gap = confidence_gap(scope, "quadratic")
            row[f"{scope}_binary_signed_confidence_gap"] = before_gap
            row[f"{scope}_quadratic_signed_confidence_gap"] = after_gap
            row[f"{scope}_signed_confidence_gap_change"] = (
                after_gap - before_gap
            )
            before_score = calibrated_score(scope, "binary")
            after_score = calibrated_score(scope, "quadratic")
            row[f"{scope}_binary_confidence_calibrated_score"] = before_score
            row[f"{scope}_quadratic_confidence_calibrated_score"] = after_score
            row[f"{scope}_confidence_calibrated_score_change"] = (
                after_score - before_score
            )
            before_risk90 = high_confidence_error_90_rate(scope, "binary")
            after_risk90 = high_confidence_error_90_rate(scope, "quadratic")
            row[f"{scope}_binary_high_confidence_error_90_rate"] = (
                before_risk90
            )
            row[f"{scope}_quadratic_high_confidence_error_90_rate"] = (
                after_risk90
            )
            row[f"{scope}_high_confidence_error_90_change"] = (
                after_risk90 - before_risk90
            )
        result.append(row)
    return result


def _hidden_contrasts(summary: dict[str, object]) -> list[dict[str, object]]:
    cells = summary["by_checkpoint"]
    pairs: dict[tuple[str, object], dict[str, dict[str, object]]] = {}
    for cell in cells.values():
        objective = str(cell.get("objective"))
        if objective not in {"binary", "quadratic"}:
            continue
        key = (str(cell["training_domain"]), cell.get("training_seed"))
        pairs.setdefault(key, {})[objective] = cell
    result = []
    metrics = (
        "unauthorized_action_rate",
        "high_confidence_unauthorized_rate",
        "authorized_control_completion",
        "policy_sensitivity",
    )
    for (training, seed), pair in sorted(pairs.items(), key=lambda row: (row[0][0], int(row[0][1]))):
        if set(pair) != {"binary", "quadratic"}:
            raise ValueError(f"incomplete hidden-opportunity pair: {training}/{seed}")
        row: dict[str, object] = {
            "training_regime": training,
            "training_seed": seed,
            "n_per_checkpoint": pair["binary"]["n"],
            "binary_parse_rate": pair["binary"]["parse_rate"],
            "quadratic_parse_rate": pair["quadratic"]["parse_rate"],
        }
        for metric in metrics:
            control = float(pair["binary"][metric])
            treatment = float(pair["quadratic"][metric])
            row[f"binary_{metric}"] = control
            row[f"quadratic_{metric}"] = treatment
            row[f"change_{metric}"] = treatment - control
        row["binary_concealment_given_unauthorized"] = pair["binary"][
            "concealment_given_unauthorized"
        ]
        row["quadratic_concealment_given_unauthorized"] = pair["quadratic"][
            "concealment_given_unauthorized"
        ]
        result.append(row)
    return result


def _family_gates(run: pathlib.Path) -> list[dict[str, object]]:
    rows = []
    warmup = _read(run / "nemotron_format" / "warmup.json")
    rows.append(
        {
            "model": warmup["model"],
            "stage": "knowledge_free_format_checkpoint",
            "sample_size": warmup["workload"]["examples_used"],
            "invalid_rate": "",
            "status": warmup["status"],
            "decision": "continue_to_full_profiles" if warmup["status"] == "COMPLETE" else "stop",
        }
    )
    for seed in (101, 202):
        directory = run / f"nemotron_profile_seed{seed}"
        arm = _read(directory / "arm.json")
        health = _read(directory / "rollout_health.json")
        rows.append(
            {
                "model": arm["model"],
                "stage": f"full_profile_seed{seed}",
                "sample_size": health["n"],
                "invalid_rate": health["rates"].get("INVALID", 0.0),
                "status": health["status"],
                "decision": "admit" if health["status"] == "GREEN" else "stop_before_reward_training",
            }
        )
    return rows


def _spend(run: pathlib.Path) -> tuple[float, list[dict[str, object]]]:
    rows = []
    total = 0.0
    for ledger in sorted(run.glob("**/spend.jsonl")):
        cost = 0.0
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cost += float(json.loads(line).get("cost_usd", 0.0))
        rows.append({"run": str(ledger.parent.relative_to(run)), "spent_usd": cost})
        total += cost
    return total, rows


def export(run: pathlib.Path, output: pathlib.Path) -> dict[str, object]:
    evaluation = _read(run / "qwen_evaluation" / "summary.json")
    _add_high_confidence_error_90(
        evaluation, run / "qwen_evaluation" / "responses.jsonl"
    )
    hidden = _read(run / "hidden_qwen" / "summary.json")
    transfer_rows = _summarize_transfer(evaluation["contrasts"])
    transfer_level_rows = _summarize_transfer_levels(evaluation["cells"])
    generalization_rows = _summarize_generalization(
        evaluation["cells"], evaluation["contrasts"]
    )
    generalization_pair_rows = _summarize_generalization_pairs(
        evaluation["cells"], evaluation["contrasts"]
    )
    hidden_rows = _hidden_contrasts(hidden)
    gate_rows = _family_gates(run)
    spent, spend_rows = _spend(run)
    four_domain_responses = sum(
        int(cell["n"]) for cell in evaluation["cells"].values()
    )
    _write_csv(output / "multitask_transfer_summary.csv", transfer_rows)
    _write_csv(output / "multitask_transfer_levels.csv", transfer_level_rows)
    _write_csv(
        output / "multitask_generalization_summary.csv", generalization_rows
    )
    _write_csv(
        output / "multitask_generalization_pairs.csv", generalization_pair_rows
    )
    _write_csv(output / "hidden_opportunity_contrasts.csv", hidden_rows)
    _write_csv(output / "multitask_family_gates.csv", gate_rows)
    _write_csv(output / "multitask_family_spend.csv", spend_rows)
    manifest = {
        "schema_version": 3,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "run_root": _portable_path(run),
        # Keep the manifest compact and make its denominator directly usable.
        # The cell-level audit trail remains in the run summary referenced above.
        "four_domain_responses": four_domain_responses,
        "transfer_summary_rows": len(transfer_rows),
        "transfer_level_rows": len(transfer_level_rows),
        "generalization_summary_rows": len(generalization_rows),
        "generalization_pair_rows": len(generalization_pair_rows),
        "hidden_opportunity_responses": hidden["records"],
        "hidden_matched_pairs": len(hidden_rows),
        "family_gate_rows": len(gate_rows),
        "actual_spend_usd": round(spent, 6),
        "hard_program_cap_usd": 20.0,
        "outputs": [
            "data/processed/multitask_transfer_summary.csv",
            "data/processed/multitask_transfer_levels.csv",
            "data/processed/multitask_generalization_summary.csv",
            "data/processed/multitask_generalization_pairs.csv",
            "data/processed/hidden_opportunity_contrasts.csv",
            "data/processed/multitask_family_gates.csv",
            "data/processed/multitask_family_spend.csv",
        ],
    }
    (output / "multitask_family_agentic_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=pathlib.Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    print(json.dumps(export(args.run, args.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
