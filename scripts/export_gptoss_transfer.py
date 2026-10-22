#!/usr/bin/env python3
"""Export the admitted GPT-OSS subject-transfer pairs for the essay.

The GPT-OSS evaluation was split across a primary run and one supplement after
an interrupted ethics seed was retrained from the shared format checkpoint.
This exporter reconciles those two immutable summaries, verifies that every
admitted pair has all four evaluation domains, and writes one row per
independent training pair. Repeated evaluation domains stay inside the row so
they cannot be mistaken for additional fine-tuning replications.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "runs" / "finetune" / "gptoss_domain_replication"
DEFAULT_OUT = ROOT / "data" / "processed"
SUBJECTS = ("ethics", "math", "medicine")
SCOPES = ("same_subject", "other_trained_subject", "unseen_gpqa")


def _read(path: pathlib.Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: pathlib.Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _scope(training_domain: str, evaluation_domain: str) -> str:
    if evaluation_domain == training_domain:
        return "same_subject"
    if evaluation_domain == "gpqa":
        return "unseen_gpqa"
    if evaluation_domain in SUBJECTS:
        return "other_trained_subject"
    raise ValueError(f"unexpected evaluation domain: {evaluation_domain}")


def _pool_cells(cells: list[dict[str, object]]) -> dict[str, float]:
    """Pool scheduled-question metrics without changing their denominators."""
    scheduled = sum(int(cell["n"]) for cell in cells)
    attempted = sum(int(cell["n"]) * float(cell["coverage"]) for cell in cells)
    correct = sum(int(cell["n"]) * float(cell["overall_accuracy"]) for cell in cells)
    confidence_total = sum(
        int(cell["n"])
        * float(cell["coverage"])
        * float(cell["mean_confidence_among_answers"])
        for cell in cells
    )
    if attempted <= 0:
        raise ValueError("cannot calculate an answered-question gap with no answers")
    return {
        "questions": scheduled,
        "signed_confidence_gap": confidence_total / attempted - correct / attempted,
        "confidence_calibrated_score": sum(
            int(cell["n"]) * float(cell["mean_quadratic_score"])
            for cell in cells
        ) / scheduled,
        "high_confidence_error_90_rate": sum(
            int(cell["n"]) * float(cell["high_confidence_wrong_rate"])
            for cell in cells
        ) / scheduled,
    }


def build_pair_rows(
    summaries: list[dict[str, object]], census: dict[str, object]
) -> list[dict[str, object]]:
    """Return one complete transfer row per admitted matched training pair."""
    cells: dict[tuple[str, int, str, str], dict[str, object]] = {}
    contrast_ids: set[tuple[str, int, str]] = set()
    for summary in summaries:
        for label, cell in summary["cells"].items():
            objective = str(cell["training_objective"])
            if objective not in {"binary", "quadratic"}:
                continue
            evaluation_domain = str(label).rsplit("|", 1)[-1]
            if evaluation_domain not in {*SUBJECTS, "gpqa"}:
                raise ValueError(
                    f"unexpected GPT-OSS evaluation domain in {label}: "
                    f"{evaluation_domain}"
                )
            key = (
                str(cell["training_domain"]),
                int(cell["training_seed"]),
                objective,
                evaluation_domain,
            )
            if key in cells:
                raise ValueError(f"duplicate GPT-OSS transfer cell: {key}")
            cells[key] = cell
        for row in summary["contrasts"]:
            identity = (
                str(row["training_domain"]), int(row["training_seed"]),
                str(row["evaluation_domain"]),
            )
            if identity in contrast_ids:
                raise ValueError(f"duplicate GPT-OSS transfer contrast: {identity}")
            contrast_ids.add(identity)

    admitted = {
        (str(row["training_domain"]), int(row["training_seed"]))
        for row in census["training_census"]
        if row["matched_pair_admitted"]
    }
    if len(admitted) != int(census["matched_pairs_admitted"]):
        raise ValueError("admitted GPT-OSS pair count disagrees with the census")
    expected_contrasts = {
        (training_domain, seed, evaluation_domain)
        for training_domain, seed in admitted
        for evaluation_domain in (*SUBJECTS, "gpqa")
    }
    if contrast_ids != expected_contrasts:
        missing = sorted(expected_contrasts - contrast_ids)
        extra = sorted(contrast_ids - expected_contrasts)
        raise ValueError(f"GPT-OSS transfer matrix mismatch; missing={missing}, extra={extra}")

    rows = []
    for training_domain, seed in sorted(admitted):
        output: dict[str, object] = {
            "model_family": "GPT-OSS 20B",
            "training_domain": training_domain,
            "training_seed": seed,
        }
        for scope in SCOPES:
            domains = [
                domain for domain in (*SUBJECTS, "gpqa")
                if _scope(training_domain, domain) == scope
            ]
            output[f"{scope}_pair_tests"] = len(domains)
            for objective in ("binary", "quadratic"):
                pooled = _pool_cells([
                    cells[(training_domain, seed, objective, domain)]
                    for domain in domains
                ])
                output[f"{scope}_questions_per_arm"] = pooled["questions"]
                for metric in (
                    "signed_confidence_gap", "confidence_calibrated_score",
                    "high_confidence_error_90_rate",
                ):
                    output[f"{scope}_{objective}_{metric}"] = pooled[metric]
            for metric in (
                "signed_confidence_gap", "confidence_calibrated_score",
                "high_confidence_error_90_rate",
            ):
                change_name = (
                    "high_confidence_error_90_change"
                    if metric == "high_confidence_error_90_rate"
                    else f"{metric}_change"
                )
                output[f"{scope}_{change_name}"] = (
                    float(output[f"{scope}_quadratic_{metric}"])
                    - float(output[f"{scope}_binary_{metric}"])
                )
        rows.append(output)
    return rows


def export(run: pathlib.Path, output: pathlib.Path) -> dict[str, object]:
    primary_path = run / "evaluation" / "summary.json"
    supplement_path = run / "evaluation_ethics_seed1_supplement" / "summary.json"
    census_path = run / "gptoss_checkpoints.json"
    source_paths = (primary_path, supplement_path, census_path)
    summaries = [_read(primary_path), _read(supplement_path)]
    census = _read(census_path)
    rows = build_pair_rows(summaries, census)
    if len(rows) != 3:
        raise ValueError(f"expected three admitted GPT-OSS pairs, found {len(rows)}")

    pair_path = output / "gptoss_subject_transfer_pairs.csv"
    manifest_path = output / "gptoss_subject_transfer_manifest.json"
    _write_csv(pair_path, rows)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_family": "GPT-OSS 20B",
        "planned_training_pairs": int(census["planned_pairs"]),
        "admitted_training_pairs": len(rows),
        "failed_training_pairs": int(census["planned_pairs"]) - len(rows),
        "evaluation_domains": [*SUBJECTS, "gpqa"],
        "pair_rows": len(rows),
        "sources": {str(path.relative_to(ROOT)): _sha(path) for path in source_paths},
        "outputs": [str(pair_path.relative_to(ROOT))],
    }
    manifest_path.write_text(
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
