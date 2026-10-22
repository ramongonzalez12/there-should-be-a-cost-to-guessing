#!/usr/bin/env python3
"""The essay's public data step: graded rows -> tables -> figure CSVs -> key numbers.

    python scripts/essay_data_step.py            # rebuild data/essay/{tables,figures,key-numbers.json}
    python scripts/essay_data_step.py --check    # rebuild into a temp dir, diff against data/essay, exit 1 on any diff

No API key, no network, no run database: everything is read from
data/essay/graded/responses.csv.gz (one row per graded response, text-free),
data/essay/inputs/ (model metadata, the item skips, the frozen Part 3
summaries, and the code literals some charts draw), and the carried tables
named below.

Every statistic comes from the same analyzers the essay used
(scripts/analyze_notation_artifact.py, scripts/export_warning_comparison.py,
scripts/export_battery_thresholds.py), fed the same Row records the lab's
essay data step built from its frozen source (lab/essay_v628/adapt.py
write_overlay, as pointed at source v638-lunajson-228f0788 by the v6.38 and
v6.69 layers). The arm names are the analyzers' own:

    contract (graded rows)   analyzer arm      on the page
    confidence               control           the baseline prompt
    rule                     quad_score_only   "Explain the scoring rule"
    warning                  warning           "Warn about overconfidence"

Tables are REBUILT from the graded rows, or CARRIED: written by the lab from
inputs that are not in the graded rows (the training experiments of Part 3,
the gate design profiles, the model catalog). A carried table is copied
through unchanged and listed as "compared, not rebuilt" in --check and in
data/essay/manifest.json. Two rebuilt tables are partly carried:
notation_artifact_cells.csv and notation_artifact_summary.json hold rows and
blocks from earlier studies that are kept as they are, while every row and
block of this battery is recomputed.

Bootstrap intervals (warning_comparison_levels.csv, the rule contrast in
notation_artifact_summary.json) use the analyzers' fixed seeds and draw in
the graded rows' file order, so a rebuild reproduces them exactly. They are
the slow part: most of the run's seven minutes.

Lab-only: --from-lab seeds the carried tables from the v6.69 essay layer and
--compare-lab diffs the rebuilt tables and key numbers against it.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib
import io
import json
import math
import random
import re
import shutil
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "data/essay"
GRADED = DATA / "graded/responses.csv.gz"
BEHAVIOUR = DATA / "graded/behaviour"
INPUTS = DATA / "inputs"
# The lab's essay layer these files reproduce (absent from the public repository).
LAB_LAYER = ROOT / "lab/essay_v669/sources/v638-lunajson-228f0788/retrain"

ARM = {"confidence": "control", "rule": "quad_score_only", "warning": "warning"}
ITEMS_PER_MODEL = 800

# Tables rebuilt from the graded rows (file names under tables/).
REBUILT = (
    "battery_cohort.csv",
    "notation_artifact_cells.csv",          # partly carried: other studies' rows
    "notation_artifact_summary.json",       # partly carried: other studies' blocks
    "notation_rerun_models.csv",
    "notation_rerun_benchmarks.csv",
    "notation_rerun_cells.csv",
    "notation_rerun_reliability_bins.csv",
    "notation_rerun_reliability_bins_by_band.csv",
    "notation_rerun_reliability_bins_by_model.csv",
    "model_vintage_calibration.csv",
    "model_vintage_by_year.csv",
    "warning_comparison_levels.csv",
    "battery_confidence_thresholds.csv",
    "model_coverage_extension_candidates.csv",
    "model_assessment_history.csv",
)
# Tables carried unchanged: their inputs are not graded rows of this source.
CARRIED = (
    "battery_confidence_thresholds_manifest.json",
    "common_training_pooled_levels.csv",
    "common_training_reliability_bins.csv",
    "common_training_thresholds.csv",
    "common_training_trajectories.csv",
    "confidence_only_training_accuracy_cells.csv",
    "confidence_only_training_accuracy_scope_summary.csv",
    "confidence_only_training_manifest.json",
    "confidence_only_untouched_base_prompts.csv",
    "models_catalog.csv",
    "design/gate-model-distributions.json",
    "design/gate-observed-distributions.json",
    "design/v623-baseline-extension.json",
    "essay_cohort_manifest.json",
)
# Where each tables/ file sits in the lab layer's processed/ folder.
LAB_NAME = {"models_catalog.csv": "data/models_catalog.csv"}

# Half-year release periods (lab/essay_v629/vintage_halves.py): a year with a
# half under MIN_MODELS models is folded into one period.
MIN_MODELS = 3
PERIOD_FIELDS = ("bin_label", "bin_start", "bin_end")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def header(path: Path) -> list[str]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    """lab/essay_v628/adapt.py's writer: DictWriter, '\\n' line ends, floats as repr."""
    fields = fields or list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_graded(path: Path = GRADED) -> list[dict]:
    """The graded rows, in file order. Line 1 is the canary; the CSV starts on line 2."""
    text = gzip.decompress(path.read_bytes()).decode("utf-8")
    first, rest = text.split("\n", 1)
    if "canary GUID" not in first:
        raise SystemExit(f"{path}: line 1 is not the canary line")
    return list(csv.DictReader(io.StringIO(rest)))


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Cohorts and Row records
# --------------------------------------------------------------------------

def skips() -> list[dict]:
    return read_csv(INPUTS / "item-exclusions.csv")


def cohorts(graded: list[dict]) -> tuple[list[str], list[str], dict]:
    """B (complete in the confidence contract) and P (complete in confidence,
    rule and warning), by the audited analysis's rule (lab/essay_refresh/
    analyze.py completed()): every scheduled item returned, none awaiting
    interpretation or grade, after the model's item skips leave its schedule.

    Returns (B, P, counts) where counts[(model, contract)] holds the returned,
    pending and grade-pending numbers the cohort table's reasons quote.
    """
    k_model = Counter(s["model"] for s in skips())
    counts: dict = defaultdict(Counter)
    for r in graded:
        key = (r["model"], r["contract"])
        counts[key]["returned_all"] += 1
        counts[key]["interpretation_pending_all"] += r["pending"] == "1"
        counts[key]["grade_pending_all"] += r["grade_status"] == "PENDING"
        if r["excluded_from_analysis"] == "1":
            continue
        counts[key]["returned"] += 1
        counts[key]["interpretation_pending"] += r["pending"] == "1"
        counts[key]["grade_pending"] += r["grade_status"] == "PENDING"
    for (model, _contract), c in counts.items():
        c["scheduled"] = ITEMS_PER_MODEL - k_model[model]
        c["missing"] = c["scheduled"] - c["returned"]

    def complete(model, contract):
        c = counts.get((model, contract))
        return bool(c) and c["missing"] == 0 and c["grade_pending"] == 0 and c["interpretation_pending"] == 0

    models = sorted({r["model"] for r in graded})
    baseline = [m for m in models if complete(m, "confidence")]
    paired = [m for m in baseline if complete(m, "rule") and complete(m, "warning")]
    return baseline, paired, counts


def row_records(ana, graded: list[dict], baseline: list[str], paired: list[str]) -> dict:
    """Graded rows -> the analyzer's Row records, per (model, analyzer arm).

    The mapping is lab/essay_v628/adapt.py load_rows, applied to the graded
    rows' own columns: attempted unless an explicit abstention; parse_failure
    and verdict as the graded rows define them (Rule 1: a format failure is
    INCORRECT); the confidence enters only when the response is usable.
    Only complete cohort cells enter: every confidence row of B, and the rule
    and warning rows of P, less the item skips.
    """
    rows: dict = defaultdict(list)
    for r in graded:
        arm = ARM.get(r["contract"])
        if arm is None:
            continue  # the answer-only `standard` contract is not an essay input
        model = r["model"]
        if model not in (baseline if arm == "control" else paired):
            continue
        if r["excluded_from_analysis"] == "1":
            continue
        if r["pending"] == "1" or r["grade_status"] != "RESOLVED":
            raise SystemExit(f"open row in a complete cohort cell: {model} {r['item_id']} {r['contract']}")
        attempted = r["answer_status"] != "explicit_abstention"
        parse_failure = r["parse_failure"] == "1"
        usable = r["answer_status"] == "explicit_answer" and not parse_failure
        conf = float(r["confidence"]) if usable else None
        rows[model, arm].append(ana.Row(
            group="rerun", model=model, benchmark=r["benchmark"], arm=arm, item_id=r["item_id"],
            attempted=attempted, correct=r["verdict"] == "CORRECT", parse_failure=parse_failure,
            stored_conf=conf, corrected_conf=conf, notation="none", integer_zero=False,
            idk_letter=False, source=SOURCE_TAG))
    k_model = Counter(s["model"] for s in skips())
    for (model, arm), own in rows.items():
        if len(own) != ITEMS_PER_MODEL - k_model[model] or len({r.benchmark for r in own}) != 8:
            raise SystemExit(f"incomplete cohort cell: {model} {arm} has {len(own)} rows")
    expected = {(m, "control") for m in baseline} | {(m, a) for m in paired for a in ("quad_score_only", "warning")}
    if set(rows) != expected:
        raise SystemExit("cohort cells do not match B and P")
    return rows


def source_info() -> dict:
    return json.loads((INPUTS / "source.json").read_text())


# Tags every Row with its snapshot, as the lab's step did ('luna-assisted:<8 hex>').
SOURCE_TAG = "luna-assisted:" + json.loads((INPUTS / "source.json").read_text())["snapshot_id"][:8] \
    if (INPUTS / "source.json").exists() else "luna-assisted:?"


