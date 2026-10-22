"""Warning-prompt comparison from response-level data, one control per exhibit.

Why this exists. The essay's "warning about overconfidence" row once mixed two
controls: the pre-specified Aug 26 integrated control for the gap and score,
and the Aug 27 re-run control for the 90%+ error tail, because the Aug 26
response database was believed lost and only its decile summary survived.
The database was recovered on 2026-09-02 (see runs/RECOVERY.md), so every
outcome can now be computed from responses against the same control, with a
paired item bootstrap, and the confidence-band bridge is exact rather than a
decile approximation.

Inputs (all regraded from raw with the fixed parser):
  runs/prompt_only_main_off_20260826.db, runs/prompt_only_main_low_20260826.db
      control arm: the pre-specified baseline, two calls per question
  runs/prompt_arm_ident_main_off_20260827.db, runs/prompt_arm_ident_main_low_20260827.db
      hedge_placebo arm: the warning, one call per question
  runs/notation_rerun_20260827.db
      control arm: the same-day sensitivity control, one call per question

Outputs in data/processed/:
  warning_comparison_levels.csv   scope x control x metric, with paired 95% CIs
  warning_comparison_band_bridge.csv  exact response-level band decomposition
  warning_comparison_manifest.json

Definitions match scripts/analyze_notation_artifact.py exactly: a response is
usable when attempted, well formed, and carrying a probability in [0, 1];
accuracy and confidence average over usable responses; the score averages
over every scheduled response with abstention = 0 and malformed = -1; the
90%+ error tail counts wrong attempted answers at p >= 0.9 over every
scheduled response. Cells (model x benchmark) are weighted equally.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import random
import sqlite3
import subprocess
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
sys.path.insert(0, str(ROOT / "src"))

from belowzero.cohort import load_cohort

# The frozen inputs. A later cohort that ran the same arm can be pooled into
# any of these lists at the command line with --extra-db NAME=PATH, where NAME
# is a control name below or "warning". Neither constant is edited for that, so
# a run with no flags reproduces the committed tables byte for byte.
CONTROLS = {
    "aug26_integrated": ([ROOT / "runs" / "prompt_only_main_off_20260826.db",
                          ROOT / "runs" / "prompt_only_main_low_20260826.db"], "control"),
    "aug27_rerun": ([ROOT / "runs" / "notation_rerun_20260827.db"], "control"),
}
WARNING = ([ROOT / "runs" / "prompt_arm_ident_main_off_20260827.db",
            ROOT / "runs" / "prompt_arm_ident_main_low_20260827.db"], "hedge_placebo")
# Difficulty bands are defined on the control arm's per-benchmark accuracy
# among answered questions, exactly as the essay's band_of() does (hard below
# 75%, middle 75% to 85%, easier above 85%). Derived from the data, never
# listed by hand: the 2026-09-02 regrade moved BBQ from 84% to 91% and so from
# the middle band to the easier one.


def band_of(accuracy: float) -> str:
    # Exclusive upper bound on "middle", matching the essay builder's band_of()
    # (in the private lab): hard < 0.75 <= middle <
    # 0.85 <= easier. This exporter used to close the middle band at 0.85
    # inclusive, which put a benchmark sitting exactly at 0.85 in a
    # different band here than on the published page.
    if accuracy < 0.75:
        return "hard"
    if accuracy < 0.85:
        return "middle"
    return "easier"


def bands_from(control) -> dict[str, tuple[str, ...]]:
    by_bench = defaultdict(list)
    for (model, bench), rs in control.items():
        by_bench[bench].append(cell_metrics(rs)["accuracy"])
    out = defaultdict(list)
    for bench, accs in by_bench.items():
        out[band_of(sum(accs) / len(accs))].append(bench)
    return {k: tuple(sorted(v)) for k, v in out.items()}
def battery_bands() -> dict[str, tuple[str, ...]]:
    """Bands from the battery's per-benchmark control accuracy, or {}."""
    path = ROOT / "data" / "processed" / "notation_rerun_benchmarks.csv"
    if not path.exists():
        return {}
    out = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[band_of(float(row["control_accuracy"]))].append(row["benchmark"])
    return {k: tuple(sorted(v)) for k, v in out.items()}


