#!/usr/bin/env python3
"""Export the cross-domain and matched behavior runs into committed tables.

The two output tables answer different questions. The transfer table reports
whether the calibration objective changes performance and confidence quality
outside its training subject. The behavior table reports separate safety and
agentic endpoints, including their control rates, so refusal or inaction cannot
masquerade as alignment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "runs" / "finetune" / "domain_transfer_v1"
TRANSFER_OUT = ROOT / "data" / "processed" / "domain_transfer_contrasts.csv"
BEHAVIOR_OUT = ROOT / "data" / "processed" / "domain_alignment_behavior.csv"
MANIFEST_OUT = ROOT / "data" / "processed" / "domain_alignment_manifest.json"

TRANSFER_FIELDS = (
    "training_domain",
    "evaluation_domain",
    "n",
    "accuracy_change",
    "accuracy_ci_low",
    "accuracy_ci_high",
    "confidence_calibrated_score_change",
    "score_ci_low",
    "score_ci_high",
    "high_confidence_wrong_change",
)

BEHAVIOR_FIELDS = (
    "training_domain",
    "unauthorized_shortcut_binary",
    "unauthorized_shortcut_quadratic",
    "unauthorized_shortcut_change",
    "benign_tool_success_binary",
    "benign_tool_success_quadratic",
    "benign_tool_success_change",
    "goal_appropriate_binary",
    "goal_appropriate_quadratic",
    "goal_appropriate_change",
    "tamper_binary",
    "tamper_quadratic",
    "concealment_binary",
    "concealment_quadratic",
    "prohibited_n_binary",
    "prohibited_n_quadratic",
    "xstest_benign_refusal_binary",
    "xstest_benign_refusal_quadratic",
    "xstest_benign_refusal_change",
    "xstest_parse_binary",
    "xstest_parse_quadratic",
    "xstest_parse_change",
    "xstest_unsafe_compliance_binary",
    "xstest_unsafe_compliance_quadratic",
    "xstest_unsafe_compliance_change",
)


def _read(path: pathlib.Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(
    path: pathlib.Path, fields: tuple[str, ...], rows: list[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _difference(control: object, treatment: object) -> float | str:
    """Return treatment minus control while retaining undefined endpoints."""
    if control is None or treatment is None:
        return ""
    return float(treatment) - float(control)


def export(root: pathlib.Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    transfer_path = root / "evaluation_matrix" / "summary.json"
    xstest_path = root / "xstest_actions_v1" / "summary.json"
    agentic_path = root / "plural_prudence_v1" / "summary.json"
    transfer = _read(transfer_path)
    xstest = _read(xstest_path)
    agentic = _read(agentic_path)

    transfer_rows = []
    for row in transfer["contrasts"]:
        accuracy_interval = row["accuracy_change_interval_95"]
        score_interval = row["quadratic_score_change_interval_95"]
        transfer_rows.append(
            {
                "training_domain": row["training_domain"],
                "evaluation_domain": row["evaluation_domain"],
                "n": row["n"],
                "accuracy_change": row["accuracy_change"],
                "accuracy_ci_low": accuracy_interval[0],
                "accuracy_ci_high": accuracy_interval[1],
                "confidence_calibrated_score_change": row[
                    "quadratic_score_change"
                ],
                "score_ci_low": score_interval[0],
                "score_ci_high": score_interval[1],
                "high_confidence_wrong_change": row[
                    "high_confidence_wrong_change"
                ],
            }
        )
    transfer_rows.sort(
        key=lambda row: (str(row["training_domain"]), str(row["evaluation_domain"]))
    )

    xstest_cells = xstest["cells"]
    agentic_cells = agentic["by_cell"]
    behavior_rows = []
    for domain in ("medicine", "math", "ethics"):
        binary_agent = agentic_cells[f"{domain}-binary|neutral"]
        quadratic_agent = agentic_cells[f"{domain}-quadratic|neutral"]
        binary_safety = xstest_cells[f"{domain}-binary"]
        quadratic_safety = xstest_cells[f"{domain}-quadratic"]

        row: dict[str, object] = {"training_domain": domain}
        for output_name, track, metric in (
            ("unauthorized_shortcut", "integrity", "unauthorized_shortcut_rate"),
            ("benign_tool_success", "integrity", "benign_tool_success"),
            ("goal_appropriate", "goal", "appropriate_action_rate"),
            ("tamper", "integrity", "tamper_rate"),
            ("concealment", "integrity", "concealment_given_prohibited"),
        ):
            control = binary_agent[track][metric]
            treatment = quadratic_agent[track][metric]
            row[f"{output_name}_binary"] = "" if control is None else control
            row[f"{output_name}_quadratic"] = "" if treatment is None else treatment
            if f"{output_name}_change" in BEHAVIOR_FIELDS:
                row[f"{output_name}_change"] = _difference(control, treatment)
        row["prohibited_n_binary"] = binary_agent["integrity"]["prohibited_n"]
        row["prohibited_n_quadratic"] = quadratic_agent["integrity"]["prohibited_n"]

        for output_name, metric in (
            ("xstest_benign_refusal", "benign_refusal_rate"),
            ("xstest_parse", "parse_rate"),
            ("xstest_unsafe_compliance", "unsafe_compliance_rate"),
        ):
            control = binary_safety[metric]
            treatment = quadratic_safety[metric]
            row[f"{output_name}_binary"] = control
            row[f"{output_name}_quadratic"] = treatment
            row[f"{output_name}_change"] = _difference(control, treatment)
        behavior_rows.append(row)

    _write_csv(TRANSFER_OUT, TRANSFER_FIELDS, transfer_rows)
    _write_csv(BEHAVIOR_OUT, BEHAVIOR_FIELDS, behavior_rows)

    # Hash the design, exact items, raw responses, and summary for every
    # evaluation. The committed tables can then be traced back to a complete
    # local audit trail without committing model outputs to the public site.
    source_paths = tuple(
        root / directory / filename
        for directory, item_filename in (
            ("evaluation_matrix", "domain_evaluation_items.json"),
            ("xstest_actions_v1", "xstest_items.json"),
            ("plural_prudence_v1", "items.json"),
        )
        for filename in ("manifest.json", item_filename, "responses.jsonl", "summary.json")
    )
    manifest = {
        "schema_version": 1,
        "sources": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
        "records": {
            "domain_transfer_cells": len(transfer_rows),
            "behavior_training_domains": len(behavior_rows),
            "agentic_responses": agentic["records"],
        },
        "spend_usd": {
            "domain_evaluation": _read(root / "evaluation_matrix" / "spend.json")[
                "spent_usd"
            ],
            "xstest": _read(root / "xstest_actions_v1" / "spend.json")["spent_usd"],
            "agentic": _read(root / "plural_prudence_v1" / "spend.json")[
                "spent_usd"
            ],
        },
        "committed_outputs": [
            str(TRANSFER_OUT.relative_to(ROOT)),
            str(BEHAVIOR_OUT.relative_to(ROOT)),
        ],
    }
    MANIFEST_OUT.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return transfer_rows, behavior_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    transfer_rows, behavior_rows = export(args.root)
    print(f"wrote {TRANSFER_OUT}: {len(transfer_rows)} paired domain cells")
    print(f"wrote {BEHAVIOR_OUT}: {len(behavior_rows)} paired behavior rows")
    print(f"wrote {MANIFEST_OUT}: source hashes and spend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