def freeze_stamp() -> str:
    """'2026-10-08 23:20 UTC' (lab/essay_v628/essay_source.py freeze_stamp)."""
    import datetime as dt
    t = dt.datetime.fromisoformat(source_info()["freeze_cutoff_utc"]).astimezone(dt.timezone.utc)
    return f"{t:%Y-%m-%d %H:%M} UTC"


def freeze_day() -> str:
    """'October 8' (essay_source.py freeze_day)."""
    import datetime as dt
    t = dt.datetime.fromisoformat(source_info()["freeze_cutoff_utc"]).astimezone(dt.timezone.utc)
    return f"{t:%B} {t.day}"


# --------------------------------------------------------------------------
# Half-year periods (lab/essay_v629/vintage_halves.py)
# --------------------------------------------------------------------------

def half_of(date: str) -> str:
    """'2025-04-14' -> '2025H1'; '2025-07-01' -> '2025H2'."""
    return f"{date[:4]}H{1 if int(date[5:7]) <= 6 else 2}"


def period_codes(dates: list[str]) -> list[str]:
    """One period per date; a year with a half under MIN_MODELS models is one period."""
    halves = Counter(half_of(d) for d in dates)
    folded = {h[:4] for h, n in halves.items() if n < MIN_MODELS}
    return [d[:4] if d[:4] in folded else half_of(d) for d in dates]


def period_label(code: str) -> str:
    """'2024', '1H 2025', '2H 2026'."""
    return code if len(code) == 4 else f"{code[5]}H {code[:4]}"


def period_bounds(code: str) -> tuple[str, str]:
    half = None if len(code) == 4 else int(code[5])
    start = {None: "01-01", 1: "01-01", 2: "07-01"}[half]
    end = {None: "12-31", 1: "06-30", 2: "12-31"}[half]
    return f"{code[:4]}-{start}", f"{code[:4]}-{end}"


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

def build_tables(out: Path, base: Path, verbose: bool = True) -> dict:
    """Write every table into out/ (the tables/ folder). `base` holds the
    carried tables and the earlier-study rows of the partly carried ones."""
    ana = importlib.import_module("analyze_notation_artifact")
    warn = importlib.import_module("export_warning_comparison")
    thr = importlib.import_module("export_battery_thresholds")
    out.mkdir(parents=True, exist_ok=True)
    ana.PROCESSED = out
    src = source_info()

    for name in CARRIED:
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / name, out / name)

    graded = load_graded()
    baseline, paired, counts = cohorts(graded)
    by_key = row_records(ana, graded, baseline, paired)
    all_rows = [r for own in by_key.values() for r in own]
    rerun = [r for r in all_rows if r.arm in ("control", "quad_score_only")]
    models = {m["model"]: m for m in read_csv(INPUTS / "models.csv")}

    # 1. The cohort registry: B, with in_p for P. The October run's request
    # settings come from the graded rows (one output limit and one reasoning
    # setting per model); the statuses and reasons state the freeze's counts.
    settings = defaultdict(set)
    for r in graded:
        if r["contract"] == "confidence":
            settings[r["model"]].add((r["max_tokens"], r["reasoning"]))
    registry = []
    for model in baseline:
        if len(settings[model]) != 1:
            raise SystemExit(f"{model}: more than one request setting in the confidence contract")
        (max_tokens, reasoning), = settings[model]
        row = {"model": model, "cohort": models[model]["registry_cohort"], "listed_date": models[model]["listed_date"],
               "max_tokens": max_tokens, "reasoning": reasoning}
        reasons = []
        for short, contract in (("control", "confidence"), ("rule", "rule"), ("warning", "warning")):
            complete = (model, ARM[contract]) in by_key
            row[f"{short}_status"] = "admitted" if complete else "incomplete"
            row[f"{short}_rows"] = str(len(by_key[model, ARM[contract]])) if complete else "0"
            if not complete:
                c = counts[model, contract]
                reasons.append(f"{short}: {c['missing']} missing, {c['grade_pending']} awaiting grade, "
                               f"{c['interpretation_pending']} awaiting interpretation at the {freeze_stamp()} freeze")
        row["in_p"] = "1" if model in paired else "0"
        row["reason"] = " | ".join(reasons)
        registry.append(row)
    write_csv(out / "battery_cohort.csv", registry)

    # 2. Per-cell artifact table: the earlier studies' rows carried, this
    # battery's ("rerun") rows recomputed.
    old_cells = [r for r in read_csv(base / "notation_artifact_cells.csv") if r["study"] != "rerun"]
    fields = header(base / "notation_artifact_cells.csv")
    cells = defaultdict(list)
    for r in rerun:
        cells[r.model, r.benchmark, r.arm].append(r)
    new_cells = []
    for (model, bench, arm), own in sorted(cells.items()):
        rec = {"study": "rerun", "model": model, "benchmark": bench, "arm": arm}
        for which in ("as_parsed", "corrected"):
            for k, v in ana.cell_metrics(own, which).items():
                rec[f"{which}_{k}"] = v
        rec.update(fraction_notation_responses=0, integer_zero_responses=0, idk_letter_responses=0)
        new_cells.append(rec)
    write_csv(out / "notation_artifact_cells.csv", old_cells + new_cells, fields)

    # 3. Summary JSON: the analyzer's own rerun blocks; earlier studies kept.
    summary = json.loads((base / "notation_artifact_summary.json").read_text())
    for key in [k for k in summary["arms"] if k.startswith("rerun")]:
        del summary["arms"][key]
    for block in ("artifact_census", "idk_letter", "per_model_gap"):
        for key in [k for k in summary[block] if k.startswith("rerun")]:
            del summary[block][key]
    by_arm = defaultdict(list)
    for r in rerun:
        by_arm[r.arm].append(r)
    for arm, own in sorted(by_arm.items()):
        key = f"rerun:{arm}"
        summary["arms"][key] = {w: ana.equal_cell_summary(own, w) for w in ("as_parsed", "corrected")}
        summary["artifact_census"][key] = {}
        summary["idk_letter"][key] = 0
        summary["per_model_gap"][key] = {m: {w: ana.equal_cell_summary([r for r in own if r.model == m], w)["confidence_gap"]
                                             for w in ("as_parsed", "corrected")} for m in sorted({r.model for r in own})}
    rr = [r for r in rerun if r.model in set(paired)]
    ctl = ana.equal_cell_summary([r for r in rr if r.arm == "control"], "corrected")
    trt = ana.equal_cell_summary([r for r in rr if r.arm == "quad_score_only"], "corrected")
    summary["arms"]["rerun_paired:control"] = {w: ana.equal_cell_summary([r for r in rr if r.arm == "control"], w)
                                               for w in ("as_parsed", "corrected")}
    summary["rerun_design"] = {
        "models_control_complete": len(baseline), "models_both_arms_complete": len(paired),
        "control_models": baseline, "paired_models": paired, "benchmarks": 8, "items_per_benchmark": 100,
        "cohort_registry": "data/processed/battery_cohort.csv", "p_models": paired}
    summary["rerun_corrected_contrast"] = {
        "confidence_change": trt["confidence"] - ctl["confidence"],
        "accuracy_change": trt["accuracy"] - ctl["accuracy"],
        "signed_gap_change": trt["confidence_gap"] - ctl["confidence_gap"],
        "absolute_gap_change": trt["mean_absolute_confidence_gap"] - ctl["mean_absolute_confidence_gap"],
        "score_change": trt["calibrated_score"] - ctl["calibrated_score"]}
    if verbose:
        print("bootstrap: rule versus confidence, 2,000 paired cluster draws ...", flush=True)
    summary["rerun_corrected_contrast_bootstrap"] = ana.cluster_bootstrap(
        rr, "control", "quad_score_only", draws=ana.BOOTSTRAP_DRAWS, seed=ana.BOOTSTRAP_SEED)
    ana.emit_rerun_rollups(rerun, summary)
    (out / "notation_artifact_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    # The pooled reliability file: a response-weighted sum of the per-model bins.
    groups = defaultdict(list)
    for row in read_csv(out / "notation_rerun_reliability_bins_by_model.csv"):
        groups[row["arm"], row["confidence_bin"]].append(row)
    pooled = []
    for (arm, band), own in sorted(groups.items()):
        n = sum(int(r["responses"]) for r in own)
        pooled.append({"arm": arm, "confidence_bin": band, "responses": n,
                       **{k: math.fsum(int(r["responses"]) * float(r[k]) for r in own) / n
                          for k in ("mean_stated_confidence", "accuracy")}})
    write_csv(out / "notation_rerun_reliability_bins.csv", pooled)

    # 4. Vintage table: one row per baseline model (the analyzer's per-model
    # equal-cell summaries for the baseline and rule prompts), listed_year
    # as the release period; then the period averages.
    vintage_fields = header(base / "model_vintage_calibration.csv")
    codes = dict(zip(baseline, period_codes([models[m]["listed_date"] for m in baseline])))
    vintage = []
    for model in baseline:
        rec = {"model": model, "listed_date": models[model]["listed_date"], "listed_year": codes[model],
               "cohort": models[model]["registry_cohort"],
               "arms": "control+quad_score_only" if model in paired else "control", "reps": 1,
               "control_complete": 1, "treatment_complete": int(model in paired),
               "control_responses": len(by_key[model, "control"]),
               "treatment_responses": len(by_key[model, "quad_score_only"]) if model in paired else 0}
        for arm, prefix in (("control", "control"), ("quad_score_only", "treatment")):
            own = by_key.get((model, arm), [])
            for which, suffix in (("corrected", ""), ("as_parsed", "_as_parsed")):
                s = ana.equal_cell_summary(own, which)
                for metric in ("accuracy", "confidence", "confidence_gap", "overall_accuracy", "calibrated_score",
                               "brier_loss", "high_confidence_error_90_rate", "usable_confidence_rate",
                               "answer_rate", "confidence_when_wrong", "errors_at_90_share"):
                    rec[f"{prefix}_{metric}{suffix}"] = s[metric]
        vintage.append({k: rec[k] for k in vintage_fields})
    write_csv(out / "model_vintage_calibration.csv", vintage, vintage_fields)
    year_fields = header(base / "model_vintage_by_year.csv")
    years = []
    for code in sorted({r["listed_year"] for r in vintage}):
        own = [r for r in vintage if r["listed_year"] == code]
        row = {"listed_year": code, "models": len(own)}
        for field in year_fields[2:]:
            if field in PERIOD_FIELDS:
                continue
            if field.startswith(("min_", "max_")):
                op = min if field.startswith("min_") else max
                row[field] = op(float(r[field[4:]]) for r in own)
            else:
                row[field] = statistics.mean(float(r[field]) for r in own)
        row["bin_label"] = period_label(code)
        row["bin_start"], row["bin_end"] = period_bounds(code)
        years.append(row)
    write_csv(out / "model_vintage_by_year.csv", years, year_fields)

    # 5. Warning comparison on P: the exporter's own cell metrics, scopes,
    # draws and seed. One collection produced all three prompts, so the
    # same-run and battery-control comparisons are one; both labels carry it.
    def as_dicts(own):
        cells_ = defaultdict(list)
        for r in own:
            ok = r.attempted and not r.parse_failure and r.corrected_conf is not None
            cells_[r.model, r.benchmark].append({"item": r.item_id, "attempted": r.attempted, "pf": r.parse_failure,
                                                 "correct": r.correct, "conf": r.corrected_conf, "usable": ok,
                                                 "db": SOURCE_TAG})
        return cells_
    control = as_dicts([r for r in all_rows if r.arm == "control" and r.model in set(paired)])
    warning = as_dicts([r for r in all_rows if r.arm == "warning"])
    keys = sorted(warning)
    if sorted(control) != keys or len(keys) != len(paired) * 8:
        raise SystemExit("warning comparison cells do not pair")
    bands = defaultdict(list)
    for row in read_csv(out / "notation_rerun_benchmarks.csv"):
        bands[warn.band_of(float(row["control_accuracy"]))].append(row["benchmark"])
    scopes = {"all": keys}
    for band, benches in bands.items():
        scopes[f"band:{band}"] = [k for k in keys if k[1] in benches]
    for model in sorted({m for m, _ in keys}):
        scopes[f"model:{model}"] = [k for k in keys if k[0] == model]
    for bench in sorted({b for _, b in keys}):
        scopes[f"benchmark:{bench}"] = [k for k in keys if k[1] == bench]
    rng = random.Random(warn.SEED)
    levels = []
    if verbose:
        print("bootstrap: warning versus confidence, all scopes ...", flush=True)
    for scope, sel in scopes.items():
        draws = warn.DRAWS if scope == "all" or scope.startswith("band") else 500
        lv = warn.scoped_levels(control, warning, sel, rng, draws)
        for k in warn.METRICS:
            v = lv[k]
            levels.append({"scope": scope, "cells": len(sel), "metric": k,
                           "baseline": v["baseline"], "baseline_ci_low": v["baseline_ci"][0],
                           "baseline_ci_high": v["baseline_ci"][1], "warning": v["warning"],
                           "warning_ci_low": v["warning_ci"][0], "warning_ci_high": v["warning_ci"][1],
                           "change": v["change"], "change_ci_low": v["change_ci"][0],
                           "change_ci_high": v["change_ci"][1], "bootstrap_draws": draws})
    write_csv(out / "warning_comparison_levels.csv",
              [{"control": label, **row} for label in ("aug26_integrated", "aug27_rerun") for row in levels])

    # 6. Per-model confidence thresholds on B (export_battery_thresholds' rule).
    output = []
    for model in baseline:
        rows_ = by_key[model, "control"]
        for threshold in thr.THRESHOLDS:
            accepted = [r for r in rows_ if ana.usable(r, r.corrected_conf) and r.corrected_conf >= threshold]
            correct = sum(r.correct for r in accepted)
            wrong = len(accepted) - correct
            output.append({"model": model, "threshold": threshold, "questions": len(rows_),
                           "accepted": len(accepted), "correct": correct, "wrong": wrong,
                           "coverage": len(accepted) / len(rows_),
                           "wrong_among_accepted": wrong / len(accepted) if accepted else "",
                           "wrong_per_question": wrong / len(rows_)})
    write_csv(out / "battery_confidence_thresholds.csv", output)

    # 8. The models not included: every model in the source without a complete
    # baseline, its reason stated from the freeze's own counts.
    incomplete = []
    for model in sorted({r["model"] for r in graded} - set(baseline)):
        c = counts[model, "confidence"]
        parts = [f"{c['returned_all']} of {ITEMS_PER_MODEL} baseline responses returned"]
        if c["grade_pending_all"] or c["interpretation_pending_all"]:
            parts.append(f"{max(c['grade_pending_all'], c['interpretation_pending_all'])} awaiting review")
        incomplete.append({"model": model, "status": "incomplete", "source": f"{src['lab_path']}/metrics.json",
                           "reason": f"Incomplete at the {freeze_day()} freeze: " + ", ".join(parts) + ".",
                           "program_cost_usd": "", "retained_request_rows_all_attempts": c["returned_all"],
                           "other_arms_run_in_this_expansion": ""})
    write_csv(out / "model_coverage_extension_candidates.csv", incomplete,
              header(base / "model_coverage_extension_candidates.csv"))
    write_csv(out / "model_assessment_history.csv", [], header(base / "model_assessment_history.csv"))

    return {"baseline": baseline, "paired": paired, "rows": len(graded)}


# --------------------------------------------------------------------------
# Lab-only: seed and compare against the essay layer
# --------------------------------------------------------------------------

def lab_path(name: str) -> Path:
    return LAB_LAYER / "processed" / LAB_NAME.get(name, name)


def seed_from_lab(dest: Path) -> None:
    """Copy the lab layer's tables into dest/ under their tables/ names (carried
    files, and the earlier-study rows the partly carried tables keep)."""
    for name in CARRIED + REBUILT:
        src = lab_path(name)
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / name)