# The pre-registered grid: 10 models x 8 benchmarks. Asserted exactly when the
# script runs on the frozen databases alone; a pooled run is instead checked
# for a complete rectangular grid, whatever its size.
FROZEN_CELLS = 80
BAND_EDGES = [("Below 60%", 0.0, 0.6), ("60% to 79%", 0.6, 0.8),
              ("80% to 89%", 0.8, 0.9), ("90% to 100%", 0.9, 1.01)]
DRAWS = 2_000
SEED = 20260902


# Models dropped before any cell is formed (set from --exclude-model).
EXCLUDED_MODELS: set = set()


def load(paths, arm):
    rows = defaultdict(list)  # (model, benchmark) -> list of response dicts
    n = 0
    for path in paths:
        if not path.exists() or path.stat().st_size == 0:
            raise SystemExit(f"{path} missing or empty")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        for r in con.execute("SELECT * FROM answers WHERE error IS NULL AND contract=?", (arm,)):
            if r["model"] in EXCLUDED_MODELS:
                continue
            if r["verdict"] not in ("CORRECT", "INCORRECT", "NOT_ATTEMPTED"):
                raise SystemExit(f"{path}: ungraded row {r['key']}")
            conf = r["confidence"]
            attempted = r["verdict"] != "NOT_ATTEMPTED"
            pf = bool(r["parse_failure"])
            usable = attempted and not pf and conf is not None and 0.0 <= conf <= 1.0
            rows[(r["model"], r["benchmark"])].append({
                "item": r["item_id"], "attempted": attempted, "pf": pf,
                "correct": r["verdict"] == "CORRECT", "conf": conf, "usable": usable,
                # the database the row came from, so a cohort registry can
                # name one source per (model, arm) and skip superseded rows
                "db": path.name})
            n += 1
        con.close()
    return rows, n


def score(r):
    if not r["attempted"]:
        return 0.0
    if r["pf"] or r["conf"] is None:
        return -1.0
    p = min(1.0, max(0.0, r["conf"]))
    return 2 * p - p * p if r["correct"] else -p * p


def cell_metrics(rs):
    us = [r for r in rs if r["usable"]]
    n = len(rs)
    acc = sum(r["correct"] for r in us) / len(us) if us else float("nan")
    conf = sum(r["conf"] for r in us) / len(us) if us else float("nan")
    return {"accuracy": acc, "confidence": conf, "gap": conf - acc,
            "score": sum(score(r) for r in rs) / n,
            # Wrong USABLE answers at p >= 0.9 over every scheduled response. A
            # malformed response is already a confident error in the score; it
            # is not counted here, matching the cell-level analysis scripts.
            "tail": sum(r["usable"] and not r["correct"] and r["conf"] >= 0.9 for r in rs) / n,
            "overall_accuracy": sum(r["correct"] for r in rs) / n,
            "usable_rate": len(us) / n}


METRICS = ("gap", "score", "tail", "accuracy", "confidence", "overall_accuracy")


def equal_cell(cells):
    out = {}
    for k in METRICS:
        out[k] = sum(c[k] for c in cells) / len(cells)
    return out


