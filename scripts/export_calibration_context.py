"""Export reliability bins and before/after levels from preserved responses.

The brief needs more than change scores.  This exporter returns to the saved
response-level records and preserves two kinds of context:

* reliability bins, which compare stated confidence with observed accuracy;
* family-by-subject levels before and after confidence-focused training.

No model calls occur here.  The outputs are deterministic summaries of the
prompting databases and the two completed open-weight training families.

Usage::

    python scripts/export_calibration_context.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
SLICES = ROOT / "data" / "slices"
PROCESSED = ROOT / "data" / "processed"
SITE_DATA = ROOT / "site" / "below-zero" / "data"
PROMPT_META = PROCESSED / "prompt_estimation_run.json"

RELIABILITY_OUT = PROCESSED / "calibration_reliability_bins.csv"
TRAINING_LEVELS_OUT = PROCESSED / "pooled_training_levels.csv"
MANIFEST_OUT = PROCESSED / "calibration_context_manifest.json"
PUBLISHED_RELIABILITY_OUT = SITE_DATA / RELIABILITY_OUT.name
PUBLISHED_TRAINING_LEVELS_OUT = SITE_DATA / TRAINING_LEVELS_OUT.name

# The reliability bins and the confidence-tail table describe the two original
# families; the essay names that cohort and its counts (1,631 untuned answers)
# in prose. Later families enter the level tables and the programme-wide
# synthesis, not this pooled cohort, and the manifest counts below are for
# the cohort so a caption can never quote a three-family denominator under a
# two-family chart.
RELIABILITY_COHORT = {"Qwen3 8B", "GPT-OSS 20B"}

TRAINING_SOURCES = {
    "Qwen3 8B": (
        RUNS / "finetune" / "multitask_family_agentic_v1"
        / "qwen_evaluation" / "responses.jsonl"
    ),
    "GPT-OSS 20B": (
        RUNS / "finetune" / "openweight_family_v2"
        / "gpt_oss_evaluation" / "responses.jsonl"
    ),
    # Third family (2026-09-03 protocol): three matched pairs branched from a
    # syntax-only warm-up, evaluated on the same four batteries. Skipped, not
    # fabricated, while its evaluation is absent so the export still runs.
    "Nemotron 3 Nano 30B": (
        RUNS / "finetune" / "third_family_v1"
        / "nemotron_evaluation" / "responses.jsonl"
    ),
}

# The second training programme (2026-09-12): three families x five seed
# pairs under one recipe, evaluated on the same four batteries by the
# domain-transfer evaluation. Same display keys as above, so every
# downstream reader that derives families from the file sees 5/5/5 with no
# change; selected with --programme second, which leaves the reliability
# bins (a first-programme, two-family cohort the essay names in prose)
# untouched.
SECOND_PROGRAMME = RUNS / "finetune" / "second_programme_v1"
SECOND_TRAINING_SOURCES = {
    "Qwen3 8B": SECOND_PROGRAMME / "qwen" / "eval_final_batteries" / "responses.jsonl",
    "GPT-OSS 20B": SECOND_PROGRAMME / "gpt_oss" / "eval_final_batteries" / "responses.jsonl",
    "Nemotron 3 Nano 30B": SECOND_PROGRAMME / "nemotron" / "eval_final_batteries" / "responses.jsonl",
}
SECOND_MANIFEST_OUT = PROCESSED / "calibration_context_second_programme_manifest.json"

RELIABILITY_FIELDS = (
    "experiment", "cohort", "arm", "bin_lower", "bin_upper", "n",
    "mean_confidence", "accuracy", "signed_gap",
)
TRAINING_LEVEL_FIELDS = (
    "model_family", "evaluation_domain", "training_objective",
    "matched_seed_pairs", "n_responses", "mean_accuracy",
    "mean_accuracy_among_answers",
    "mean_confidence_among_answers", "mean_high_confidence_wrong_rate",
    "mean_high_confidence_error_90_rate",
    "mean_confidence_calibrated_score",
)


def _sha256(path: Path) -> str:
    """Hash each immutable source so the derived chart can be reproduced."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def calibration_bins(records: list[dict]) -> list[dict]:
    """Group binary outcomes into fixed ten-percentage-point confidence bins.

    Empty bins remain in the output.  The chart can therefore keep a stable
    0%-to-100% axis while distinguishing "no observations" from zero accuracy.
    """
    grouped: dict[tuple[str, str, str], list[list[dict]]] = {}
    for record in records:
        key = (record["experiment"], record["cohort"], record["arm"])
        bins = grouped.setdefault(key, [[] for _ in range(10)])
        probability = float(record["probability"])
        bins[min(int(probability * 10), 9)].append(record)

    exported = []
    for (experiment, cohort, arm), bins in sorted(grouped.items()):
        for index, members in enumerate(bins):
            if members:
                mean_confidence = statistics.mean(
                    float(record["probability"]) for record in members
                )
                accuracy = statistics.mean(
                    bool(record["correct"]) for record in members
                )
                signed_gap = mean_confidence - accuracy
            else:
                mean_confidence = accuracy = signed_gap = ""
            exported.append({
                "experiment": experiment,
                "cohort": cohort,
                "arm": arm,
                "bin_lower": index / 10,
                "bin_upper": (index + 1) / 10,
                "n": len(members),
                "mean_confidence": mean_confidence,
                "accuracy": accuracy,
                "signed_gap": signed_gap,
            })
    return exported


