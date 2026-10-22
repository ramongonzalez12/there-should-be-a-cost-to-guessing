#!/usr/bin/env python3
"""Export the scaled domain replication with failed pairs in the denominator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import statistics
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Failed paid runs sometimes stop before the runner writes its final spend
# summary. Their raw token ledgers are still complete, but the budget contract
# deliberately charges the full dispatch cap when final provider usage is
# unresolved. Keeping those caps here makes the conservative figure in the
# report reproducible instead of leaving it as hand-written prose.
FAILED_DISPATCH_CAPS_USD = {
    "qwen_math_binary_seed2": 0.49,
    "qwen_math_quadratic_seed1": 0.49,
    "deepseek_math_base_profile": 1.30,
    "qwen35_medicine_base_profile": 0.24,
    "qwen35_math_base_profile": 0.31,
    "qwen35_ethics_base_profile": 0.26,
}


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty output {path}")
    fields = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        # Use repository-native LF endings. csv's platform-independent default
        # is CRLF, which makes git treat every generated line as trailing space.
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _recorded_spend(path: pathlib.Path) -> float:
    """Read a completed run's authoritative spend summary."""
    return float(json.loads(path.read_text(encoding="utf-8"))["spent_usd"])


def _ledger_spend(root: pathlib.Path) -> float:
    """Sum every preserved raw token-cost row, including failed runs."""
    total = 0.0
    for path in root.rglob("spend.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += float(json.loads(line)["cost_usd"])
    return total


def spend_audit(root: pathlib.Path) -> dict[str, object]:
    """Return both observed ledger cost and the fail-closed budget liability."""
    completed_qwen_training = sum(
        _recorded_spend(path)
        for path in (root / "qwen").glob("**/spend.json")
    )
    components = {
        "completed_qwen_training_recorded": completed_qwen_training,
        "two_failed_qwen_training_caps": 0.98,
        "qwen_evaluation_recorded": _recorded_spend(
            root / "qwen_evaluation" / "spend.json"
        ),
        "deepseek_pilot_recorded": _recorded_spend(
            root / "deepseek" / "math" / "format_pilot" / "spend.json"
        ),
        "deepseek_failed_profile_cap": 1.30,
        "qwen35_pilot_recorded": _recorded_spend(
            root / "qwen35" / "medicine" / "format_pilot" / "spend.json"
        ),
        "three_qwen35_failed_profile_caps": 0.81,
    }
    conservative = sum(components.values())
    return {
        "program_hard_cap_usd": 20.0,
        "recorded_raw_ledger_spend_usd": round(_ledger_spend(root), 6),
        "conservative_liability_usd": round(conservative, 6),
        "components_usd": {
            key: round(value, 6) for key, value in components.items()
        },
        "failed_dispatch_caps_usd": FAILED_DISPATCH_CAPS_USD,
        "rule": (
            "Completed runs use recorded spend; failed runs without a final "
            "summary use the full pre-dispatch cap."
        ),
    }


def summarize(
    contrasts: list[dict[str, object]], census: list[dict[str, object]]
) -> list[dict[str, object]]:
    planned_by_domain = {}
    admitted_by_domain = {}
    for row in census:
        domain = str(row["training_domain"])
        planned_by_domain[domain] = planned_by_domain.get(domain, 0) + 1
        admitted_by_domain[domain] = admitted_by_domain.get(domain, 0) + int(
            bool(row["matched_pair_admitted"])
        )

    result = []
    for domain in ("medicine", "math", "ethics", "all"):
        rows = contrasts if domain == "all" else [
            row for row in contrasts if row["training_domain"] == domain
        ]
        risk = [float(row["high_confidence_wrong_change"]) for row in rows]
        accuracy = [float(row["accuracy_change"]) for row in rows]
        score = [float(row["confidence_calibrated_score_change"]) for row in rows]
        planned_pairs = sum(planned_by_domain.values()) if domain == "all" else planned_by_domain[domain]
        admitted_pairs = sum(admitted_by_domain.values()) if domain == "all" else admitted_by_domain[domain]
        result.append({
            "training_domain": domain,
            "planned_training_pairs": planned_pairs,
            "admitted_training_pairs": admitted_pairs,
            "failed_training_pairs": planned_pairs - admitted_pairs,
            "observed_contrasts": len(rows),
            "planned_contrasts": planned_pairs * 3,
            "risk_reductions_observed": sum(value < 0 for value in risk),
            # A failed pair cannot be credited as an improvement. This second
            # denominator prevents the successful-pairs-only result from
            # silently erasing training instability.
            "risk_reductions_planned_denominator": sum(value < 0 for value in risk),
            "median_high_confidence_wrong_change": statistics.median(risk),
            "min_high_confidence_wrong_change": min(risk),
            "max_high_confidence_wrong_change": max(risk),
            "median_accuracy_change": statistics.median(accuracy),
            "min_accuracy_change": min(accuracy),
            "max_accuracy_change": max(accuracy),
            "score_improvements_observed": sum(value > 0 for value in score),
            "median_confidence_calibrated_score_change": statistics.median(score),
            "min_confidence_calibrated_score_change": min(score),
            "max_confidence_calibrated_score_change": max(score),
        })
    return result


def _profile_gate(model: str, domain: str, root: pathlib.Path) -> dict[str, object]:
    arm_path = root / "arm.json"
    arm = json.loads(arm_path.read_text(encoding="utf-8"))
    health = arm.get("health_gate") or (arm.get("stages") or [{}])[-1].get("health_gate")
    return {
        "model": model,
        "domain": domain,
        "stage": "full_base_profile",
        "n": health["n"],
        "invalid_rate": health["rates"].get("INVALID", 0.0),
        "status": arm["status"],
        "gate_passed": arm["status"] == "COMPLETE" and health["status"] == "GREEN",
        "reason": ";".join(health.get("reasons", [])),
    }


def _pilot_gate(model: str, domain: str, root: pathlib.Path) -> dict[str, object]:
    """Score the first response for each planned pilot identity."""
    rows = [
        json.loads(line)
        for line in (root / "rollouts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    unique = {}
    for row in rows:
        key = (int(row["step"]), str(row["item_id"]), int(row["rollout_index"]))
        unique.setdefault(key, row)
    planned = list(unique.values())
    invalid = sum(row["outcome"] == "INVALID" for row in planned)
    return {
        "model": model,
        "domain": domain,
        "stage": "format_pilot",
        "n": len(planned),
        "invalid_rate": invalid / len(planned),
        "status": "COMPLETE",
        "gate_passed": invalid == 0 and len(planned) == 64,
        "reason": (
            f"{len(rows) - len(planned)} duplicate audit rows excluded by identity"
            if len(rows) != len(planned) else ""
        ),
    }


def export(root: pathlib.Path, output: pathlib.Path) -> dict[str, object]:
    qwen_summary_path = root / "qwen_evaluation" / "summary.json"
    qwen_manifest_path = root / "qwen_checkpoints.json"
    qwen_summary = json.loads(qwen_summary_path.read_text(encoding="utf-8"))
    checkpoint_manifest = json.loads(qwen_manifest_path.read_text(encoding="utf-8"))
    contrasts = sorted(
        qwen_summary["contrasts"],
        key=lambda row: (
            int(row["training_seed"]), str(row["training_domain"]),
            str(row["evaluation_domain"]),
        ),
    )
    identities = {
        (row["training_seed"], row["training_domain"], row["evaluation_domain"])
        for row in contrasts
    }
    if len(contrasts) != len(identities):
        raise ValueError("duplicate seed/domain contrast")
    if len(contrasts) != 21:
        raise ValueError(f"expected 21 admitted contrasts, found {len(contrasts)}")
    flat_contrasts = []
    for row in contrasts:
        flat_contrasts.append({
            "model_family": row["model_family"],
            "training_seed": row["training_seed"],
            "training_domain": row["training_domain"],
            "evaluation_domain": row["evaluation_domain"],
            "n": row["n"],
            "high_confidence_wrong_change": row["high_confidence_wrong_change"],
            "accuracy_change": row["accuracy_change"],
            "accuracy_interval_low": row["accuracy_change_interval_95"][0],
            "accuracy_interval_high": row["accuracy_change_interval_95"][1],
            "confidence_calibrated_score_change": row["quadratic_score_change"],
            "score_interval_low": row["quadratic_score_change_interval_95"][0],
            "score_interval_high": row["quadratic_score_change_interval_95"][1],
        })
    aggregate = summarize(flat_contrasts, checkpoint_manifest["training_census"])

    gates = [
        _pilot_gate(
            "DeepSeek-V3.1", "math", root / "deepseek" / "math" / "format_pilot"
        ),
        _profile_gate(
            "DeepSeek-V3.1", "math", root / "deepseek" / "math" / "base_profile"
        ),
        _pilot_gate(
            "Qwen3.5-4B", "medicine", root / "qwen35" / "medicine" / "format_pilot"
        ),
    ]
    gates.extend(
        _profile_gate(
            "Qwen3.5-4B", domain, root / "qwen35" / domain / "base_profile"
        )
        for domain in ("medicine", "math", "ethics")
    )

    _write_csv(output / "domain_replication_contrasts.csv", flat_contrasts)
    _write_csv(output / "domain_replication_summary.csv", aggregate)
    _write_csv(output / "domain_replication_model_gates.csv", gates)

    sources = {
        str(path): _sha(path)
        for path in (
            qwen_summary_path,
            qwen_manifest_path,
            root / "qwen_evaluation" / "responses.jsonl",
            root / "qwen_evaluation" / "manifest.json",
            root / "manifest.json",
            root / "deepseek" / "math" / "base_profile" / "arm.json",
            root / "qwen35" / "medicine" / "base_profile" / "arm.json",
            root / "qwen35" / "math" / "base_profile" / "arm.json",
            root / "qwen35" / "ethics" / "base_profile" / "arm.json",
        )
    }
    audit = spend_audit(root)
    if audit["conservative_liability_usd"] > audit["program_hard_cap_usd"]:
        raise ValueError("conservative program liability exceeds hard cap")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "primary_sample": "300 new exact-ID-disjoint items per evaluation domain",
        "qwen_evaluation_responses": 13_500,
        "planned_qwen_training_pairs": 9,
        "admitted_qwen_training_pairs": 7,
        "failed_qwen_training_pairs": 2,
        "observed_qwen_contrasts": 21,
        "planned_qwen_contrasts": 27,
        "spend": audit,
        "sources": sources,
        "outputs": [
            "data/processed/domain_replication_contrasts.csv",
            "data/processed/domain_replication_summary.csv",
            "data/processed/domain_replication_model_gates.csv",
        ],
    }
    (output / "domain_replication_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"summary": aggregate, "gates": gates, "manifest": manifest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "data" / "processed")
    args = parser.parse_args(argv)
    print(json.dumps(export(args.root, args.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
