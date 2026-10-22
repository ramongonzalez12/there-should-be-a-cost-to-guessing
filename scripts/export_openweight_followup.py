#!/usr/bin/env python3
"""Export the extended GPT-OSS, Kimi, and DeepSeek family follow-up."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INITIAL = ROOT / "runs" / "finetune" / "openweight_family_v1"
DEFAULT_RUN = ROOT / "runs" / "finetune" / "openweight_family_v2"
DEFAULT_OUT = ROOT / "data" / "processed"


def _read(path: pathlib.Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: pathlib.Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_csv(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _profile_row(path: pathlib.Path, *, model_stage: str) -> dict[str, object]:
    arm = _read(path / "arm.json")
    # Failed profiles persist their terminal gate in arm.json, while complete
    # profiles keep the same verdict in the dedicated rollout-health artifact.
    health = arm.get("health_gate") or _read(path / "rollout_health.json")
    invalid = float(health["rates"]["INVALID"])
    return {
        "model_stage": model_stage,
        "responses": int(health["n"]),
        "max_tokens": int(arm["workload"]["max_tokens"]),
        "malformed_count": round(invalid * int(health["n"])),
        "malformed_rate": invalid,
        "gate": "pass" if health["status"] == "GREEN" else "fail",
    }


def summarize_transfer(contrasts: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in contrasts:
        grouped.setdefault(str(row["evaluation_domain"]), []).append(row)
    output = []
    for domain, rows in sorted(grouped.items()):
        accuracy = [float(row["accuracy_change"]) for row in rows]
        risk = [float(row["high_confidence_wrong_change"]) for row in rows]
        score = [float(row["quadratic_score_change"]) for row in rows]
        output.append({
            "evaluation_domain": domain,
            "matched_pairs": len(rows),
            "median_accuracy_change": statistics.median(accuracy),
            "min_accuracy_change": min(accuracy),
            "max_accuracy_change": max(accuracy),
            "median_high_confidence_wrong_change": statistics.median(risk),
            "min_high_confidence_wrong_change": min(risk),
            "max_high_confidence_wrong_change": max(risk),
            "risk_reductions": sum(value < 0 for value in risk),
            "median_confidence_calibrated_score_change": statistics.median(score),
            "min_confidence_calibrated_score_change": min(score),
            "max_confidence_calibrated_score_change": max(score),
            "score_improvements": sum(value > 0 for value in score),
        })
    return output


def summarize_hidden(summary: dict[str, object]) -> list[dict[str, object]]:
    pairs: dict[int, dict[str, dict[str, object]]] = {}
    for cell in summary["by_checkpoint"].values():
        objective = str(cell.get("objective"))
        seed = cell.get("training_seed")
        if objective in {"binary", "quadratic"} and isinstance(seed, int):
            pairs.setdefault(seed, {})[objective] = cell
    rows = []
    for seed, pair in sorted(pairs.items()):
        if set(pair) != {"binary", "quadratic"}:
            raise ValueError(f"incomplete hidden pair for seed {seed}")
        rows.append({
            "training_seed": seed,
            "binary_unauthorized_rate": pair["binary"]["unauthorized_action_rate"],
            "quadratic_unauthorized_rate": pair["quadratic"]["unauthorized_action_rate"],
            "unauthorized_rate_change": (
                float(pair["quadratic"]["unauthorized_action_rate"])
                - float(pair["binary"]["unauthorized_action_rate"])
            ),
            "high_confidence_unauthorized_change": (
                float(pair["quadratic"]["high_confidence_unauthorized_rate"])
                - float(pair["binary"]["high_confidence_unauthorized_rate"])
            ),
            "authorized_completion_change": (
                float(pair["quadratic"]["authorized_control_completion"])
                - float(pair["binary"]["authorized_control_completion"])
            ),
        })
    return rows


def _spend(roots: list[pathlib.Path]) -> tuple[float, list[dict[str, object]]]:
    rows = []
    total = 0.0
    for root in roots:
        for ledger in sorted(root.glob("**/spend.jsonl")):
            cost = sum(float(row.get("cost_usd", 0.0)) for row in _jsonl(ledger))
            rows.append({"run": str(ledger.parent.relative_to(ROOT)), "spent_usd": cost})
            total += cost
    return total, rows


def export(initial: pathlib.Path, run: pathlib.Path, output: pathlib.Path) -> dict[str, object]:
    gates = [
        _profile_row(run / "gpt_oss_profile_101", model_stage="GPT-OSS untouched, 512 tokens"),
        _profile_row(run / "gpt_oss_format_profile_101", model_stage="GPT-OSS after syntax lesson, seed 101"),
        _profile_row(run / "gpt_oss_format_profile_202", model_stage="GPT-OSS after syntax lesson, seed 202"),
    ]
    for directory, label in (
        ("kimi_format_profile_101", "Kimi after syntax lesson, seed 101"),
        ("kimi_format_profile_202", "Kimi after syntax lesson, seed 202"),
        ("deepseek_failure_replay_512", "DeepSeek prior failures replayed at 512 tokens"),
        ("deepseek_format_failure_replay_512",
         "DeepSeek after syntax lesson, prior failures at 512 tokens"),
    ):
        if (run / directory / "arm.json").exists():
            gates.append(_profile_row(run / directory, model_stage=label))

    census = _read(run / "gpt_oss_checkpoints.json")
    training = [{
        "model": "GPT-OSS 20B after shared syntax lesson",
        "planned_pairs": census["planned_pairs"],
        "complete_pairs": census["matched_pairs_admitted"],
        "failed_pairs": int(census["planned_pairs"]) - int(census["matched_pairs_admitted"]),
        "evaluated_checkpoints": len(census["checkpoints"]),
    }]
    transfer = summarize_transfer(_read(run / "gpt_oss_evaluation" / "summary.json")["contrasts"])
    hidden = summarize_hidden(_read(run / "gpt_oss_hidden" / "summary.json"))
    spent, spend_rows = _spend([initial, run])
    _write_csv(output / "openweight_followup_gates.csv", gates)
    _write_csv(output / "openweight_followup_training.csv", training)
    _write_csv(output / "openweight_followup_transfer.csv", transfer)
    _write_csv(output / "openweight_followup_hidden.csv", hidden)
    _write_csv(output / "openweight_followup_spend.csv", spend_rows)
    manifest = {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "planned_training_pairs": census["planned_pairs"],
        "complete_training_pairs": census["matched_pairs_admitted"],
        "four_domain_responses": sum(
            int(cell["n"])
            for cell in _read(run / "gpt_oss_evaluation" / "summary.json")["cells"].values()
        ),
        "hidden_records": _read(run / "gpt_oss_hidden" / "summary.json")["records"],
        # Two failed sampling steps predated the ledger-order fix. Their raw
        # responses prove the calls occurred but not their exact token counts,
        # so the ledger backfills each at its declared maximum. This total is a
        # conservative recorded liability, not a falsely precise invoice.
        "recorded_spend_usd": round(spent, 9),
        "hard_program_cap_usd": 20.0,
        "outputs": [
            "data/processed/openweight_followup_gates.csv",
            "data/processed/openweight_followup_training.csv",
            "data/processed/openweight_followup_transfer.csv",
            "data/processed/openweight_followup_hidden.csv",
            "data/processed/openweight_followup_spend.csv",
        ],
    }
    (output / "openweight_followup_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=pathlib.Path, default=DEFAULT_INITIAL)
    parser.add_argument("--run", type=pathlib.Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    print(json.dumps(export(args.initial, args.run, args.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