def summarize_training_levels(records: list[dict],
                              baseline: list[dict] = ()) -> list[dict]:
    """Average matched seed-level outcomes within each family and subject.

    Each training seed receives equal weight.  The binary and quadratic rows
    are restricted to the same seed identities before aggregation, so the
    displayed before/after levels preserve the paired experimental design.

    ``baseline`` holds the untuned evaluations (training_objective "base",
    one per family, on the same four batteries). They are exported as
    ``untuned`` rows with ``matched_seed_pairs`` 0 so the final-endpoint
    exhibits can print the level both reward arms started from beside the
    accuracy-only control, instead of leaving the reader to infer how much of
    each contrast is the control drifting. They are a descriptive level, not a
    seed-matched arm, and the essay labels them that way.
    """
    by_cell: dict[tuple[str, str, str, int], list[dict]] = defaultdict(list)
    for record in list(records) + [
            {**r, "training_objective": "untuned", "training_seed": 0}
            for r in baseline]:
        key = (
            record["model_family"], record["evaluation_domain"],
            record["training_objective"], int(record["training_seed"]),
        )
        by_cell[key].append(record)

    metrics = {}
    for key, members in by_cell.items():
        attempted = [
            record for record in members
            if record["outcome"] in {"CORRECT", "INCORRECT"}
            and record.get("probability") is not None
        ]
        n = len(members)
        metrics[key] = {
            "n": n,
            # Two accuracies, because the overconfidence gap must subtract the
            # accuracy of the SAME responses whose confidence is averaged.
            # `accuracy` is over every scheduled response (abstentions and
            # malformed output count as wrong); `accuracy_among_answers` is
            # over the attempted responses with a probability, the set the
            # confidence mean is taken on. Subtracting the first from the
            # confidence inflated the published gap by the abstention rate,
            # most in the confidence-trained arm (Qwen +14.9 published vs
            # +12.3 co-denominated).
            "accuracy": sum(r["outcome"] == "CORRECT" for r in members) / n,
            "accuracy_among_answers": (
                sum(r["outcome"] == "CORRECT" for r in attempted) / len(attempted)
                if attempted else float("nan")
            ),
            "confidence": statistics.mean(
                float(r["probability"]) for r in attempted
            ),
            "high_confidence_wrong": sum(
                r["outcome"] == "INCORRECT"
                and float(r["probability"]) >= 0.8
                for r in attempted
            ) / n,
            "high_confidence_error_90": sum(
                r["outcome"] == "INCORRECT"
                and float(r["probability"]) >= 0.9
                for r in attempted
            ) / n,
            "score": statistics.mean(
                float(r["scores"]["quadratic"]) for r in members
            ),
        }

    families_domains = sorted({(key[0], key[1]) for key in metrics})
    exported = []
    for family, domain in families_domains:
        seeds = {
            objective: {
                key[3] for key in metrics
                if key[:3] == (family, domain, objective)
            }
            for objective in ("binary", "quadratic")
        }
        matched = sorted(seeds["binary"] & seeds["quadratic"])
        if not matched:
            continue
        objectives = [("binary", matched), ("quadratic", matched)]
        if (family, domain, "untuned", 0) in metrics:
            objectives.append(("untuned", [0]))
        for objective, seed_ids in objectives:
            cells = [metrics[(family, domain, objective, seed)] for seed in seed_ids]
            exported.append({
                "model_family": family,
                "evaluation_domain": domain,
                "training_objective": objective,
                "matched_seed_pairs": len(matched) if objective != "untuned" else 0,
                "n_responses": sum(cell["n"] for cell in cells),
                "mean_accuracy": statistics.mean(
                    cell["accuracy"] for cell in cells
                ),
                "mean_accuracy_among_answers": statistics.mean(
                    cell["accuracy_among_answers"] for cell in cells
                ),
                "mean_confidence_among_answers": statistics.mean(
                    cell["confidence"] for cell in cells
                ),
                "mean_high_confidence_wrong_rate": statistics.mean(
                    cell["high_confidence_wrong"] for cell in cells
                ),
                "mean_high_confidence_error_90_rate": statistics.mean(
                    cell["high_confidence_error_90"] for cell in cells
                ),
                "mean_confidence_calibrated_score": statistics.mean(
                    cell["score"] for cell in cells
                ),
            })
    return exported