def lab_battery_cohort_view(path: Path) -> list[dict]:
    """The lab's cohort table with the changes this release makes: the three
    lab-path columns dropped, and the earlier battery's request settings
    (max_tokens, reasoning) left out of the comparison."""
    rows = read_csv(path)
    return [{k: v for k, v in r.items() if not k.endswith("_db") and k not in ("max_tokens", "reasoning")}
            for r in rows]


def compare_tables(built: Path) -> dict:
    """Rebuilt and carried tables against the lab layer: identical bytes, or
    for battery_cohort.csv identical apart from the documented column changes."""
    out = {}
    for name in REBUILT + CARRIED:
        mine, lab = built / name, lab_path(name)
        if name == "battery_cohort.csv":
            a = [{k: v for k, v in r.items() if k not in ("max_tokens", "reasoning")} for r in read_csv(mine)]
            same = a == lab_battery_cohort_view(lab)
        else:
            same = mine.read_bytes() == lab.read_bytes()
        out[name] = "identical" if same else "DIFFERS"
    return out


# --------------------------------------------------------------------------
# Figure CSVs: exactly the rows each exhibit draws
# --------------------------------------------------------------------------
# One file per exhibit, named by its figure id; columns named as the chart's
# axes and series; no comment lines. Percentages and points are on the page's
# 0-100 scale, rounded to four decimals: enough that rounding a value again to
# the page's whole number or one decimal gives what the page prints. The
# Summary's copy of [1.B] links the [1.B] file.

DEC = 4
# Float sums use math.fsum (exactly rounded): Python 3.12's built-in sum()
# compensates rounding error and 3.10's does not, so a plain sum() gives
# last-digit differences between the two and the committed bytes would
# depend on the interpreter.


def r2(x) -> float:
    """A value already on the page's scale, four decimals."""
    return round(float(x), DEC) + 0.0


def pct(x) -> float:
    """A 0-1 share on the page's 0-100 scale, four decimals."""
    return round(float(x) * 100, DEC) + 0.0


def figure_inputs() -> dict:
    return json.loads((INPUTS / "figure-inputs.json").read_text())


def frozen_input(name: str) -> dict:
    """A frozen Part 3 input by file name (inputs/figure-inputs.json)."""
    doc = figure_inputs()["frozen_inputs"]
    hits = [v["data"] for k, v in doc.items() if k.endswith("/" + name)]
    if len(hits) != 1:
        raise SystemExit(f"frozen input {name}: {len(hits)} matches")
    return hits[0]


def literal(name: str):
    return figure_inputs()["code_literals"][name]


def model_meta() -> dict:
    return {m["model"]: m for m in read_csv(INPUTS / "models.csv")}


def half_up(x: float) -> int:
    """The essay's rounding for printed integers (lab/essay_v660/feedback.py)."""
    return math.floor(x + 0.5)


def fig_scissors(T: Path) -> list[dict]:
    """[1.B]: one row per benchmark, easiest (highest accuracy) first."""
    names = literal("benchmark_names")["names"]
    rows = sorted(read_csv(T / "notation_rerun_benchmarks.csv"), key=lambda r: -float(r["control_accuracy"]))
    return [{"order_easiest_to_hardest": i, "benchmark": names[r["benchmark"]], "benchmark_key": r["benchmark"],
             "accuracy_pct": pct(r["control_accuracy"]), "stated_confidence_pct": pct(r["control_confidence"]),
             "overconfidence_gap_pts": pct(r["control_confidence_gap"])}
            for i, r in enumerate(rows, 1)]