def scoped_levels(control, warning, keys, rng, draws):
    """Point levels and paired-item bootstrap CIs for one set of cells."""
    def one(resample):
        ctl_cells, wrn_cells = [], []
        for key in keys:
            c_rows = control[key]
            w_rows = warning[key]
            if resample:
                items = sorted({r["item"] for r in w_rows})
                chosen = [rng.choice(items) for _ in items]
                c_by = defaultdict(list)
                w_by = defaultdict(list)
                for r in c_rows:
                    c_by[r["item"]].append(r)
                for r in w_rows:
                    w_by[r["item"]].append(r)
                c_rows = [r for i in chosen for r in c_by[i]]
                w_rows = [r for i in chosen for r in w_by[i]]
            ctl_cells.append(cell_metrics(c_rows))
            wrn_cells.append(cell_metrics(w_rows))
        return equal_cell(ctl_cells), equal_cell(wrn_cells)

    point_c, point_w = one(False)
    samples = [one(True) for _ in range(draws)]
    out = {}
    for k in METRICS:
        lo, hi = int(0.025 * draws), int(0.975 * draws)
        cs = sorted(s[0][k] for s in samples)
        ws = sorted(s[1][k] for s in samples)
        ds = sorted(s[1][k] - s[0][k] for s in samples)
        out[k] = {"baseline": point_c[k], "baseline_ci": (cs[lo], cs[hi]),
                  "warning": point_w[k], "warning_ci": (ws[lo], ws[hi]),
                  "change": point_w[k] - point_c[k], "change_ci": (ds[lo], ds[hi])}
    return out