def _prompt_records() -> tuple[list[dict], list[Path], int]:
    """Load the two primary prompt arms on their committed frozen slices."""
    records = []
    sources = []
    total_primary_responses = 0
    metadata = json.loads(PROMPT_META.read_text())
    benchmarks = tuple(metadata["benchmarks"])
    for cohort in metadata["models"]:
        path = RUNS / cohort["database"]
        sources.append(path)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in benchmarks)
        selected = connection.execute(
            f"SELECT benchmark, item_id, contract, confidence, verdict "
            f"FROM answers WHERE model=? AND benchmark IN ({placeholders}) "
            "AND contract IN ('control', 'quad_both')",
            (cohort["model"], *benchmarks),
        ).fetchall()
        connection.close()

        allowed: dict[str, set[str]] = {}
        for benchmark in benchmarks:
            slice_path = SLICES / f'{benchmark}_{cohort["n_per_condition"]}.json'
            if slice_path.exists():
                allowed[benchmark] = set(json.loads(slice_path.read_text()))
        selected = [
            row for row in selected
            if row["benchmark"] not in allowed
            or row["item_id"] in allowed[row["benchmark"]]
        ]
        expected = len(benchmarks) * 2 * int(cohort["n_per_condition"])
        if len(selected) != expected:
            raise ValueError(
                f'{cohort["model"]}: expected {expected} primary responses, '
                f"found {len(selected)}"
            )
        total_primary_responses += len(selected)
        for row in selected:
            if row["verdict"] not in {"CORRECT", "INCORRECT"}:
                continue
            if row["confidence"] is None:
                continue
            records.append({
                "experiment": "prompting",
                "cohort": "Five models",
                "arm": (
                    "answer_normally" if row["contract"] == "control"
                    else "rule_threshold"
                ),
                "probability": float(row["confidence"]),
                "correct": row["verdict"] == "CORRECT",
            })
    return records, sources, total_primary_responses


