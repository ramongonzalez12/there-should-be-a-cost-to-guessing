#!/usr/bin/env python3
"""Quantify and correct the probability-notation artifact.

Protocol: notes/2026-08-27-notation-artifact-rerun-protocol.md (frozen before
the paid re-run). The runtime parser divides every probability token by 100,
so a model that writes ``PROBABILITY: 0.85`` (fraction notation, against the
requested integer format) is stored at 0.0085. This script re-reads the RAW
responses and applies the frozen correction rule in analysis only:

  - token contains a decimal point and its value is <= 1.0  ->  a fraction,
    taken at face value (0.85 -> 0.85)
  - any other token is a percent (85 -> 0.85; 0 -> 0.0; 87.5 -> 0.875)

The runtime parser itself stays frozen: generation and scoring are separated
by design, so re-scoring stored raws is free and non-destructive.

Also counted, per protocol: genuine integer-zero probabilities, and responses
whose parsed answer is the appended I DON'T KNOW option letter (currently
graded as an ordinary attempt; reported here, deliberately not regraded).

Analyzes every relevant response-level DB present on disk:
  runs/notation_rerun_20260827.db          control + quad_score_only (fresh)
  runs/prompt_arm_ident_main_off_20260827.db   hedge_placebo + quad_worked_example
  runs/prompt_arm_ident_main_low_20260827.db   (same, low-reasoning cohort)
  runs/base_model_prompt_main_20260827.db  control + quad_score_only, 2 base models

Outputs (data/processed/):
  notation_artifact_cells.csv     per db-group x model x benchmark x arm,
                                  as-parsed AND corrected metrics side by side
  notation_artifact_summary.json  pooled equal-cell summaries both ways,
                                  artifact census, per-model gaps, IDK-letter
                                  counts, and corrected contrasts
  notation_artifact_manifest.json provenance

Corrected drop-in files for the essay's overconfidence exhibits (v3.2: the
correction is applied to the WHOLE study, not just the prompting section, so
these mirror the column names of the as-parsed prompt_only_calibration_*
files and the builder can switch source paths without reshaping):
  notation_rerun_models.csv                  per model, control_/treatment_
  notation_rerun_benchmarks.csv              per benchmark, control_/treatment_
  notation_rerun_cells.csv                   per model x benchmark x arm
  notation_rerun_reliability_bins.csv        corrected bins, both arms
  notation_rerun_reliability_bins_by_band.csv  the same bins split by
                                  difficulty band (band = benchmark grouping
                                  by corrected control accuracy, same
                                  thresholds as the essay's band_of)
  notation_artifact_reliability_bins.csv     corrected bins for every study
                                  and arm, used for like-for-like prompt-arm
                                  reliability comparisons
  notation_artifact_reliability_bins_by_band.csv  the same retained studies,
                                  split by the essay's three difficulty bands
  notation_artifact_reliability_bins_by_model.csv the same retained studies,
                                  split by model for interactive chart filters
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
sys.path.insert(0, str(ROOT / "src"))

from belowzero.cohort import load_cohort

# Group label -> (db paths, arms expected). Missing DBs are skipped loudly.
# These are the frozen paths. A later cohort that ran the same arms can be
# pooled into an existing group at the command line with --extra-db
# GROUP=PATH; the dict itself is not edited, so a run with no flags reproduces
# the committed tables byte for byte.
GROUPS = {
    "rerun": ([ROOT / "runs" / "notation_rerun_20260827.db"],
              ("control", "quad_score_only")),
    "identification": ([ROOT / "runs" / "prompt_arm_ident_main_off_20260827.db",
                        ROOT / "runs" / "prompt_arm_ident_main_low_20260827.db"],
                       ("hedge_placebo", "quad_worked_example")),
    "base_models": ([ROOT / "runs" / "base_model_prompt_main_20260827.db"],
                    ("control", "quad_score_only")),
}

# The LAST probability token in the raw response, mirroring the runtime
# parser's vocabulary but keeping the token text so notation is inspectable.
PROB_RE = re.compile(
    r"(?:probability|confidence)\s*[:=]?\s*([0-9]{1,3}(?:\.[0-9]+)?)\s*%?",
    re.IGNORECASE)
IDK_LETTER_RE = re.compile(r"\b([A-Z])[.)]\s*I DON'T KNOW", re.IGNORECASE)


@dataclass(frozen=True)
class Row:
    group: str
    model: str
    benchmark: str
    arm: str
    item_id: str
    attempted: bool
    correct: bool
    parse_failure: bool
    stored_conf: float | None     # what the runtime parser stored
    corrected_conf: float | None  # after the frozen notation correction
    notation: str                 # "integer_percent" | "fraction" | "none"
    integer_zero: bool
    idk_letter: bool
    # file name of the database the row was read from, so a cohort registry
    # can name one source per (model, arm) and skip superseded rows
    source: str = ""


def classify(raw: str) -> tuple[float | None, str]:
    """Return (corrected probability, notation class) from the raw text."""
    matches = PROB_RE.findall(raw or "")
    if not matches:
        return None, "none"
    token = matches[-1]
    value = float(token)
    if "." in token and value <= 1.0:
        return value, "fraction"
    if value > 100.0:
        return None, "none"
    return value / 100.0, "integer_percent"


def load_group(name: str, paths, arms) -> list[Row]:
    rows: list[Row] = []
    for path in paths:
        if not path.exists():
            print(f"WARNING: {path} missing; group {name} incomplete")
            continue
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        ungraded = 0
        errored = 0
        for r in con.execute(
            "SELECT a.*, m.request_json FROM answers a "
            "JOIN call_meta m USING (key)"
        ):
            if r["error"]:
                # a handful of terminal provider errors can survive retries;
                # they are excluded and counted rather than failing the whole
                # analysis (4 of 16,000 in the re-run)
                errored += 1
                continue
            if r["contract"] not in arms:
                continue
            if r["verdict"] not in ("CORRECT", "INCORRECT", "NOT_ATTEMPTED"):
                ungraded += 1
                continue
            corrected, notation = classify(r["raw"] or "")
            stored = r["confidence"]
            stored = float(stored) if stored is not None else None
            # sanity: our extraction should reproduce the stored value for
            # every parseable row (both use /100 on the same token)
            if (stored is not None and corrected is not None
                    and notation == "integer_percent"
                    and abs(stored - corrected) > 1e-6):
                # the runtime parser saw a different token than our re-read;
                # keep the stored interpretation for the as-parsed track and
                # flag it in the census rather than guessing
                notation = "mismatch"
            # the stored `question` column is the stem only; the option list
            # (with the appended I DON'T KNOW letter) lives in the exact
            # request that was sent, retained in call_meta.request_json
            try:
                request = json.loads(r["request_json"])
                user_text = " ".join(
                    m.get("content", "") for m in request.get("messages", [])
                    if m.get("role") == "user")
            except (TypeError, ValueError):
                user_text = ""
            m = IDK_LETTER_RE.search(user_text)
            idk_letter = bool(
                m and (r["answer"] or "").strip().upper() == m.group(1).upper())
            rows.append(Row(
                group=name, model=r["model"], benchmark=r["benchmark"],
                arm=r["contract"], item_id=r["item_id"],
                attempted=r["verdict"] != "NOT_ATTEMPTED",
                correct=r["verdict"] == "CORRECT",
                parse_failure=bool(r["parse_failure"]),
                stored_conf=stored,
                corrected_conf=corrected,
                notation=notation,
                integer_zero=(notation == "integer_percent"
                              and corrected == 0.0),
                idk_letter=idk_letter,
                source=path.name,
            ))
        con.close()
        if ungraded:
            print(f"WARNING: {path.name}: skipped {ungraded} ungraded rows "
                  f"(re-run after grading for final numbers)")
        if errored:
            print(f"NOTE: {path.name}: excluded {errored} rows with terminal "
                  f"provider errors")
    return rows


def usable(row: Row, conf: float | None) -> bool:
    return (row.attempted and not row.parse_failure
            and conf is not None and 0.0 <= conf <= 1.0)


def score_of(row: Row, conf: float | None) -> float:
    """Proper score under the frozen protocol: NOT_ATTEMPTED scores 0; a
    malformed response (no answer, or no usable probability) is a confident
    error and scores -1 whatever it happened to say. Since the 2026-09-02
    parser fix such rows are stored as parse failures with verdict INCORRECT,
    so this branch is explicit rather than an accident of p = 1 imputation."""
    if not row.attempted:
        return 0.0
    if row.parse_failure or conf is None:
        return -1.0
    p = conf
    p = min(1.0, max(0.0, p))
    return (2 * p - p * p) if row.correct else -(p * p)


def cell_metrics(rows: list[Row], which: str) -> dict:
    def conf_of(row: Row) -> float | None:
        return row.stored_conf if which == "as_parsed" else (
            row.corrected_conf if row.corrected_conf is not None
            else row.stored_conf)
    us = [r for r in rows if usable(r, conf_of(r))]
    # ``accuracy`` is intentionally conditional on a usable answer-plus-
    # probability response because it supports the calibration scatter.  The
    # proper score, however, uses every scheduled question.  Export a second
    # accuracy on that same all-question denominator so exhibits never compare
    # the conditional accuracy with the all-question score.
    overall_accuracy = sum(r.correct for r in rows) / len(rows)
    calibrated_score = sum(score_of(r, conf_of(r)) for r in rows) / len(rows)
    # Tail risk uses the same all-scheduled-question denominator as the proper
    # score.  A response counts only when the model attempted an answer, was
    # wrong, and reported at least 90% confidence after the notation fix.
    # Wrong usable answers at p >= 0.9 over every scheduled response. Malformed
    # responses are excluded (they are already -1 in the score); the same
    # definition as the cell-level scripts and export_warning_comparison.py.
    high_confidence_error_90_rate = sum(
        usable(r, conf_of(r)) and not r.correct and conf_of(r) >= 0.9
        for r in rows
    ) / len(rows)
    # Two per-ERROR readings that survive an accuracy improvement (a model
    # whose accuracy rises to meet an unmoving confidence closes its gap
    # without learning anything about its own errors): the mean confidence
    # stated on wrong usable answers, and the share of those wrong answers
    # stated at 90%+. Both are nan for a cell with no wrong usable answer.
    wrong = [r for r in us if not r.correct]
    confidence_when_wrong = (sum(conf_of(r) for r in wrong) / len(wrong)
                             if wrong else math.nan)
    errors_at_90_share = (sum(conf_of(r) >= 0.9 for r in wrong) / len(wrong)
                          if wrong else math.nan)
    out = {
        "responses": len(rows),
        "accuracy": (sum(r.correct for r in us) / len(us)) if us else math.nan,
        "confidence": (sum(conf_of(r) for r in us) / len(us)) if us else math.nan,
        "overall_accuracy": overall_accuracy,
        "calibrated_score": calibrated_score,
        "brier_loss": overall_accuracy - calibrated_score,
        "high_confidence_error_90_rate": high_confidence_error_90_rate,
        "confidence_when_wrong": confidence_when_wrong,
        "errors_at_90_share": errors_at_90_share,
        "usable_confidence_rate": len(us) / len(rows),
        # The pre-registered primary outcome, on the all-scheduled denominator:
        # the share of responses that declined (the literal I DON'T KNOW or
        # its appended option letter, both graded NOT_ATTEMPTED since the
        # 2026-09-02 regrade). Malformed output is reported beside it so the
        # two ways of "not answering" are never conflated.
        "abstention_rate": sum(not r.attempted for r in rows) / len(rows),
        "malformed_rate": sum(
            r.attempted and (r.parse_failure or conf_of(r) is None)
            for r in rows) / len(rows),
    }
    out["confidence_gap"] = out["confidence"] - out["accuracy"]
    return out


BOOTSTRAP_DRAWS = 2_000
BOOTSTRAP_SEED = 20260902


def cluster_bootstrap(rows: list[Row], control_arm: str, treatment_arm: str,
                      *, draws: int, seed: int) -> dict:
    """Paired three-way cluster bootstrap: models, benchmarks, then items.

    Every draw resamples the paired models and eight benchmarks with replacement,
    then resamples the 100 frozen items inside each selected cell, using the
    SAME items for both arms so the contrast stays paired. Reported are 95%
    percentile intervals for each arm's level and for the treatment minus
    control change, on the equal-cell weighting the exhibits use. With a
    dozen-odd model clusters a percentile interval is somewhat anti-conservative; it is
    still the honest width to show beside a one-point effect that was
    previously printed with no interval at all.
    """
    import random
    by_cell: dict[tuple[str, str], dict[str, dict[str, Row]]] = defaultdict(
        lambda: defaultdict(dict))
    for r in rows:
        by_cell[(r.model, r.benchmark)][r.arm][r.item_id] = r
    models = sorted({m for m, _ in by_cell})
    benchmarks = sorted({b for _, b in by_cell})
    measures = ("confidence", "confidence_gap", "calibrated_score",
                "high_confidence_error_90_rate", "accuracy", "overall_accuracy")
    rng = random.Random(seed)

    def draw_once(resample: bool) -> dict[str, dict[str, float]]:
        ms = [rng.choice(models) for _ in models] if resample else models
        bs = [rng.choice(benchmarks) for _ in benchmarks] if resample else benchmarks
        acc: dict[str, dict[str, list[float]]] = {a: defaultdict(list)
                                                  for a in (control_arm, treatment_arm)}
        for m in ms:
            for b in bs:
                arms = by_cell[(m, b)]
                items = sorted(arms[control_arm])
                chosen = [rng.choice(items) for _ in items] if resample else items
                for arm in (control_arm, treatment_arm):
                    cell = cell_metrics([arms[arm][i] for i in chosen], "corrected")
                    for k in measures:
                        acc[arm][k].append(cell[k])
        return {arm: {k: sum(v) / len(v) for k, v in vals.items()}
                for arm, vals in acc.items()}

    point = draw_once(False)
    samples = [draw_once(True) for _ in range(draws)]
    out: dict = {"draws": draws, "seed": seed,
                 "unit": "models x benchmarks x items, paired across arms"}
    for k in measures:
        for arm in (control_arm, treatment_arm):
            vals = sorted(s[arm][k] for s in samples)
            out[f"{arm}_{k}"] = {"estimate": point[arm][k],
                                 "ci_low": vals[int(0.025 * draws)],
                                 "ci_high": vals[int(0.975 * draws)]}
        deltas = sorted(s[treatment_arm][k] - s[control_arm][k] for s in samples)
        out[f"{k}_change"] = {"estimate": point[treatment_arm][k] - point[control_arm][k],
                              "ci_low": deltas[int(0.025 * draws)],
                              "ci_high": deltas[int(0.975 * draws)]}
    return out


def equal_cell_summary(rows: list[Row], which: str) -> dict:
    cells: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in rows:
        cells[(r.model, r.benchmark)].append(r)
    per_cell = [cell_metrics(group, which) for group in cells.values()]
    n = len(per_cell)
    if n == 0:
        # A model that ran only the control arm has no treatment cells. Its
        # roll-up row carries nan in the treatment columns; the exhibits that
        # read those columns skip such rows by design.
        return {"cells": 0, **{k: math.nan for k in (
            "accuracy", "confidence", "confidence_gap",
            "mean_absolute_confidence_gap", "calibrated_score",
            "overall_accuracy", "brier_loss", "high_confidence_error_90_rate",
            "confidence_when_wrong", "errors_at_90_share",
            "usable_confidence_rate", "answer_rate")}}
    answer_rates = [sum(r.attempted for r in group) / len(group)
                    for group in cells.values()]
    return {
        "cells": n,
        "accuracy": sum(c["accuracy"] for c in per_cell) / n,
        "confidence": sum(c["confidence"] for c in per_cell) / n,
        "confidence_gap": sum(c["confidence_gap"] for c in per_cell) / n,
        "mean_absolute_confidence_gap":
            sum(abs(c["confidence_gap"]) for c in per_cell) / n,
        "calibrated_score": sum(c["calibrated_score"] for c in per_cell) / n,
        "overall_accuracy": sum(c["overall_accuracy"] for c in per_cell) / n,
        "brier_loss": sum(c["brier_loss"] for c in per_cell) / n,
        "high_confidence_error_90_rate": sum(
            c["high_confidence_error_90_rate"] for c in per_cell
        ) / n,
        # Per-error readings average over the cells that have a wrong usable
        # answer (a perfect cell contributes nothing rather than a nan).
        "confidence_when_wrong": _nanmean(
            [c["confidence_when_wrong"] for c in per_cell]),
        "errors_at_90_share": _nanmean(
            [c["errors_at_90_share"] for c in per_cell]),
        "usable_confidence_rate":
            sum(c["usable_confidence_rate"] for c in per_cell) / n,
        "answer_rate": sum(answer_rates) / n,
    }


def _nanmean(values: list[float]) -> float:
    kept = [v for v in values if not math.isnan(v)]
    return sum(kept) / len(kept) if kept else math.nan


# Difficulty-band thresholds, kept identical to the essay page's band_of():
# bands are defined on the CONTROL arm's per-benchmark accuracy, so the same
# benchmark lands in the same band in every exhibit that mentions difficulty.
def band_of(acc: float) -> str:
    return "hard" if acc < 0.75 else ("middle" if acc < 0.85 else "easier")


def emit_rerun_rollups(rerun_rows: list[Row], summary: dict,
                       preregistered: frozenset[str] = frozenset()) -> None:
    """Corrected replacements for the essay's overconfidence exhibits, in the
    same column shapes as the as-parsed prompt_only_calibration_* files so the
    builder switches by path alone. Corrected values sit in the canonical
    column names; the as-parsed twins ride along with an _as_parsed suffix so
    the correction stays auditable in one file.

    `preregistered` is empty unless the caller passed --preregistered, and only
    then does notation_rerun_models.csv gain a trailing `cohort` column. The
    column is opt-in precisely so the committed file's shape never changes
    under a plain run: downstream readers index it by column name."""
    ARM_PREFIX = {"control": "control", "quad_score_only": "treatment"}

    def rollup(keyname: str, keyof) -> list[dict]:
        recs: dict[str, dict] = {}
        for key in sorted({keyof(r) for r in rerun_rows}):
            rec: dict = {keyname: key}
            for arm, prefix in ARM_PREFIX.items():
                sel = [r for r in rerun_rows
                       if keyof(r) == key and r.arm == arm]
                co = equal_cell_summary(sel, "corrected")
                ap = equal_cell_summary(sel, "as_parsed")
                for metric in ("accuracy", "confidence", "confidence_gap",
                               "overall_accuracy", "calibrated_score",
                               "brier_loss", "high_confidence_error_90_rate",
                               "usable_confidence_rate",
                               "answer_rate", "confidence_when_wrong",
                               "errors_at_90_share"):
                    rec[f"{prefix}_{metric}"] = co[metric]
                    rec[f"{prefix}_{metric}_as_parsed"] = ap[metric]
            recs[key] = rec
        return list(recs.values())

    def write(name: str, rows: list[dict]) -> None:
        with (PROCESSED / name).open("w", newline="") as fh:
            w = csv.DictWriter(
                fh, fieldnames=list(rows[0].keys()), lineterminator="\n"
            )
            w.writeheader()
            w.writerows(rows)

    model_rows = rollup("model", lambda r: r.model)
    if preregistered:
        # Appended last so every existing column keeps its position. Any model
        # the caller did not name as pre-registered is, by construction, one
        # that arrived with a later --extra-db.
        for rec in model_rows:
            rec["cohort"] = ("preregistered" if rec["model"] in preregistered
                             else "added")
    write("notation_rerun_models.csv", model_rows)
    bench_rollup = rollup("benchmark", lambda r: r.benchmark)
    write("notation_rerun_benchmarks.csv", bench_rollup)

    # per-cell drop-in (shape of prompt_only_calibration_cells.csv, corrected)
    cell_recs = []
    by_cell: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
    for r in rerun_rows:
        by_cell[(r.model, r.benchmark, r.arm)].append(r)
    for (model, benchmark, arm), rows in sorted(by_cell.items()):
        m = cell_metrics(rows, "corrected")
        cell_recs.append({
            "model": model, "benchmark": benchmark, "arm": arm,
            "responses": m["responses"],
            "answer_rate": sum(r.attempted for r in rows) / len(rows),
            "accuracy": m["accuracy"], "confidence": m["confidence"],
            "overall_accuracy": m["overall_accuracy"],
            "calibrated_score": m["calibrated_score"],
            "brier_loss": m["brier_loss"],
            "high_confidence_error_90_rate":
                m["high_confidence_error_90_rate"],
            "usable_confidence_rate": m["usable_confidence_rate"],
            "confidence_gap": m["confidence_gap"],
            "confidence_when_wrong": m["confidence_when_wrong"],
            "errors_at_90_share": m["errors_at_90_share"],
        })
    write("notation_rerun_cells.csv", cell_recs)

    # reliability bins split by difficulty band (chart toggle source)
    bench_band = {rec["benchmark"]: band_of(rec["control_accuracy"])
                  for rec in bench_rollup}
    band_recs = []
    for band in ("hard", "middle", "easier"):
        for arm in ("control", "quad_score_only"):
            bins: dict[float, list] = defaultdict(list)
            for r in rerun_rows:
                if r.arm != arm or bench_band[r.benchmark] != band:
                    continue
                conf = (r.corrected_conf if r.corrected_conf is not None
                        else r.stored_conf)
                if not usable(r, conf):
                    continue
                bins[min(1.0, math.floor(conf * 10 + 0.5) / 10)].append(
                    (conf, r.correct))
            for b in sorted(bins):
                group = bins[b]
                band_recs.append({
                    "band": band, "arm": arm, "confidence_bin": b,
                    "responses": len(group),
                    "mean_stated_confidence":
                        sum(c for c, _ in group) / len(group),
                    "accuracy": sum(k for _, k in group) / len(group),
                })
    write("notation_rerun_reliability_bins_by_band.csv", band_recs)

    # reliability bins split by model (the chart's model toggles)
    model_recs = []
    for model in sorted({r.model for r in rerun_rows}):
        for arm in ("control", "quad_score_only"):
            bins = defaultdict(list)
            for r in rerun_rows:
                if r.arm != arm or r.model != model:
                    continue
                conf = (r.corrected_conf if r.corrected_conf is not None
                        else r.stored_conf)
                if not usable(r, conf):
                    continue
                bins[min(1.0, math.floor(conf * 10 + 0.5) / 10)].append(
                    (conf, r.correct))
            for b in sorted(bins):
                group = bins[b]
                model_recs.append({
                    "model": model, "arm": arm, "confidence_bin": b,
                    "responses": len(group),
                    "mean_stated_confidence":
                        sum(c for c, _ in group) / len(group),
                    "accuracy": sum(k for _, k in group) / len(group),
                })
    write("notation_rerun_reliability_bins_by_model.csv", model_recs)

    # headline: how many of the control cells sit above the diagonal
    # (the essay's "N of 80 cells overconfident" claim), both tracks
    headline: dict = {}
    for which in ("corrected", "as_parsed"):
        control_cells = [
            cell_metrics(rows, which)
            for (model, benchmark, arm), rows in sorted(by_cell.items())
            if arm == "control"]
        headline[which] = {
            "control_cells": len(control_cells),
            "control_overconfident_cells": sum(
                1 for c in control_cells if c["confidence_gap"] > 0),
        }
    summary["rerun_headline"] = headline


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quantify and correct the probability-notation artifact.")
    parser.add_argument(
        "--extra-db", action="append", default=[], metavar="GROUP=PATH",
        help="pool an additional response database into an existing group. "
             "Repeatable. GROUP is one of: " + ", ".join(GROUPS) + ". The "
             "database must carry that group's arms; rows on any other "
             "contract are ignored, exactly as for the frozen databases.")
    parser.add_argument(
        "--exclude-model", action="append", default=[], metavar="ID",
        help="drop every row of this model before analysis. Repeatable. For "
             "a model whose battery is incomplete in a pooled database (its "
             "rows stay in the database; only the pool ignores them).")
    parser.add_argument(
        "--cohort", metavar="PATH",
        help="the battery's cohort registry (data/processed/battery_cohort.csv, "
             "from scripts/build_battery_cohort.py). When given, the rerun "
             "group keeps a row only if the registry admits its (model, arm) "
             "AND names the row's database as that arm's source, and the rule "
             "arm is read on P (the models admitted under all three prompts). "
             "Replaces --exclude-model and the incomplete-arm drop for the "
             "battery; both still run afterwards as guards.")
    parser.add_argument(
        "--preregistered", action="append", default=[], metavar="ID",
        help="a model id belonging to the pre-registered cohort. Repeatable. "
             "Passing it at all adds a trailing `cohort` column to "
             "notation_rerun_models.csv marking every other model as `added`; "
             "omitting it leaves that file's columns exactly as committed.")
    return parser.parse_args(argv)


def resolve_groups(extra_db: list[str]) -> dict:
    """Copy the frozen GROUPS and append any --extra-db paths to their group.

    The copy is deliberate: GROUPS stays the frozen record of what the
    pre-registered study ran, and the manifest below hashes whatever this
    returns, so a pooled run is self-describing.
    """
    groups = {name: (list(paths), arms) for name, (paths, arms) in GROUPS.items()}
    for spec in extra_db:
        name, sep, raw = spec.partition("=")
        if not sep or not raw:
            raise SystemExit(f"--extra-db expects GROUP=PATH, got: {spec!r}")
        if name not in groups:
            raise SystemExit(
                f"--extra-db: unknown group {name!r}; valid groups are "
                + ", ".join(sorted(groups)))
        path = Path(raw).expanduser()
        if not path.exists():
            raise SystemExit(f"--extra-db not found: {path}")
        groups[name][0].append(path)
    return groups


def main(argv=None) -> None:
    args = parse_args(argv)
    groups = resolve_groups(args.extra_db)
    preregistered = frozenset(args.preregistered)
    cohort = load_cohort(args.cohort) if args.cohort else None
    if cohort is not None:
        # The registry owns source selection as well as row filtering. Without
        # this enumeration a newly admitted control could silently disappear
        # unless somebody also maintained a second list of CLI --extra-db flags.
        paths = groups["rerun"][0]
        seen = {p.resolve() for p in paths}
        required = {ROOT / row[f"{short}_db"] for row in cohort.rows
                    for short in ("control", "rule")
                    if row[f"{short}_status"] == "admitted"
                    and (short == "control" or row["model"] in cohort.p)}
        for path in sorted(required):
            if not path.is_file():
                raise SystemExit(f"cohort source unavailable: {path}")
            if path.resolve() not in seen:
                paths.append(path)
                seen.add(path.resolve())

    all_rows: list[Row] = []
    for name, (paths, arms) in groups.items():
        all_rows.extend(load_group(name, paths, arms))
    if cohort is not None:
        # The registry decides, per (model, arm), which database is the
        # battery's source; a row from any other database is superseded, and
        # a model outside the battery (pilot-only, or a partial extension
        # cohort) has no source at all. The rule arm is further restricted to
        # P so the rule's paired contrast and the warning's read on one set.
        def in_battery(r: Row) -> bool:
            if r.group != "rerun":
                return True
            if not cohort.keeps(r.model, r.arm, r.source):
                return False
            return r.arm == "control" or r.model in cohort.p
        before = len(all_rows)
        kept = [r for r in all_rows if in_battery(r)]
        gone = defaultdict(int)
        for r in all_rows:
            if r.group == "rerun" and not in_battery(r):
                gone[(r.model, r.arm, r.source)] += 1
        all_rows = kept
        print(f"NOTE: --cohort {Path(args.cohort).name} kept {len(kept):,} of "
              f"{before:,} rows; dropped by (model, arm, db): "
              + "; ".join(f"{m} {a} {d}={n}" for (m, a, d), n in sorted(gone.items())))
    if args.exclude_model:
        excluded = set(args.exclude_model)
        dropped = sum(1 for r in all_rows if r.model in excluded)
        all_rows = [r for r in all_rows if r.model not in excluded]
        print(f"NOTE: --exclude-model dropped {dropped:,} rows of "
              + ", ".join(sorted(excluded)))

    # A typo in --preregistered would silently relabel a real model as
    # "added", so check the ids against the data before anything is written.
    if preregistered:
        seen_models = {r.model for r in all_rows}
        unknown = sorted(preregistered - seen_models)
        if unknown:
            raise SystemExit(
                "--preregistered names models absent from the data: "
                + ", ".join(unknown))

    # ---- arm completeness in the rerun group -----------------------------
    # The rerun group is the essay's battery. A model belongs to an arm's
    # level estimates only when that arm is complete: all eight benchmarks,
    # 100 frozen items each. Pilot rows for a model whose full run was never
    # admitted, and the 20-item treatment pilots of models admitted on the
    # control arm alone, are dropped here with a note; the databases keep
    # them. The paired contrast (rule versus control) uses only models with
    # both arms complete, so the treatment and control it compares are the
    # same models on the same items.
    RERUN_BENCHMARKS = 8
    RERUN_ITEMS = 100
    items_by_arm: dict[tuple[str, str], dict[str, set]] = defaultdict(
        lambda: defaultdict(set))
    for r in all_rows:
        if r.group == "rerun":
            items_by_arm[(r.model, r.arm)][r.benchmark].add(r.item_id)
    complete_arms = {
        key for key, per_bench in items_by_arm.items()
        if len(per_bench) == RERUN_BENCHMARKS
        and all(len(v) >= RERUN_ITEMS for v in per_bench.values())
    }
    dropped_incomplete = sum(
        1 for r in all_rows
        if r.group == "rerun" and (r.model, r.arm) not in complete_arms)
    if dropped_incomplete:
        partial = sorted({f"{m} ({a})" for (m, a) in items_by_arm
                          if (m, a) not in complete_arms})
        print(f"NOTE: dropped {dropped_incomplete:,} rerun rows from incomplete "
              "arms (pilot-only cells): " + ", ".join(partial))
        all_rows = [r for r in all_rows
                    if r.group != "rerun" or (r.model, r.arm) in complete_arms]
    rerun_level_models = sorted({m for (m, a) in complete_arms if a == "control"})
    rerun_paired_models = sorted(
        m for m in rerun_level_models if (m, "quad_score_only") in complete_arms)
    if cohort is not None and (set(rerun_level_models) != cohort.models
                               or set(rerun_paired_models) != cohort.p):
        raise SystemExit("loaded battery does not reproduce the registry's complete universes")

    # ---- per-cell table, both tracks side by side -------------------------
    cells: dict[tuple[str, str, str, str], list[Row]] = defaultdict(list)
    for r in all_rows:
        cells[(r.group, r.model, r.benchmark, r.arm)].append(r)
    cell_rows = []
    for (group, model, benchmark, arm), rows in sorted(cells.items()):
        rec = {"study": group, "model": model, "benchmark": benchmark, "arm": arm}
        for which in ("as_parsed", "corrected"):
            m = cell_metrics(rows, which)
            for k, v in m.items():
                rec[f"{which}_{k}"] = v
        rec["fraction_notation_responses"] = sum(
            1 for r in rows if r.notation == "fraction")
        rec["integer_zero_responses"] = sum(1 for r in rows if r.integer_zero)
        rec["idk_letter_responses"] = sum(1 for r in rows if r.idk_letter)
        cell_rows.append(rec)

    # ---- pooled summaries, artifact census, per-model gaps ----------------
    summary: dict = {"arms": {}, "artifact_census": {}, "idk_letter": {},
                     "per_model_gap": {}}
    by_group_arm: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in all_rows:
        by_group_arm[(r.group, r.arm)].append(r)
    for (group, arm), rows in sorted(by_group_arm.items()):
        summary["arms"][f"{group}:{arm}"] = {
            which: equal_cell_summary(rows, which)
            for which in ("as_parsed", "corrected")
        }
        census: dict[str, dict] = {}
        for r in rows:
            c = census.setdefault(r.model, {"fraction": 0, "integer_zero": 0,
                                            "mismatch": 0, "responses": 0})
            c["responses"] += 1
            if r.notation == "fraction":
                c["fraction"] += 1
            if r.integer_zero:
                c["integer_zero"] += 1
            if r.notation == "mismatch":
                c["mismatch"] += 1
        summary["artifact_census"][f"{group}:{arm}"] = {
            m: v for m, v in sorted(census.items(),
                                    key=lambda kv: -kv[1]["fraction"])
            if v["fraction"] or v["integer_zero"] or v["mismatch"]}
        summary["idk_letter"][f"{group}:{arm}"] = sum(
            1 for r in rows if r.idk_letter)
        gaps: dict[str, dict] = {}
        models = sorted({r.model for r in rows})
        for model in models:
            sel = [r for r in rows if r.model == model]
            gaps[model] = {
                which: equal_cell_summary(sel, which)["confidence_gap"]
                for which in ("as_parsed", "corrected")
            }
        summary["per_model_gap"][f"{group}:{arm}"] = gaps

    # ---- corrected contrasts within the fresh rerun -----------------------
    if any(r.group == "rerun" for r in all_rows):
        paired = set(rerun_paired_models)
        rr = [r for r in all_rows if r.group == "rerun" and r.model in paired]
        ctl = equal_cell_summary([r for r in rr if r.arm == "control"], "corrected")
        trt = equal_cell_summary([r for r in rr if r.arm == "quad_score_only"], "corrected")
        # The control level over the paired models only, both tracks, so a
        # sentence that quotes the rule's effect can name the baseline it was
        # measured against rather than the all-model level.
        summary["arms"]["rerun_paired:control"] = {
            which: equal_cell_summary([r for r in rr if r.arm == "control"], which)
            for which in ("as_parsed", "corrected")
        }
        summary["rerun_design"] = {
            "models_control_complete": len(rerun_level_models),
            "models_both_arms_complete": len(rerun_paired_models),
            "control_models": rerun_level_models,
            "paired_models": rerun_paired_models,
            "benchmarks": RERUN_BENCHMARKS, "items_per_benchmark": RERUN_ITEMS,
            # The registry that decided membership, or null for a plain run
            # on the frozen databases alone. When present, paired_models is
            # P by construction and the warning exporter reads the same set.
            "cohort_registry": (str(Path(args.cohort)) if args.cohort else None),
            "p_models": (sorted(cohort.p) if cohort is not None else None),
        }
        summary["rerun_corrected_contrast"] = {
            "confidence_change": trt["confidence"] - ctl["confidence"],
            "accuracy_change": trt["accuracy"] - ctl["accuracy"],
            "signed_gap_change": trt["confidence_gap"] - ctl["confidence_gap"],
            "absolute_gap_change": (trt["mean_absolute_confidence_gap"]
                                    - ctl["mean_absolute_confidence_gap"]),
            "score_change": trt["calibrated_score"] - ctl["calibrated_score"],
        }

        summary["rerun_corrected_contrast_bootstrap"] = cluster_bootstrap(
            rr, "control", "quad_score_only", draws=BOOTSTRAP_DRAWS,
            seed=BOOTSTRAP_SEED)

    # ---- corrected drop-in roll-ups for the overconfidence exhibits -------
    rerun_rows = [r for r in all_rows if r.group == "rerun"]
    if rerun_rows:
        emit_rerun_rollups(rerun_rows, summary, preregistered)

    # ---- corrected reliability bins for the fresh rerun (chart source) ----
    if rerun_rows:
        bin_recs = []
        for arm in ("control", "quad_score_only"):
            bins: dict[float, list] = defaultdict(list)
            for r in rerun_rows:
                if r.arm != arm:
                    continue
                conf = (r.corrected_conf if r.corrected_conf is not None
                        else r.stored_conf)
                if not usable(r, conf):
                    continue
                bins[min(1.0, math.floor(conf * 10 + 0.5) / 10)].append(
                    (conf, r.correct))
            for b in sorted(bins):
                group = bins[b]
                bin_recs.append({
                    "arm": arm, "confidence_bin": b, "responses": len(group),
                    "mean_stated_confidence":
                        sum(c for c, _ in group) / len(group),
                    "accuracy": sum(k for _, k in group) / len(group),
                })
        with (PROCESSED / "notation_rerun_reliability_bins.csv").open(
                "w", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "arm", "confidence_bin", "responses",
                    "mean_stated_confidence", "accuracy",
                ],
                lineterminator="\n",
            )
            w.writeheader()
            w.writerows(bin_recs)

    # ---- corrected reliability bins for every retained prompt study -------
    # This preserves the study label because the identification arms were
    # generated one day after the matched rerun. The essay may compare their
    # shapes, but must keep that cross-run boundary visible.
    all_bin_recs = []
    for (study, arm), study_rows in sorted(by_group_arm.items()):
        bins: dict[float, list[tuple[float, bool]]] = defaultdict(list)
        for row in study_rows:
            conf = (row.corrected_conf if row.corrected_conf is not None
                    else row.stored_conf)
            if not usable(row, conf):
                continue
            bins[min(1.0, math.floor(conf * 10 + 0.5) / 10)].append(
                (conf, row.correct))
        for confidence_bin in sorted(bins):
            group = bins[confidence_bin]
            all_bin_recs.append({
                "study": study,
                "arm": arm,
                "confidence_bin": confidence_bin,
                "responses": len(group),
                "mean_stated_confidence": (
                    sum(conf for conf, _ in group) / len(group)
                ),
                "accuracy": sum(correct for _, correct in group) / len(group),
            })
    if all_bin_recs:
        with (PROCESSED / "notation_artifact_reliability_bins.csv").open(
                "w", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(all_bin_recs[0]),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(all_bin_recs)

    # The direct-confidence exhibit uses the same difficulty and model filters
    # as the main prompting chart. Persist these derived bins rather than
    # making the site build depend on the 90 MB response databases. Difficulty
    # is fixed from the corrected control-arm accuracy in the fresh rerun, so
    # an intervention cannot move a benchmark into a different band.
    if rerun_rows:
        rerun_control = [
            row for row in rerun_rows if row.arm == "control"
        ]
        benchmark_band = {}
        for benchmark in sorted({row.benchmark for row in rerun_control}):
            selected = [
                row for row in rerun_control if row.benchmark == benchmark
            ]
            benchmark_band[benchmark] = band_of(
                equal_cell_summary(selected, "corrected")["accuracy"]
            )

        def write_sliced_bins(filename: str, slice_name: str, slice_of) -> None:
            groups: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
            for row in all_rows:
                slice_value = slice_of(row)
                if slice_value is not None:
                    groups[(row.group, row.arm, slice_value)].append(row)

            records = []
            for (study, arm, slice_value), selected in sorted(groups.items()):
                bins: dict[float, list[tuple[float, bool]]] = defaultdict(list)
                for row in selected:
                    confidence = (
                        row.corrected_conf
                        if row.corrected_conf is not None
                        else row.stored_conf
                    )
                    if not usable(row, confidence):
                        continue
                    confidence_bin = min(
                        1.0,
                        math.floor(confidence * 10 + 0.5) / 10,
                    )
                    bins[confidence_bin].append((confidence, row.correct))
                for confidence_bin in sorted(bins):
                    values = bins[confidence_bin]
                    records.append({
                        "study": study,
                        "arm": arm,
                        slice_name: slice_value,
                        "confidence_bin": confidence_bin,
                        "responses": len(values),
                        "mean_stated_confidence": (
                            sum(confidence for confidence, _ in values)
                            / len(values)
                        ),
                        "accuracy": (
                            sum(correct for _, correct in values) / len(values)
                        ),
                    })

            with (PROCESSED / filename).open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=list(records[0]),
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(records)

        write_sliced_bins(
            "notation_artifact_reliability_bins_by_band.csv",
            "band",
            lambda row: benchmark_band.get(row.benchmark),
        )
        write_sliced_bins(
            "notation_artifact_reliability_bins_by_model.csv",
            "model",
            lambda row: row.model,
        )

    PROCESSED.mkdir(parents=True, exist_ok=True)
    fields = list(cell_rows[0].keys())
    with (PROCESSED / "notation_artifact_cells.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(cell_rows)
    with (PROCESSED / "notation_artifact_summary.json").open("w") as fh:
        json.dump(summary, fh, indent=2)

    def manifest_path(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    def sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    with (PROCESSED / "notation_artifact_manifest.json").open("w") as fh:
        json.dump({
            "protocol": "notes/2026-08-27-notation-artifact-rerun-protocol.md",
            "databases": [
                # repo-relative when possible; an --extra-db may sit outside
                # the checkout and provenance must not crash on it
                {"path": manifest_path(p), "sha256": sha(p)}
                for paths, _ in groups.values() for p in paths if p.exists()],
            "git_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                capture_output=True, text=True).stdout.strip(),
            "correction_rule": ("decimal token <= 1.0 read as fraction; "
                                "integer token read as percent; applied in "
                                "analysis only, runtime parser frozen"),
        }, fh, indent=2)

    # ---- console digest ---------------------------------------------------
    for key, tracks in summary["arms"].items():
        ap, co = tracks["as_parsed"], tracks["corrected"]
        print(f"{key:32s} conf {ap['confidence']:.3f}->{co['confidence']:.3f}  "
              f"gap {ap['confidence_gap']:+.3f}->{co['confidence_gap']:+.3f}  "
              f"|gap| {ap['mean_absolute_confidence_gap']:.3f}->"
              f"{co['mean_absolute_confidence_gap']:.3f}  "
              f"score {ap['calibrated_score']:.3f}->{co['calibrated_score']:.3f}")
    for key, census in summary["artifact_census"].items():
        frac = sum(v["fraction"] for v in census.values())
        zero = sum(v["integer_zero"] for v in census.values())
        if frac or zero:
            top = next(iter(census)) if census else "-"
            print(f"{key:32s} fraction rows {frac:4d} (top: {top})  "
                  f"integer zeros {zero:4d}  idk-letter "
                  f"{summary['idk_letter'][key]}")
    if "rerun_corrected_contrast" in summary:
        c = summary["rerun_corrected_contrast"]
        print("rerun corrected contrast: "
              f"dConf {c['confidence_change']:+.3f}  "
              f"dGap {c['signed_gap_change']:+.3f}  "
              f"d|gap| {c['absolute_gap_change']:+.3f}  "
              f"dScore {c['score_change']:+.3f}")


if __name__ == "__main__":
    main()