def band_bridge(control, warning):
    """Exact price-volume style bridge over confidence bands, response level."""
    def band_stats(rows_by_cell):
        shares = defaultdict(float)
        scores = defaultdict(list)
        cells = list(rows_by_cell.values())
        for rs in cells:
            n = len(rs)
            counts = defaultdict(int)
            for r in rs:
                if r["usable"]:
                    for name, lo, hi in BAND_EDGES:
                        if lo <= r["conf"] < hi:
                            counts[name] += 1
                            scores[name].append(score(r))
                            break
                else:
                    counts["No usable probability"] += 1
                    scores["No usable probability"].append(score(r))
            for name, c in counts.items():
                shares[name] += c / n / len(cells)
        means = {name: (sum(v) / len(v) if v else 0.0) for name, v in scores.items()}
        return shares, means

    s0, m0 = band_stats(control)
    s1, m1 = band_stats(warning)
    names = [n for n, _, _ in BAND_EDGES] + ["No usable probability"]
    rows = []
    for name in names:
        rows.append({"band": name,
                     "baseline_share": s0.get(name, 0.0), "warning_share": s1.get(name, 0.0),
                     "baseline_within_score": m0.get(name, 0.0),
                     "warning_within_score": m1.get(name, 0.0),
                     "baseline_contribution": s0.get(name, 0.0) * m0.get(name, 0.0),
                     "warning_contribution": s1.get(name, 0.0) * m1.get(name, 0.0)})
    mix = sum((s1.get(n, 0) - s0.get(n, 0)) * m0.get(n, 0) for n in names)
    within = sum(s1.get(n, 0) * (m1.get(n, 0) - m0.get(n, 0)) for n in names)
    return rows, {"mix_effect": mix, "within_effect": within,
                  "total_change": sum(r["warning_contribution"] for r in rows)
                  - sum(r["baseline_contribution"] for r in rows)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


WARNING_NAME = "warning"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Warning-prompt comparison from response-level data.")
    parser.add_argument(
        "--extra-db", action="append", default=[], metavar="NAME=PATH",
        help="pool an additional response database into one input list. "
             "Repeatable. NAME is one of: "
             + ", ".join([*CONTROLS, WARNING_NAME])
             + ". The database must carry that list's arm; the arm filter in "
               "load() ignores everything else.")
    parser.add_argument(
        "--exclude-model", action="append", default=[], metavar="ID",
        help="drop every row of this model before analysis (repeatable): for "
             "a model whose battery is incomplete in a pooled database.")
    parser.add_argument(
        "--cohort", metavar="PATH",
        help="the battery's cohort registry (data/processed/battery_cohort.csv). "
             "When given, the warning arm and the aug27_rerun control are read "
             "on P (models admitted under all three prompts), each row from "
             "the database the registry names for its arm. The aug26_integrated "
             "control (the same-run 13-model study) is left as it is.")
    return parser.parse_args(argv)


def resolve_inputs(extra_db):
    """Copy the frozen CONTROLS/WARNING specs and append any --extra-db paths.

    Returns (controls_spec, warning_spec). The frozen constants stay untouched
    so they remain the record of what the pre-registered study ran, and the
    manifest hashes whatever comes back here.
    """
    controls_spec = {name: (list(paths), arm)
                     for name, (paths, arm) in CONTROLS.items()}
    warning_paths, warning_arm = list(WARNING[0]), WARNING[1]
    valid = [*controls_spec, WARNING_NAME]
    for spec in extra_db:
        name, sep, raw = spec.partition("=")
        if not sep or not raw:
            raise SystemExit(f"--extra-db expects NAME=PATH, got: {spec!r}")
        if name not in valid:
            raise SystemExit(
                f"--extra-db: unknown name {name!r}; valid names are "
                + ", ".join(valid))
        path = pathlib.Path(raw).expanduser()
        if not path.exists():
            raise SystemExit(f"--extra-db not found: {path}")
        if name == WARNING_NAME:
            warning_paths.append(path)
        else:
            controls_spec[name][0].append(path)
    return controls_spec, (warning_paths, warning_arm)


def manifest_path(path):
    """Repo-relative when possible; an --extra-db may sit outside the checkout
    and provenance must not crash on it."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv=None):
    args = parse_args(argv)
    EXCLUDED_MODELS.update(args.exclude_model)
    controls_spec, warning_spec = resolve_inputs(args.extra_db)

    if args.cohort:
        selected = load_cohort(args.cohort)
        for short, paths in (("control", controls_spec["aug27_rerun"][0]),
                             ("warning", warning_spec[0])):
            for source in sorted({row[f"{short}_db"] for row in selected.rows
                                  if row["model"] in selected.p}):
                path = ROOT / source
                if not path.is_file():
                    raise SystemExit(f"cohort source unavailable: {path}")
                # CLI extras can be relative while cohort paths are absolute.
                # Opening both spellings duplicates every response in that DB.
                if not any(path.resolve() == existing.resolve() for existing in paths):
                    paths.append(path)

    warning, n_w = load(*warning_spec)
    controls = {name: load(paths, arm) for name, (paths, arm) in controls_spec.items()}
    if args.cohort:
        # One model set for both prompt levers. The registry names, per
        # (model, arm), the one database that is the battery's source; rows
        # from any other database are superseded and a model outside P has
        # no warning comparison at all. Applied to the warning arm and to the
        # battery's own control (aug27_rerun); the aug26 two-rep control is
        # the pre-registered same-run study and keeps its own thirteen.
        cohort = load_cohort(args.cohort)

        def restrict(cells, arm):
            out = defaultdict(list)
            for (model, bench), rs in cells.items():
                if model not in cohort.p:
                    continue
                kept = [r for r in rs if cohort.keeps(model, arm, r["db"])]
                if kept:
                    out[(model, bench)] = kept
            return out

        warning = restrict(warning, warning_spec[1])
        n_w = sum(len(rs) for rs in warning.values())
        # load() returns (rows, count); the arm name lives in the spec
        ctl_rows, _ = controls["aug27_rerun"]
        ctl_rows = restrict(ctl_rows, controls_spec["aug27_rerun"][1])
        controls["aug27_rerun"] = (ctl_rows, sum(len(rs) for rs in ctl_rows.values()))
        # The model set alone cannot detect a source loaded twice. Match
        # each model's response count to its selected registry arm before
        # spending CPU on bootstrap estimates or writing a manifest.
        for cells, short in ((warning, "warning"), (ctl_rows, "control")):
            observed = {model: sum(len(rs) for (m, _), rs in cells.items() if m == model)
                        for model in cohort.p}
            expected = {row["model"]: int(row[short + "_rows"]) for row in cohort.rows
                        if row["model"] in cohort.p}
            if observed != expected:
                raise SystemExit(f"{short} response counts differ from selected cohort sources")
        if {m for m, _ in warning} != cohort.p or {m for m, _ in ctl_rows} != cohort.p:
            raise SystemExit("warning comparison does not cover the exact paired cohort")
        print(f"NOTE: --cohort {pathlib.Path(args.cohort).name}: warning arm on "
              f"{len({m for m, _ in warning})} models (P = {len(cohort.p)}), "
              f"aug27_rerun control on {len({m for m, _ in ctl_rows})}")
    keys = sorted(warning)
    if args.extra_db:
        # Pooled: the grid may be larger than the frozen one, but it must still
        # be a complete rectangle, or the equal-cell weighting is over a ragged
        # set and every level below is quietly mis-weighted.
        rectangle = len({m for m, _ in keys}) * len({b for _, b in keys})
        if len(keys) != rectangle:
            raise SystemExit(
                f"incomplete warning grid: {len(keys)} cells for "
                f"{rectangle} model x benchmark combinations")
    elif len(keys) != FROZEN_CELLS:
        raise SystemExit(f"expected {FROZEN_CELLS} warning cells, found {len(keys)}")
    rng = random.Random(SEED)
    level_rows = []
    # Computed once, outside the per-control loop, so the scopes used to
    # build the CSV and the "bands" key written into the manifest are
    # provably the same dict. Before 2026-09-06 the loop below recomputed
    # `battery_bands() or bands_from(control)` on every iteration (correct
    # for the CSV, since notation_rerun_benchmarks.csv is present and always
    # wins), but the manifest below the loop was written from a separate,
    # unconditional `bands_from(controls["aug26_integrated"][0])` call --
    # the control arm's own accuracy, never the battery's. That put
    # math500 and mmlu_pro (hard on the battery, "middle"/near it on the
    # aug26 control alone) in the wrong band in the committed manifest while
    # the CSV scopes were already correct.
    battery = battery_bands()
    for cname, (control, _) in controls.items():
        # A control may cover a SUBSET of the warning grid: the Aug 26 two-rep
        # control exists only for the pre-registered ten, while the warning
        # arm and the Aug 27 control are pooled over the extended cohort. The
        # comparison then runs over the cells the control has, and the
        # manifest records how many that is. A control cell with no warning
        # twin is still an error.
        orphan = sorted(set(control) - set(keys))
        if orphan:
            raise SystemExit(f"{cname}: control cells with no warning arm: {orphan[:3]}")
        ckeys = [k for k in keys if k in control]
        if len(ckeys) != len(keys):
            print(f"NOTE: {cname} covers {len(ckeys)} of {len(keys)} warning cells; "
                  "its comparison is over those cells only")
        # Difficulty bands are the battery's (notation_rerun_benchmarks.csv,
        # the control arm over every model that completed it), so the warning
        # table groups benchmarks exactly as every other exhibit does. The
        # control's own accuracy defines the bands only when that file is
        # absent (a checkout without the roll-ups).
        scopes = {"all": ckeys}
        bands = battery or bands_from(control)
        for band, benches in bands.items():
            scopes[f"band:{band}"] = [k for k in ckeys if k[1] in benches]
        for model in sorted({m for m, _ in ckeys}):
            scopes[f"model:{model}"] = [k for k in ckeys if k[0] == model]
        for bench in sorted({b for _, b in ckeys}):
            scopes[f"benchmark:{bench}"] = [k for k in ckeys if k[1] == bench]
        for scope, sel in scopes.items():
            draws = DRAWS if scope == "all" or scope.startswith("band") else 500
            lv = scoped_levels(control, warning, sel, rng, draws)
            for k in METRICS:
                v = lv[k]
                level_rows.append({
                    "control": cname, "scope": scope, "cells": len(sel), "metric": k,
                    "baseline": v["baseline"], "baseline_ci_low": v["baseline_ci"][0],
                    "baseline_ci_high": v["baseline_ci"][1],
                    "warning": v["warning"], "warning_ci_low": v["warning_ci"][0],
                    "warning_ci_high": v["warning_ci"][1],
                    "change": v["change"], "change_ci_low": v["change_ci"][0],
                    "change_ci_high": v["change_ci"][1], "bootstrap_draws": draws})
    with (PROCESSED / "warning_comparison_levels.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(level_rows[0]))
        w.writeheader()
        w.writerows(level_rows)

    # The bridge decomposes ONE control's score change into a mix effect and a
    # within-band effect, so both halves have to be the same cells. Until the
    # 2026-09-06 warning extension the whole warning grid WAS the aug26
    # control's grid, so passing `warning` unrestricted was accidentally
    # right and the mismatch could not show itself. Pooling the extension in
    # took the warning arm to 248 cells over 31 models while this control
    # stays at 104 over 13, and the unrestricted call then subtracted a
    # 31-model warning arm from a 13-model baseline: `total_change` stopped
    # reconciling with the aug26 headline score change (-0.042 against
    # -0.001) while every column still looked plausible. Restricting to the
    # control's own keys reproduces the published bridge exactly. A bridge
    # over the extended cohort is a different exhibit and needs the
    # aug27_rerun control on BOTH sides, not this control and that warning arm.
    _bridge_control = controls["aug26_integrated"][0]
    bridge_rows, totals = band_bridge(
        _bridge_control, {k: warning[k] for k in _bridge_control})
    with (PROCESSED / "warning_comparison_band_bridge.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(bridge_rows[0]))
        w.writeheader()
        w.writerows(bridge_rows)

    manifest = {
        "created_by": "scripts/export_warning_comparison.py",
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, check=False,
                                     text=True, cwd=ROOT).stdout.strip(),
        "bootstrap": {"draws_primary": DRAWS, "draws_breakouts": 500, "seed": SEED,
                      "unit": "items within model-benchmark cells, paired across arms"},
        "inputs": [{"path": manifest_path(p), "sha256": sha(p)}
                   for paths, _ in [warning_spec, *controls_spec.values()]
                   for p in paths],
        "responses": {"warning": n_w, **{k: v[1] for k, v in controls.items()}},
        "cohort_registry": args.cohort,
        "warning_models": sorted({m for m, _ in keys}),
        "band_bridge_totals": totals,
        # Same value the scopes loop above used (`battery`, computed once
        # before the loop): the manifest must describe the CSV it sits next
        # to, not a second, independently-computed band assignment. Falls
        # back to the aug26 control's own accuracy only when the battery
        # roll-up file is absent, matching the scopes' fallback exactly.
        "bands": battery or bands_from(controls["aug26_integrated"][0]),
        "bands_source": ("notation_rerun_benchmarks.csv (the battery's control arm)"
                          if battery else
                          "this run's aug26_integrated control arm"),
        "headline": {row["metric"]: {"baseline": row["baseline"], "warning": row["warning"],
                                     "change": row["change"],
                                     "change_ci": [row["change_ci_low"], row["change_ci_high"]]}
                     for row in level_rows
                     if row["control"] == "aug26_integrated" and row["scope"] == "all"},
    }
    (PROCESSED / "warning_comparison_manifest.json").write_text(json.dumps(manifest, indent=1))
    for cname in controls:
        for row in level_rows:
            if row["control"] == cname and row["scope"] == "all":
                print(f"{cname:16s} {row['metric']:10s} {row['baseline']:+.4f} -> "
                      f"{row['warning']:+.4f}  change {row['change']:+.4f} "
                      f"[{row['change_ci_low']:+.4f}, {row['change_ci_high']:+.4f}]")
    print("bridge:", {k: round(v, 4) for k, v in totals.items()})


if __name__ == "__main__":
    main()