def confidence_split(T: Path) -> dict:
    """Mean confidence on right and on wrong answers: the equal-cell means of the
    control cells' exact conditional means (the essay generator's
    confidence_by_correctness): wrong = confidence_when_wrong; right recovered
    from E[c] = P(right) E[c|right] + P(wrong) E[c|wrong]."""
    rights, wrongs = [], []
    for row in read_csv(T / "notation_rerun_cells.csv"):
        if row["arm"] != "control":
            continue
        acc, conf, wrong = (float(row[k]) for k in ("accuracy", "confidence", "confidence_when_wrong"))
        right = conf if acc == 1 else (conf - (1 - acc) * wrong) / acc if acc > 0 else math.nan
        for value, pooled in ((right, rights), (wrong, wrongs)):
            if math.isfinite(value):
                pooled.append(value * 100)
    return {"mean_right": math.fsum(rights) / len(rights), "mean_wrong": math.fsum(wrongs) / len(wrongs)}


def control_summary(T: Path, key: str = "rerun:control") -> dict:
    return json.loads((T / "notation_artifact_summary.json").read_text())["arms"][key]["corrected"]


def fig_confsplit(T: Path) -> list[dict]:
    """[1.C]: average confidence on right and wrong answers; and per 100
    questions, right, wrong under 90%, and wrong at 90% or higher."""
    cs = confidence_split(T)
    ctl = control_summary(T)
    right = ctl["overall_accuracy"] * 100
    tail = ctl["high_confidence_error_90_rate"] * 100
    return [
        {"panel": "Average confidence (%)", "category": "Right answers", "value": r2(cs["mean_right"])},
        {"panel": "Average confidence (%)", "category": "Wrong answers", "value": r2(cs["mean_wrong"])},
        {"panel": "Per 100 questions", "category": "right", "value": r2(right)},
        {"panel": "Per 100 questions", "category": "wrong, under 90%", "value": r2(100 - right - tail)},
        {"panel": "Per 100 questions", "category": "wrong at 90%+", "value": r2(tail)},
    ]


def vintage_rows(T: Path) -> list[dict]:
    return read_csv(T / "model_vintage_calibration.csv")


def fig_every_model(T: Path) -> list[dict]:
    """[1.D]: one point per model (accuracy across, stated confidence up)."""
    meta = model_meta()
    labels = {r["listed_year"]: r["bin_label"] for r in read_csv(T / "model_vintage_by_year.csv")}
    return [{"model": r["model"], "model_name": meta[r["model"]]["display_name"],
             "developer": meta[r["model"]]["developer"], "listed_date": r["listed_date"],
             "period": labels[r["listed_year"]], "accuracy_pct": pct(r["control_accuracy"]),
             "stated_confidence_pct": pct(r["control_confidence"]),
             "overconfidence_gap_pts": pct(r["control_confidence_gap"])}
            for r in vintage_rows(T)]


def fig_behaviour(T: Path) -> list[dict]:
    """[1.E]: the period averages the steps draw, then every model point."""
    out = [{"row": "period average", "label": r["bin_label"], "period": r["bin_label"], "models": int(r["models"]),
            "accuracy_pct": pct(r["control_accuracy"]), "stated_confidence_pct": pct(r["control_confidence"]),
            "overconfidence_gap_pts": pct(r["control_confidence_gap"])}
           for r in read_csv(T / "model_vintage_by_year.csv")]
    for m in fig_every_model(T):
        out.append({"row": "model", "label": m["model_name"], "period": m["period"], "models": 1,
                    "accuracy_pct": m["accuracy_pct"], "stated_confidence_pct": m["stated_confidence_pct"],
                    "overconfidence_gap_pts": m["overconfidence_gap_pts"]})
    return out


def fig_vintage(T: Path) -> list[dict]:
    """[1.F]: each developer's models by listing date, with the open-weight flag."""
    meta = model_meta()
    rows = sorted(vintage_rows(T), key=lambda r: (meta[r["model"]]["developer"], r["listed_date"], r["model"]))
    return [{"developer": meta[r["model"]]["developer"], "model": r["model"],
             "model_name": meta[r["model"]]["display_name"], "listed_date": r["listed_date"],
             "open_weight": {"1": "yes", "0": "no"}.get(meta[r["model"]]["open_weight"], ""),
             "stated_confidence_pct": pct(r["control_confidence"]), "accuracy_pct": pct(r["control_accuracy"]),
             "overconfidence_gap_pts": pct(r["control_confidence_gap"])}
            for r in rows]


def fig_students(T: Path) -> list[dict]:
    """[2.A]: the two hypothetical students the chart draws (code literals)."""
    return [{"student": s["student"], "right_of_100": s["right_of_100"], "wrong_of_100": 100 - s["right_of_100"],
             "confidence_on_right_pct": half_up(s["confidence_on_right"] * 100),
             "confidence_on_wrong_pct": half_up(s["confidence_on_wrong"] * 100)}
            for s in literal("students_2A")["rows"]]


def quad(p: float, correct: bool) -> float:
    """The essay's honest confidence score (src/belowzero/rules.py quadratic)."""
    from belowzero.rules import quadratic
    return quadratic(p, correct)


def fig_score_build(T: Path) -> list[dict]:
    """[2.B]: points on one question against reported confidence, computed from
    the formula in the caption (cost −c², reward 2c if right), on the chart's
    grid of 101 reports."""
    out = []
    for i in range(101):
        c = i / 100
        out.append({"confidence_pct": i, "cost": r4(-c * c), "reward_if_right": r4(2 * c),
                    "score_if_right": r4(quad(c, True)), "score_if_wrong": r4(quad(c, False))})
    return out


def r4(x) -> float:
    return round(float(x), 4) + 0.0


def fig_payoff_curve(T: Path) -> list[dict]:
    """[2.C]: expected points per question against the reported confidence, for
    the caption's belief, computed from the formula on the chart's 101-report grid."""
    belief = literal("payoff_2C")["belief"]
    return [{"belief_pct": half_up(belief * 100), "confidence_reported_pct": i,
             "expected_points": r4(belief * quad(i / 100, True) + (1 - belief) * quad(i / 100, False))}
            for i in range(101)]


def tbl_ev_true(T: Path) -> list[dict]:
    """The calculation fold under [2.C]: points per question at each report, by outcome."""
    lit = literal("payoff_2C")
    belief, reports = lit["belief"], lit["reports"]
    cols = {f"report_{half_up(c * 100)}pct": c for c in reports}
    rows = [{"outcome": "Right", "chance_pct": half_up(belief * 100), **{k: r4(quad(c, True)) for k, c in cols.items()}},
            {"outcome": "Wrong", "chance_pct": half_up((1 - belief) * 100), **{k: r4(quad(c, False)) for k, c in cols.items()}},
            {"outcome": "Expected points", "chance_pct": "",
             **{k: r4(belief * quad(c, True) + (1 - belief) * quad(c, False)) for k, c in cols.items()}}]
    return rows


def models_by_score(T: Path) -> list[dict]:
    return sorted(read_csv(T / "notation_rerun_models.csv"), key=lambda r: -float(r["control_calibrated_score"]))


def fig_spread(T: Path) -> list[dict]:
    """[2.D]: every model's adjusted accuracy, accuracy, and stated confidence, highest adjusted accuracy first."""
    meta = model_meta()
    return [{"rank": i, "model": r["model"], "model_name": meta[r["model"]]["display_name"],
             "adjusted_accuracy_pts": pct(r["control_calibrated_score"]), "accuracy_pct": pct(r["control_accuracy"]),
             "stated_confidence_pct": pct(r["control_confidence"])}
            for i, r in enumerate(models_by_score(T), 1)]


def tbl_model_by_model(T: Path) -> list[dict]:
    """The model-by-model table: gap, wrong at 90%+ per 100, accuracy over all questions, adjusted accuracy."""
    meta = model_meta()
    return [{"model": r["model"], "model_name": meta[r["model"]]["display_name"],
             "overconfidence_gap_pts": pct(r["control_confidence_gap"]),
             "wrong_at_90_plus_per_100": pct(r["control_high_confidence_error_90_rate"]),
             "accuracy_all_questions_pct": pct(r["control_overall_accuracy"]),
             "adjusted_accuracy_pts": pct(r["control_calibrated_score"])}
            for r in models_by_score(T)]


def tbl_measures(T: Path) -> list[dict]:
    """The measures card: all models (equal-cell means) and each model."""
    ctl = control_summary(T)
    n = len(vintage_rows(T))
    out = [{"model": "", "model_name": f"All {n} models", "overconfidence_gap_pts": pct(ctl["confidence_gap"]),
            "wrong_at_90_plus_per_100": pct(ctl["high_confidence_error_90_rate"]),
            "accuracy_pct": pct(ctl["overall_accuracy"]), "adjusted_accuracy_pts": pct(ctl["calibrated_score"])}]
    meta = model_meta()
    for r in vintage_rows(T):
        out.append({"model": r["model"], "model_name": meta[r["model"]]["display_name"],
                    "overconfidence_gap_pts": pct(r["control_confidence_gap"]),
                    "wrong_at_90_plus_per_100": pct(r["control_high_confidence_error_90_rate"]),
                    "accuracy_pct": pct(r["control_overall_accuracy"]),
                    "adjusted_accuracy_pts": pct(r["control_calibrated_score"])})
    return out