def _validate_training_battery_identity(
        baseline: list[dict], trained: list[dict]) -> None:
    """Prove that every plotted training cell uses the baseline's items.

    The untuned model is evaluated once per family, while each trained arm is
    evaluated once per admitted seed. Bubble size is normalized within each
    series, so duplicating the baseline for every seed would add no information
    and would inflate its denominator. This check instead requires each
    family-domain-objective-seed cell to use the exact untuned item set.
    """
    baseline_items: dict[tuple[str, str], set[str]] = defaultdict(set)
    baseline_counts: dict[tuple[str, str], int] = defaultdict(int)
    for record in baseline:
        key = (record["model_family"], record["evaluation_domain"])
        baseline_items[key].add(record["item_id"])
        baseline_counts[key] += 1

    trained_items: dict[tuple[str, str, str, int], set[str]] = defaultdict(set)
    trained_counts: dict[tuple[str, str, str, int], int] = defaultdict(int)
    for record in trained:
        key = (
            record["model_family"], record["evaluation_domain"],
            record["training_objective"], int(record["training_seed"]),
        )
        trained_items[key].add(record["item_id"])
        trained_counts[key] += 1

    for key, item_ids in baseline_items.items():
        if baseline_counts[key] != len(item_ids):
            raise ValueError(f"duplicate untuned evaluation item in {key}")
    for key, item_ids in trained_items.items():
        family_domain = key[:2]
        if family_domain not in baseline_items:
            raise ValueError(f"no untuned comparison for training cell {key}")
        if trained_counts[key] != len(item_ids):
            raise ValueError(f"duplicate trained evaluation item in {key}")
        if item_ids != baseline_items[family_domain]:
            raise ValueError(
                f"training cell {key} does not match its untuned battery"
            )


def _training_records(
        training_sources: dict | None = None,
        ) -> tuple[list[dict], list[dict], list[dict], list[Path]]:
    """Load the untuned batteries and the complete pooled training pairs."""
    raw = []
    baseline = []
    sources = []
    for family, path in (training_sources or TRAINING_SOURCES).items():
        if not path.exists():
            print(f"{family}: {path.relative_to(ROOT)} absent; family skipped")
            continue
        sources.append(path)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                record["model_family"] = family
                objective = record.get("training_objective")
                if objective == "base":
                    baseline.append(record)
                elif (record.get("training_domain") == "pooled"
                      and objective in {"binary", "quadratic"}):
                    raw.append(record)

    seeds: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for record in raw:
        seeds[(record["model_family"], record["evaluation_domain"],
               record["training_objective"])].add(int(record["training_seed"]))
    matched: dict[tuple[str, str], set[int]] = {}
    for family, domain in {(r["model_family"], r["evaluation_domain"]) for r in raw}:
        matched[(family, domain)] = (
            seeds[(family, domain, "binary")]
            & seeds[(family, domain, "quadratic")]
        )
    raw = [
        record for record in raw
        if int(record["training_seed"])
        in matched[(record["model_family"], record["evaluation_domain"])]
    ]
    _validate_training_battery_identity(baseline, raw)

    # The reliability bins and the confidence-tail table describe the two
    # original families; the essay names that cohort and its counts (1,631
    # untuned answers) in prose. Later families enter the level tables and
    # the programme-wide synthesis, not this pooled cohort.
    reliability = []
    for record in baseline + raw:
        if record["model_family"] not in RELIABILITY_COHORT:
            continue
        if record["outcome"] not in {"CORRECT", "INCORRECT"}:
            continue
        if record.get("probability") is None:
            continue
        objective = record["training_objective"]
        reliability.append({
            "experiment": "training",
            "cohort": "Qwen3 8B + GPT-OSS 20B",
            "arm": {
                "base": "untuned_baseline",
                "binary": "accuracy_trained",
                "quadratic": "confidence_trained",
            }[objective],
            "probability": float(record["probability"]),
            "correct": record["outcome"] == "CORRECT",
        })
    return raw, reliability, baseline, sources