def fig_prompt_moves(T: Path) -> list[dict]:
    """[3.A]: each paired model's overconfidence gap at baseline, explaining the
    scoring rule, and with the overconfidence warning, and the two changes."""
    meta = model_meta()
    labels = {r["listed_year"]: r["bin_label"] for r in read_csv(T / "model_vintage_by_year.csv")}
    vint = {r["model"]: r for r in vintage_rows(T)}
    warn = {r["scope"][len("model:"):]: r for r in read_csv(T / "warning_comparison_levels.csv")
            if r["control"] == "aug26_integrated" and r["scope"].startswith("model:") and r["metric"] == "gap"}
    out = []
    for r in sorted(read_csv(T / "notation_rerun_models.csv"), key=lambda r: -float(r["control_accuracy"])):
        if r["model"] not in warn:
            continue
        base, rule, w = (float(r["control_confidence_gap"]) * 100, float(r["treatment_confidence_gap"]) * 100,
                         float(warn[r["model"]]["warning"]) * 100)
        acc = float(r["control_accuracy"]) * 100
        out.append({"model": r["model"], "model_name": meta[r["model"]]["display_name"],
                    "panel": "Models above 85% accuracy" if acc > 85 else "Models at or below 85% accuracy",
                    "accuracy_at_baseline_pct": r2(acc), "period": labels[vint[r["model"]]["listed_year"]],
                    "gap_baseline_pts": r2(base), "gap_explaining_scoring_pts": r2(rule), "gap_warning_pts": r2(w),
                    "change_explaining_scoring_pts": r2(rule - base), "change_warning_pts": r2(w - base)})
    return out


# The thresholds the gate exhibit's selector offers (0 is the ungated baseline).
GATE_THRESHOLDS = (0, 0.8, 0.9, 0.95, 1)


def fig_model_thresholds(T: Path) -> list[dict]:
    """The confidence-threshold exhibit: for each model, and for all models with
    equal weights, the share of questions with an allowed answer and the wrong
    answers among those allowed, ungated and at each threshold."""
    meta = model_meta()
    rows = [r for r in read_csv(T / "battery_confidence_thresholds.csv") if float(r["threshold"]) in GATE_THRESHOLDS]
    models = sorted({r["model"] for r in rows})
    out = []
    for t in GATE_THRESHOLDS:
        own = [r for r in rows if float(r["threshold"]) == t]
        coverage = math.fsum(int(r["accepted"]) / int(r["questions"]) for r in own) / len(own)
        wrong = math.fsum(int(r["wrong"]) / int(r["questions"]) for r in own) / len(own)
        out.append({"model": "", "model_name": f"All {len(models)} models", "threshold_pct": half_up(t * 100),
                    "questions_with_allowed_answer_pct": r2(100 * coverage),
                    "wrong_per_100_questions": r2(100 * wrong),
                    "wrong_among_allowed_pct": r2(100 * wrong / coverage)})
    for m in models:
        for r in sorted((r for r in rows if r["model"] == m), key=lambda r: float(r["threshold"])):
            q, acc_, wr = int(r["questions"]), int(r["accepted"]), int(r["wrong"])
            out.append({"model": m, "model_name": meta[m]["display_name"], "threshold_pct": half_up(float(r["threshold"]) * 100),
                        "questions_with_allowed_answer_pct": r2(100 * acc_ / q),
                        "wrong_per_100_questions": r2(100 * wr / q),
                        "wrong_among_allowed_pct": r2(100 * wr / acc_) if acc_ else ""})
    return out


# Why a model was left out (inputs/figure-inputs.json, roster_exclusion_reasons):
# each sentence opens with the label of its recorded cause, as the essay's
# roster prints it.
EXCLUSION_CAUSES = {
    "usability_gate": "Usability check",
    "provider_failure": "Provider failure on its OpenRouter route",
    "unfinished": "Unfinished at the freeze",
}


def exclusion_reason(reason: dict, returned: int, scheduled: int) -> str:
    """One left-out model's sentence, e.g. 'Usability check: too few usable
    GPQA answers in the first 50 (400 of 800 responses by the October 8
    freeze).' Fails unless it opens with its cause's label, and unless any
    count it quotes is the model's own and names the freeze day."""
    if reason["cause"] not in EXCLUSION_CAUSES or not reason["text"].startswith(EXCLUSION_CAUSES[reason["cause"]] + ": "):
        raise SystemExit(f"unknown exclusion cause, or a sentence without its label: {reason}")
    quoted = re.search(r"\((\d+) of (\d+) responses by the (\w+ \d+) freeze\)", reason["text"])
    if quoted and (int(quoted[1]), int(quoted[2]), quoted[3]) != (returned, scheduled, freeze_day()):
        raise SystemExit(f"exclusion cause quotes another count or day: {reason} vs {returned} of {scheduled}")
    return reason["text"]


def tbl_developers(T: Path) -> list[dict]:
    """The roster by developer: the models in the comparison and the models
    left out, with why. Since v6.70 (item X3, P04) the roster prints no
    per-model accuracy or confidence; those stay in tables/model_vintage_calibration.csv.
    Each left-out model's reason is the roster's sentence for it (v6.71 item
    35003), checked against its recorded cause and its count."""
    meta = model_meta()
    causes = literal("roster_exclusion_reasons")["reasons"]
    k_model = Counter(s["model"] for s in skips())
    out = []
    for r in sorted(vintage_rows(T), key=lambda r: (meta[r["model"]]["developer"], r["listed_date"], r["model"])):
        out.append({"developer": meta[r["model"]]["developer"], "model": r["model"],
                    "model_name": meta[r["model"]]["display_name"], "status": "included",
                    "listed_date": r["listed_date"],
                    "baseline_responses_returned": int(r["control_responses"]),
                    "baseline_responses_scheduled": ITEMS_PER_MODEL - k_model[r["model"]],
                    "why_not_included": ""})
    cand = {r["model"]: r for r in read_csv(T / "model_coverage_extension_candidates.csv")}
    if set(cand) != set(causes):
        raise SystemExit(f"left-out models without a recorded cause: {sorted(set(cand) ^ set(causes))}")
    for m in sorted(cand, key=lambda m: (meta[m]["developer"], meta[m]["listed_date"], m)):
        returned = int(cand[m]["retained_request_rows_all_attempts"])
        out.append({"developer": meta[m]["developer"], "model": m, "model_name": meta[m]["display_name"],
                    "status": "not included", "listed_date": meta[m]["listed_date"],
                    "baseline_responses_returned": returned,
                    "baseline_responses_scheduled": ITEMS_PER_MODEL,
                    "why_not_included": exclusion_reason(causes[m], returned, ITEMS_PER_MODEL)})
    return out


def tbl_parity(T: Path) -> list[dict]:
    """The GPQA parity check: published accuracy against ours, with the range
    expected from one 198-question run (rows that passed)."""
    rows = [r for r in read_csv(ROOT / "data/processed/gpqa_parity.csv") if r["status"].startswith("PASS")]
    return [{"model": r["model"], "model_and_published_setup": r["label"],
             "published_accuracy_pct": pct(r["published_score"]),
             "our_accuracy_pct": r2(100 * int(r["correct"]) / int(r["n"])),
             "questions": int(r["n"]), "expected_range_low_pct": pct(r["interval_low"]),
             "expected_range_high_pct": pct(r["interval_high"])}
            for r in rows]


def census_split() -> tuple[list[dict], list[dict]]:
    """The census benchmarks [1.A] compares (one checkable answer, no feedback to
    the model) and the 14 it leaves out (scripts/census_exclusions.py)."""
    from census_exclusions import left_out
    rows = read_csv(ROOT / "data/processed/census_by_benchmark.csv")
    left = left_out()
    return [r for r in rows if r["benchmark"] not in left], [r for r in rows if r["benchmark"] in left]


def tbl_census(T: Path) -> list[dict]:
    """[1.A]: the compared benchmarks as one row."""
    top, _ = census_split()
    n = sum(int(r["n_responses"]) for r in top)
    d = sum(int(r["n_decline_phrase"]) for r in top)
    return [{"benchmark_type": "Benchmarks with correct answers and no feedback to the model", "benchmarks": len(top),
             "responses": n, "uncertainty_or_decline_responses": d,
             "uncertainty_or_decline_pct": r2(100 * d / n), "blank_responses": sum(int(r["n_empty"]) for r in top)}]


def tbl_census_benchmarks(T: Path) -> list[dict]:
    """The census fold: each compared benchmark, highest decline rate first."""
    names = literal("census_benchmark_names")["names"]
    top, _ = census_split()
    top.sort(key=lambda r: -float(r["decline_rate"]))
    return [{"benchmark_key": r["benchmark"], "benchmark": names.get(r["benchmark"], r["benchmark"]),
             "responses": int(r["n_responses"]), "uncertainty_or_decline_responses": int(r["n_decline_phrase"]),
             "uncertainty_or_decline_pct": r2(100 * float(r["decline_rate"]))}
            for r in top]


# --------------------------------------------------------------------------
# Part 3: the training experiments (frozen summaries in inputs/figure-inputs.json)
# --------------------------------------------------------------------------
# The two models every Part 3 average covers, equal weight (lab/essay_v633/section.py SHARED).
SHARED = ("qwen", "nemotron")
ARM_LABEL = {"base": "Before training", "binary": "Accuracy-only training", "quadratic": "Honest-confidence training"}
SETUP_LABEL = {"direct": "Without reasoning", "reasoning": "With reasoning"}


def runs_per_model(setup: str) -> int:
    """Matched training runs per model in a setup (essay_runs.json, the two models)."""
    runs = [r for r in frozen_input("essay_runs.json") if r["family"] in SHARED and r["setup"] == setup]
    per = Counter(r["family"] for r in runs)
    if len(set(per.values())) != 1:
        raise SystemExit(f"unequal runs per model in {setup}: {dict(per)}")
    return per[SHARED[0]]


def two_model(setup: str, arm: str, key: str) -> float:
    E = frozen_input("essay_effort.json")[setup]["models"]
    return statistics.mean(E[f][arm][key] for f in SHARED)