def _write_csv(path: Path, fieldnames: tuple[str, ...], records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(records)


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Calibration context and pooled training levels.")
    parser.add_argument(
        "--programme", choices=("first", "second"), default="first",
        help="which training programme feeds the pooled training levels: "
             "'first' (default, the 2026-08/09 pooled runs; also writes the "
             "reliability bins) or 'second' (the 2026-09-12 three-family "
             "programme; writes the training levels and its own manifest only)")
    parser.add_argument(
        "--levels-out", type=Path, default=None,
        help="write the pooled training levels here instead of the default "
             "path (the site copy is written only for the default path)")
    args = parser.parse_args(argv)
    if args.programme == "second":
        (training_raw, _reliability_unused, training_baseline,
         training_sources) = _training_records(SECOND_TRAINING_SOURCES)
        if len(training_sources) < len(SECOND_TRAINING_SOURCES):
            # Never overwrite the published levels with a partial programme:
            # the essay's family loop would silently show fewer families.
            raise SystemExit("second programme: not every family has "
                             "eval_final_batteries/responses.jsonl yet; nothing written")
        training_levels = summarize_training_levels(training_raw, training_baseline)
        out = args.levels_out or TRAINING_LEVELS_OUT
        _write_csv(out, TRAINING_LEVEL_FIELDS, training_levels)
        if args.levels_out is None:
            _write_csv(PUBLISHED_TRAINING_LEVELS_OUT, TRAINING_LEVEL_FIELDS, training_levels)
        SECOND_MANIFEST_OUT.write_text(json.dumps({
            "programme": "second_programme_v1",
            "training_matched_responses": len(training_raw),
            "training_baseline_responses": len(training_baseline),
            "families": sorted({r["model_family"] for r in training_raw}),
            "sources": {str(p.relative_to(ROOT)): _sha256(p) for p in training_sources},
            "outputs": [str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out)],
        }, indent=2) + "\n")
        print(f"wrote {out}: {len(training_levels)} level rows (second programme)")
        return
    prompt, prompt_sources, prompt_total = _prompt_records()
    (training_raw, training_reliability, training_baseline,
     training_sources) = _training_records()
    reliability = calibration_bins(prompt + training_reliability)
    training_levels = summarize_training_levels(training_raw, training_baseline)
    if args.levels_out is not None:
        # A named output for the first programme's levels (the notes page
        # reads them once the second programme owns the default path).
        _write_csv(args.levels_out, TRAINING_LEVEL_FIELDS, training_levels)
        print(f"wrote {args.levels_out}: {len(training_levels)} level rows")
        return

    _write_csv(RELIABILITY_OUT, RELIABILITY_FIELDS, reliability)
    _write_csv(TRAINING_LEVELS_OUT, TRAINING_LEVEL_FIELDS, training_levels)
    _write_csv(PUBLISHED_RELIABILITY_OUT, RELIABILITY_FIELDS, reliability)
    _write_csv(
        PUBLISHED_TRAINING_LEVELS_OUT, TRAINING_LEVEL_FIELDS, training_levels
    )

    sources = prompt_sources + training_sources
    manifest = {
        "exported": "2026-08-24",
        "binning": "fixed deciles [0,.1), ... [.9,1.0]",
        "prompt_primary_responses": prompt_total,
        "prompt_usable_confidence_answers": len(prompt),
        "reliability_cohort": sorted(RELIABILITY_COHORT),
        "training_matched_responses": sum(
            r["model_family"] in RELIABILITY_COHORT for r in training_raw),
        "training_matched_responses_all_families": len(training_raw),
        "training_usable_confidence_answers": sum(
            row["arm"] != "untuned_baseline" for row in training_reliability
        ),
        "training_baseline_responses": sum(
            r["model_family"] in RELIABILITY_COHORT for r in training_baseline),
        "training_baseline_responses_all_families": len(training_baseline),
        "training_baseline_usable_confidence_answers": sum(
            row["arm"] == "untuned_baseline" for row in training_reliability
        ),
        "training_pairs": 9,
        "training_subjects": 4,
        "sources": {
            str(path.relative_to(ROOT)): _sha256(path) for path in sources
        },
        "outputs": [
            str(RELIABILITY_OUT.relative_to(ROOT)),
            str(TRAINING_LEVELS_OUT.relative_to(ROOT)),
            str(PUBLISHED_RELIABILITY_OUT.relative_to(ROOT)),
            str(PUBLISHED_TRAINING_LEVELS_OUT.relative_to(ROOT)),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"wrote {RELIABILITY_OUT}: {len(reliability)} decile rows; "
        f"{len(prompt) + len(training_reliability):,} usable answers"
    )
    print(f"wrote {TRAINING_LEVELS_OUT}: {len(training_levels)} level rows")


if __name__ == "__main__":
    main()