def fig_training_summary(T: Path) -> list[dict]:
    """[3.B]: the two models' averages, without and with reasoning: effort,
    accuracy, stated confidence, gap (essay_effort.json), and adjusted accuracy
    (essay_style_numbers.json: direct.* without reasoning, approaches.* with)."""
    S = frozen_input("essay_style_numbers.json")
    score_key = {"direct": {"base": "base", "binary": "binary", "quadratic": "quadratic"},
                 "reasoning": {"base": "base", "binary": "accuracy_only", "quadratic": "shared"}}
    out = []
    for setup in ("direct", "reasoning"):
        for arm in ("base", "binary", "quadratic"):
            block = S["direct"] if setup == "direct" else S["approaches"]
            out.append({"setup": SETUP_LABEL[setup], "runs_per_model": runs_per_model(setup), "arm": ARM_LABEL[arm],
                        "effort_tokens": r2(two_model(setup, arm, "length")),
                        "accuracy_pct": r2(two_model(setup, arm, "accuracy")),
                        "stated_confidence_pct": r2(two_model(setup, arm, "confidence")),
                        "overconfidence_gap_pts": r2(two_model(setup, arm, "gap0")),
                        "adjusted_accuracy_pts": r2(block[score_key[setup][arm]]["score"])})
    return out


def fig_noreason_bars(T: Path) -> list[dict]:
    """[3.C]: without reasoning, the same three arms: confidence, accuracy, gap, adjusted accuracy."""
    return [{k: v for k, v in r.items() if k not in ("setup", "runs_per_model", "effort_tokens")}
            for r in fig_training_summary(T) if r["setup"] == SETUP_LABEL["direct"]]


def fig_noreason_effort(T: Path) -> list[dict]:
    """[3.D]: each model trained with reasoning: effort, accuracy, confidence, gap by arm."""
    E = frozen_input("essay_effort.json")["reasoning"]["models"]
    names = {"qwen": "Qwen3 8B", "nemotron": "Nemotron 3 Nano 30B", "gpt_oss": "GPT-OSS 20B"}
    out = []
    for fam in ("qwen", "nemotron", "gpt_oss"):
        for arm in ("base", "binary", "quadratic"):
            v = E[fam][arm]
            out.append({"model": names[fam], "arm": ARM_LABEL[arm], "effort_tokens": r2(v["length"]),
                        "accuracy_pct": r2(v["accuracy"]), "stated_confidence_pct": r2(v["confidence"]),
                        "overconfidence_gap_pts": r2(v["gap0"])})
    return out


# The approaches [3.E] and [3.F] compare, trained with reasoning (training_ideas_results.json keys).
APPROACHES = (("honestsplit", "Score confidence separately"),
              ("groupsplit", "Score it against the other attempts"),
              ("tough", "Train on questions missed outright"),
              ("calibfirst", "Calibrate without reasoning first"))


def approach_confidence(key: str) -> float:
    """Stated confidence among answers for one approach: the two models' mean of
    each model's pooled runs (lab/essay_v633/section.py conf_of)."""
    rows = {r["family"]: r for r in frozen_input("training_ideas_results.json")[key]["rows"]}
    return statistics.mean(rows[f]["arm"]["conf_among"] for f in SHARED)


def fig_noreason_approaches(T: Path) -> list[dict]:
    """[3.E]: the baselines and the four approaches, trained with reasoning:
    effort (approach_effort.json), accuracy and gap (essay_style_numbers.json
    approaches), and stated confidence (essay_effort.json for the baselines,
    training_ideas_results.json for the approaches)."""
    S = frozen_input("essay_style_numbers.json")["approaches"]
    AE = frozen_input("approach_effort.json")
    rows = [("Baselines", "Before training", "base", AE["reference"]["base"], two_model("reasoning", "base", "confidence")),
            ("Baselines", "Accuracy-only training", "accuracy_only", AE["reference"]["binary"],
             two_model("reasoning", "binary", "confidence")),
            ("Baselines", "Honest-confidence training", "shared", AE["reference"]["quadratic"],
             two_model("reasoning", "quadratic", "confidence"))]
    for key, label in APPROACHES:
        group = "Trained without, then with reasoning" if key == "calibfirst" else "Variations with reasoning"
        rows.append((group, label, key, AE["approaches"][key]["length"], approach_confidence(key)))
    return [{"group": g, "approach": label, "effort_tokens": r2(effort), "accuracy_pct": r2(S[key]["accuracy"]),
             "stated_confidence_pct": r2(conf), "overconfidence_gap_pts": r2(S[key]["gap"])}
            for g, label, key, effort, conf in rows]


def fig_safer_pushback(T: Path, B: dict | None = None) -> list[dict]:
    """[3.F]: stated confidence and the share of pushback conversations in which
    the model gave in to a wrong answer (behaviour_summary_qn.json), by arm.
    ``B`` replaces the frozen summary (check_behaviour passes the one it rebuilt)."""
    B = B or frozen_input("behaviour_summary_qn.json")
    gave = lambda key: r2(100 * B[key]["wrong_adoption"]["mean"])
    out = [{"group": "Before training", "runs_per_model": "", "arm": "Before training",
            "stated_confidence_pct": r2(two_model("reasoning", "base", "confidence")),
            "gave_in_to_wrong_answer_pct": gave("base")}]
    for setup, prefix in (("direct", "noreason"), ("reasoning", "reasoning")):
        group = "Trained without reasoning" if setup == "direct" else "Trained with reasoning"
        for arm in ("binary", "quadratic"):
            out.append({"group": group, "runs_per_model": runs_per_model(setup), "arm": ARM_LABEL[arm],
                        "stated_confidence_pct": r2(two_model(setup, arm, "confidence")),
                        "gave_in_to_wrong_answer_pct": gave(f"{prefix} {arm}")})
    for key, label in APPROACHES:
        out.append({"group": "Trained with reasoning", "runs_per_model": runs_per_model("reasoning"), "arm": label,
                    "stated_confidence_pct": r2(approach_confidence(key)), "gave_in_to_wrong_answer_pct": gave(key)})
    return out


def fig_noreason_attempts(T: Path) -> list[dict]:
    """The four example training questions: each attempt's stated confidence,
    outcome, and honest score (essay scale), with the question's average."""
    groups = frozen_input("example_groups.json")
    # Panel heads as the essay prints them (inputs: attempt_panels, with the item that last changed them).
    titles = literal("attempt_panels")["titles"]
    panels = tuple(zip(titles, (groups["all_wrong"], frozen_input("example_group_2of8.json"),
                                groups["some_right"], groups["six_of_eight"]), strict=True))
    names = {"qwen": "Qwen3 8B", "nemotron": "Nemotron 3 Nano 30B"}
    out = []
    for title, g in panels:
        _idea, fam, _plan, step, item = g["source"]
        avg = statistics.mean(a["honest_score_x100"] for a in g["attempts"])
        for i, a in enumerate(g["attempts"], 1):
            out.append({"panel": title, "model": names[fam], "training_step": step, "item_id": item, "attempt": i,
                        "stated_confidence_pct": r2(100 * a["probability"]),
                        "outcome": "right" if a["outcome"] == "CORRECT" else "wrong",
                        "score_pts": r2(a["honest_score_x100"]), "question_average_pts": r2(avg)})
    return out


def fig_noreason_runs(T: Path) -> list[dict]:
    """The matched runs of the two models: share of early training questions
    missed on every attempt, and how much smaller the gap ended than the run's
    accuracy-only twin."""
    names = {"qwen": "Qwen3 8B", "nemotron": "Nemotron 3 Nano 30B"}
    return [{"model": names[r["family"]], "setup": SETUP_LABEL[r["setup"]], "seed": r["seed"],
             "missed_on_every_attempt_pct": r2(100 * r["always_wrong_early"]), "gap_reduction_pts": r2(r["gain"]),
             "gap_accuracy_only_pts": r2(r["gap_binary"]), "gap_honest_pts": r2(r["gap_quadratic"])}
            for r in frozen_input("essay_runs.json") if r["family"] in SHARED]


# Every exhibit with a download, in page order: figure id -> builder.
FIGURES = {
    "tbl-census": tbl_census,
    "tbl-census-benchmarks": tbl_census_benchmarks,
    "tbl-developers": tbl_developers,
    "tbl-parity": tbl_parity,
    "fig-scissors": fig_scissors,
    "fig-confsplit": fig_confsplit,
    "fig-every-model": fig_every_model,
    "fig-behaviour": fig_behaviour,
    "fig-vintage": fig_vintage,
    "fig-students": fig_students,
    "fig-score-build": fig_score_build,
    "fig-payoff-curve": fig_payoff_curve,
    "tbl-ev-true": tbl_ev_true,
    "fig-spread": fig_spread,
    "tbl-model-by-model": tbl_model_by_model,
    "tbl-measures": tbl_measures,
    "fig-prompt-moves": fig_prompt_moves,
    "fig-training-summary": fig_training_summary,
    "fig-noreason-bars": fig_noreason_bars,
    "fig-noreason-attempts": fig_noreason_attempts,
    "fig-noreason-runs": fig_noreason_runs,
    "fig-noreason-effort": fig_noreason_effort,
    "fig-noreason-approaches": fig_noreason_approaches,
    "fig-safer-pushback": fig_safer_pushback,
    "fig-model-thresholds": fig_model_thresholds,
}


def build_figures(tables: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for fid, fn in FIGURES.items():
        rows = fn(tables)
        write_csv(out / f"{fid}.csv", rows)
        counts[fid] = len(rows)
    return counts


# --------------------------------------------------------------------------
# Key numbers: the values the essay's sentences quote
# --------------------------------------------------------------------------

def confidence_audit(graded: list[dict]) -> dict:
    """Per baseline model: usable answers, those stated above 40%, wrong ones, and
    wrong ones above 40% (export_battery_thresholds' confidence audit)."""
    ana = importlib.import_module("analyze_notation_artifact")
    baseline, paired, _ = cohorts(graded)
    by_key = row_records(ana, graded, baseline, paired)
    audit = {}
    for model in baseline:
        accepted = [r for r in by_key[model, "control"] if ana.usable(r, r.corrected_conf) and r.corrected_conf >= 0]
        above = [r for r in accepted if r.corrected_conf > .4]
        audit[model] = {"usable": len(accepted), "above_40": len(above), "wrong": sum(not r.correct for r in accepted),
                        "wrong_above_40": sum(not r.correct for r in above)}
    return audit


def key_numbers(T: Path, audit: dict) -> dict:
    """The essay's key numbers (lab/essay_v628/build.py RENDER's selection of the
    essay generator's K, by the same definitions), on the 0-100 scale."""
    summary = json.loads((T / "notation_artifact_summary.json").read_text())
    arms = summary["arms"]
    ctl, rule, paired = (arms[k]["corrected"] for k in ("rerun:control", "rerun:quad_score_only", "rerun_paired:control"))
    head = summary["rerun_headline"]["corrected"]
    models = read_csv(T / "notation_rerun_models.csv")
    years = [{"year": y["listed_year"], "label": y["bin_label"], "models": int(y["models"]),
              **{k: float(y[k]) * 100 for k in ("control_answer_rate", "control_accuracy", "control_confidence",
                                                "control_confidence_gap", "control_high_confidence_error_90_rate")}}
             for y in read_csv(T / "model_vintage_by_year.csv")]
    warn = read_csv(T / "warning_comparison_levels.csv")

    def wlevel(control, scope, metric):
        row = next(r for r in warn if r["control"] == control and r["scope"] == scope and r["metric"] == metric)
        return {k: float(row[k]) * 100 for k in ("baseline", "warning", "change", "change_ci_low", "change_ci_high")}

    # Confidence on right and wrong answers, and the share of wrong answers in the top confidence bin.
    cs = confidence_split(T)
    bins = [r for r in read_csv(T / "notation_rerun_reliability_bins_by_model.csv") if r["arm"] == "control"]
    wrong_mass, wrong_total = defaultdict(float), 0.0
    for r in bins:
        n, acc = int(r["responses"]), float(r["accuracy"])
        wrong_mass[float(r["confidence_bin"])] += n * (1 - acc)
        wrong_total += n * (1 - acc)
    per_model_wrong = defaultdict(list)
    for row in read_csv(T / "notation_rerun_cells.csv"):
        if row["arm"] == "control" and math.isfinite(float(row["confidence_when_wrong"])):
            per_model_wrong[row["model"]].append(float(row["confidence_when_wrong"]) * 100)
    wrong_by_model = {m: math.fsum(v) / len(v) for m, v in per_model_wrong.items()}

    thr = read_csv(T / "battery_confidence_thresholds.csv")

    def gate(t):
        own = [r for r in thr if float(r["threshold"]) == t]
        coverage = math.fsum(int(r["accepted"]) / int(r["questions"]) for r in own) / len(own)
        wrong = math.fsum(int(r["wrong"]) / int(r["questions"]) for r in own) / len(own)
        return {"coverage": 100 * coverage, "risk": 100 * wrong / coverage, "models": len(own)}

    k = {"n_models": len(models), "n_paired": summary["rerun_design"]["models_both_arms_complete"],
         "conf_wrong": ctl["confidence_when_wrong"] * 100, "tail": ctl["high_confidence_error_90_rate"] * 100,
         "overall_acc": ctl["overall_accuracy"] * 100, "acc": ctl["accuracy"] * 100, "conf": ctl["confidence"] * 100,
         "gap": ctl["confidence_gap"] * 100, "cells": head["control_cells"], "cells_over": head["control_overconfident_cells"],
         "years": years,
         "warn_rerun": {m: wlevel("aug27_rerun", "all", m) for m in ("gap", "score", "tail", "confidence", "accuracy")},
         "rule_gap": rule["confidence_gap"] * 100, "rule_conf": rule["confidence"] * 100, "rule_acc": rule["accuracy"] * 100,
         "rule_overall_acc": rule["overall_accuracy"] * 100, "rule_score": rule["calibrated_score"] * 100,
         "rule_tail": rule["high_confidence_error_90_rate"] * 100,
         "paired_gap": paired["confidence_gap"] * 100, "paired_conf": paired["confidence"] * 100,
         "paired_acc": paired["accuracy"] * 100, "paired_overall_acc": paired["overall_accuracy"] * 100,
         "paired_score": paired["calibrated_score"] * 100, "paired_tail": paired["high_confidence_error_90_rate"] * 100,
         "score": ctl["calibrated_score"] * 100,
         "v6_years": {"acc_climb": years[-1]["control_accuracy"] - years[0]["control_accuracy"],
                      "conf_plateau": round(math.fsum(y["control_confidence"] for y in years[1:]) / len(years[1:]))},
         "cbc": {"mean_right": cs["mean_right"], "mean_wrong": cs["mean_wrong"],
                 "top_bin_share": wrong_mass[max(wrong_mass)] / wrong_total * 100,
                 "n_wrong_over_90": sum(1 for v in wrong_by_model.values() if v >= 90), "n_models": len(wrong_by_model)},
         "gate": {str(t): gate(t) for t in GATE_THRESHOLDS},
         "above40": 100 * math.fsum(r["above_40"] / r["usable"] for r in audit.values()) / len(audit),
         "wrong_above40": 100 * math.fsum(r["wrong_above_40"] / r["wrong"] for r in audit.values()) / len(audit)}
    return k


# --------------------------------------------------------------------------
# The two behavior benchmarks: graded records -> the essay's behavior numbers
# --------------------------------------------------------------------------
# graded/behaviour/ holds the shortcuts and pushback records (ids, model,
# condition, grades; no question text, scenario text, or model output). The
# essay's behavior levels (inputs: behaviour_summary_qn.json), [3.F], and the
# behavior section's pushback-by-confidence figures (pushback_by_confidence.json)
# are rebuilt from them and must match to 1e-9. docs/benchmarks/ quotes the
# counts below and the rates; this check binds both.

BEHAVIOUR_FAMILIES = {"Qwen3 8B": "qwen", "Nemotron 3 Nano": "nemotron"}
BEHAVIOUR_COUNTS = {"checkpoints": 54, "pushback_items": 150, "pushback_items_per_benchmark": 50,
                    "pushback_conversations": 11686, "wrong_arm_conversations": 8100,
                    "right_arm_conversations": 3586, "shortcut_scenarios": 64,
                    "shortcut_scenarios_unauthorized": 32, "shortcut_repetitions": 5,
                    "shortcut_records": 34560, "shortcut_tasks": 8}
HIGH_CONF, LOW_CONF = 0.95, 0.90


def load_behaviour(name: str) -> list[dict]:
    """A graded behavior file, in file order. Line 1 is the canary; the CSV starts on line 2."""
    with gzip.open(BEHAVIOUR / name, "rt", encoding="utf-8") as fh:
        if "canary GUID" not in fh.readline():
            raise SystemExit(f"{name}: line 1 is not the canary line")
        return list(csv.DictReader(fh))


def behaviour_summary(pushback: list[dict], shortcuts: list[dict]) -> dict:
    """Per checkpoint: wrong- and right-arm adoption over conversations formatted on
    both turns, and the shortcut rate over unauthorized scenarios' action records.
    Then per model the mean over its runs, the two models weighted equally, and
    seed_sd the mean of the two models' population SDs over runs."""
    per = defaultdict(lambda: defaultdict(dict))  # (condition, family) -> metric -> checkpoint -> rate
    groups = defaultdict(list)
    for r in pushback:
        groups[(r["condition"], BEHAVIOUR_FAMILIES[r["model"]], r["checkpoint"], r["arm"])].append(r)
    for (cond, fam, ck, arm), rows in groups.items():
        usable = [r for r in rows if r["first_formatted"] == "1" and r["second_formatted"] == "1"]
        if usable:
            per[(cond, fam)][f"{arm}_adoption"][ck] = (
                sum(r["second_answer"] == r["asserted_answer"] for r in usable) / len(usable))
    actions = defaultdict(list)
    for r in shortcuts:
        if r["stage"] == "action" and r["authorized"] == "0":
            actions[(r["condition"], BEHAVIOUR_FAMILIES[r["model"]], r["checkpoint"])].append(r)
    for (cond, fam, ck), rows in actions.items():
        per[(cond, fam)]["integrity_unauthorized_shortcut_rate"][ck] = (
            sum(r["took_shortcut"] == "1" for r in rows) / len(rows))
    out = {}
    for cond in sorted({c for c, _ in per}):
        out[cond] = {}
        for metric in ("integrity_unauthorized_shortcut_rate", "wrong_adoption", "right_adoption"):
            vals = {fam: list(per[(cond, fam)][metric].values()) for fam in ("qwen", "nemotron")}
            fam_mean = {fam: sum(v) / len(v) for fam, v in vals.items()}
            sd = (None if any(len(v) < 2 for v in vals.values())
                  else statistics.mean(statistics.pstdev(v) for v in vals.values()))
            out[cond][metric] = {"mean": (fam_mean["qwen"] + fam_mean["nemotron"]) / 2, **fam_mean,
                                 "n": {fam: len(v) for fam, v in vals.items()}, "seed_sd": sd}
    return out


def pushback_by_confidence(pushback: list[dict]) -> dict:
    """The behavior section's per-answer pushback figures, wrong arm, runs pooled per
    model, then the two models weighted equally (percents)."""
    out = {}
    for cond in sorted({r["condition"] for r in pushback}):
        per = {}
        for fam in ("qwen", "nemotron"):
            wrong = [r for r in pushback if r["condition"] == cond and r["arm"] == "wrong"
                     and BEHAVIOUR_FAMILIES[r["model"]] == fam]
            us = [r for r in wrong if r["first_formatted"] == "1" and r["second_formatted"] == "1"]
            gave = lambda r: r["second_answer"] == r["asserted_answer"]
            hi = [gave(r) for r in us if float(r["first_confidence"]) >= HIGH_CONF]
            lo = [gave(r) for r in us if float(r["first_confidence"]) <= LOW_CONF]
            right = [gave(r) for r in us if r["first_correct"] == "1"]
            missed = [gave(r) for r in us if r["first_correct"] != "1"]
            was_right = [r for r in wrong if r["first_correct"] == "1"]
            per[fam] = {"gave_high": 100 * sum(hi) / len(hi), "gave_low": 100 * sum(lo) / len(lo),
                        "share_low": 100 * len(lo) / len(us),
                        "gave_if_right": 100 * sum(right) / len(right),
                        "gave_if_wrong": 100 * sum(missed) / len(missed),
                        "lost_right": 100 * sum(r["second_correct"] != "1" for r in was_right) / len(was_right),
                        "n_high": len(hi), "n_low": len(lo), "n_usable": len(us)}
        pooled = {k: (per["qwen"][k] + per["nemotron"][k]) / 2 for k in per["qwen"] if not k.startswith("n_")}
        pooled["aim"] = pooled["gave_if_wrong"] - pooled["gave_if_right"]
        out[cond] = {"pooled": pooled, "by_model": per}
    return out


def _close(a, b, path: str, problems: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                problems.append(f"{path}.{k}: present on one side only")
            else:
                _close(a[k], b[k], f"{path}.{k}", problems)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        if abs(a - b) > 1e-9:
            problems.append(f"{path}: rebuilt {a!r}, essay {b!r}")
    elif a != b:
        problems.append(f"{path}: rebuilt {a!r}, essay {b!r}")


def check_behaviour(T: Path = DATA / "tables") -> list[str]:
    """Rebuild the behavior numbers from graded/behaviour/ and compare them with the
    essay's inputs and the [3.F] figure CSV. Returns the problems (empty when all match)."""
    pushback, shortcuts = load_behaviour("pushback.csv.gz"), load_behaviour("shortcuts.csv.gz")
    problems: list[str] = []
    counts = {
        "checkpoints": len({r["checkpoint"] for r in pushback} | {r["checkpoint"] for r in shortcuts}),
        "pushback_items": len({r["item_id"] for r in pushback}),
        "pushback_items_per_benchmark": max(Counter(i.split(":")[0] for i in {r["item_id"] for r in pushback}).values()),
        "pushback_conversations": len(pushback),
        "wrong_arm_conversations": sum(r["arm"] == "wrong" for r in pushback),
        "right_arm_conversations": sum(r["arm"] == "right" for r in pushback),
        "shortcut_scenarios": len({r["scenario_id"] for r in shortcuts}),
        "shortcut_scenarios_unauthorized": len({r["scenario_id"] for r in shortcuts if r["authorized"] == "0"}),
        "shortcut_repetitions": len({r["repetition"] for r in shortcuts}),
        "shortcut_records": len(shortcuts),
        "shortcut_tasks": len({r["scenario_id"].split(":")[1] for r in shortcuts}),
    }
    _close(counts, BEHAVIOUR_COUNTS, "counts", problems)
    summary = behaviour_summary(pushback, shortcuts)
    frozen = frozen_input("behaviour_summary_qn.json")
    metrics = ("integrity_unauthorized_shortcut_rate", "wrong_adoption", "right_adoption")
    _close(summary, {c: {m: frozen[c][m] for m in metrics} for c in frozen}, "behaviour_summary_qn", problems)
    _close(pushback_by_confidence(pushback), frozen_input("pushback_by_confidence.json"),
           "pushback_by_confidence", problems)
    # [3.F]: the committed CSV's pushback column equals the one built from the rebuilt summary.
    built = fig_safer_pushback(T, {c: {**frozen[c], **summary[c]} for c in frozen})
    shipped = read_csv(DATA / "figures/fig-safer-pushback.csv")
    if len(built) != len(shipped):
        problems.append("fig-safer-pushback.csv: row count")
    for b, s in zip(built, shipped):
        if (b["arm"], b["group"]) != (s["arm"], s["group"]) or \
                abs(float(s["gave_in_to_wrong_answer_pct"]) - b["gave_in_to_wrong_answer_pct"]) > 1e-9:
            problems.append(f"fig-safer-pushback.csv: {s['group']} / {s['arm']}")
    return problems


def report_behaviour() -> int:
    problems = check_behaviour()
    print("behavior benchmarks (graded/behaviour/): " + ("rebuilt; matches the essay's inputs and [3.F]"
                                                          if not problems else "MISMATCH"))
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


# --------------------------------------------------------------------------
# The whole step, the manifest, and --check
# --------------------------------------------------------------------------

def run(out: Path, base: Path, verbose: bool = True) -> dict:
    """graded rows -> out/tables -> out/figures -> out/key-numbers.json -> out/manifest.json"""
    build_tables(out / "tables", base, verbose=verbose)
    return finish(out)


def finish(out: Path) -> dict:
    """out/tables -> out/figures, out/key-numbers.json, and out/manifest.json."""
    graded = load_graded()
    baseline, paired, _ = cohorts(graded)
    audit = confidence_audit(graded)
    counts = build_figures(out / "tables", out / "figures")
    (out / "key-numbers.json").write_text(json.dumps(key_numbers(out / "tables", audit), indent=1) + "\n")
    files = {}
    produced = [p for sub in ("tables", "figures") for p in (out / sub).rglob("*") if p.is_file()]
    for path in sorted(produced + [out / "key-numbers.json"]):
        rel = path.relative_to(out).as_posix()
        name = rel.split("/", 1)[1] if rel.startswith("tables/") else None
        status = ("rebuilt" if name in REBUILT else "carried (compared, not rebuilt)" if name in CARRIED
                  else "rebuilt")
        files[rel] = {"sha256": sha(path), "status": status}
    manifest = {"source_id": source_info()["source_id"], "graded_rows_sha256": sha(GRADED),
                "baseline_models": len(baseline), "paired_models": len(paired),
                "figure_rows": counts, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def diff_trees(built: Path, committed: Path) -> list[str]:
    diffs = []
    for path in sorted(p for p in built.rglob("*") if p.is_file()):
        rel = path.relative_to(built)
        other = committed / rel
        if not other.is_file() or other.read_bytes() != path.read_bytes():
            diffs.append(str(rel))
    for path in sorted(p for p in committed.rglob("*") if p.is_file()):
        rel = path.relative_to(committed)
        if rel.parts[0] in ("tables", "figures") and not (built / rel).is_file():
            diffs.append(f"{rel} (not produced by the step)")
    return diffs


def compare_lab_key_numbers(path: Path) -> dict:
    """Each key number against the lab's v6.69 key-numbers.json (exact, to 1e-9)."""
    lab = json.loads((LAB_LAYER / "key-numbers.json").read_text())
    mine = json.loads(path.read_text())

    def same(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(same(a[x], b[x]) for x in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(a - b) < 1e-9
        return a == b
    return {k: ("identical" if k in lab and same(mine[k], lab[k]) else "DIFFERS") for k in mine} | \
        {k: "MISSING" for k in lab if k not in mine}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="rebuild into a temp dir and diff against data/essay")
    parser.add_argument("--from-lab", action="store_true", help="(lab) seed the carried tables from the v6.69 layer")
    parser.add_argument("--compare-lab", action="store_true", help="(lab) also compare tables and key numbers with v6.69")
    parser.add_argument("--behaviour", action="store_true",
                        help="only rebuild the behavior numbers from graded/behaviour/ and compare (seconds)")
    parser.add_argument("--from-tables", action="store_true",
                        help="rebuild only the figures, key numbers, and manifest from the committed tables (seconds)")
    args = parser.parse_args(argv)
    if args.behaviour:
        return report_behaviour()
    if args.from_tables:
        finish(DATA)
        print("figures, key numbers, and manifest rebuilt from data/essay/tables")
        return 0
    if args.from_lab and not LAB_LAYER.is_dir():
        raise SystemExit("--from-lab needs the lab tree")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base = DATA / "tables"
        if args.from_lab:
            base = tmp / "lab-base"
            seed_from_lab(base)
        out = tmp / "out" if args.check else DATA
        if not args.check and args.from_lab:
            out = tmp / "out"
        manifest = run(out, base)
        rebuilt = sum(1 for f in manifest["files"].values() if f["status"] == "rebuilt")
        carried = [k for k, f in manifest["files"].items() if f["status"] != "rebuilt"]
        print(f"{rebuilt} files rebuilt from the graded rows; {len(carried)} carried (compared, not rebuilt):")
        for name in carried:
            print(f"  {name}")
        status = 0
        if args.compare_lab:
            tables = compare_tables(out / "tables")
            keys = compare_lab_key_numbers(out / "key-numbers.json")
            print("lab tables:", json.dumps(tables, indent=1))
            print("lab key numbers:", json.dumps(keys, indent=1))
            if any(v != "identical" for v in list(tables.values()) + list(keys.values())):
                status = 1
        if args.check:
            diffs = diff_trees(out, DATA)
            print("diffs against data/essay:", diffs or "none")
            status = status or (1 if diffs else 0)
            status = report_behaviour() or status
        elif args.from_lab:
            for sub in ("tables", "figures"):
                if (DATA / sub).exists():
                    shutil.rmtree(DATA / sub)
                shutil.copytree(out / sub, DATA / sub)
            for name in ("key-numbers.json", "manifest.json"):
                shutil.copyfile(out / name, DATA / name)
    return status


if __name__ == "__main__":
    sys.exit(main())
