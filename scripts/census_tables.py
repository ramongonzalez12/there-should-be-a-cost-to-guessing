#!/usr/bin/env python3
"""Derive the census matrix tables from sweep.json.

scripts/census.py streams the public EEE datastore and (since v3.2) records
per-(model x benchmark) counters alongside the two marginals, writing
data/processed/sweep.json. The original census CSVs were derived from an
Aug-15 sweep whose sweep.json was lost to a CWD write, so this script exists
to make the derivation committed and repeatable.

What it writes (data/processed/):
  census_matrix.csv          one row per (model, benchmark) cell with graded
                             responses: the data needed to compare models on
                             a CONSISTENT benchmark set. The committed
                             census_by_model.csv is a pure marginal, which is
                             how a model scanned on 2 unusual benchmarks got
                             ranked against models scanned on 30.
  census_matrix_summary.json totals of THIS pull (date, files, responses),
                             kept separate from the Aug-15 census of record:
                             the headline 1,088,601 / 0.68% numbers stay
                             pinned to the frozen pull, and the matrix table
                             cites its own pull date.

With --promote (Ramon's decision of 2026-09-02) the three headline files are
also rewritten from the same sweep: census_summary.csv, census_by_benchmark.csv
and census_by_model.csv. Until then they were pinned to the Aug-15 pull whose
sweep.json was lost, so no headline number could be recomputed. The promoted
pull (2026-09-03, 1,320 of 1,320 files, zero read failures) gives 1,089,024
responses, 0.686% declines and 0.254% stated probabilities, against the frozen
1,088,601 / 0.683% / 0.254%; the earlier figures are recorded in
notes/2026-09-02-census-promotion.md.
"""
from __future__ import annotations

import csv
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def main() -> None:
    sweep = json.loads((PROCESSED / "sweep.json").read_text())
    pairs = sweep.get("by_pair")
    if not pairs:
        raise SystemExit("sweep.json has no by_pair section; re-run "
                         "scripts/census.py (the matrix emission was added "
                         "in v3.2)")

    rows = []
    for key, st in sorted(pairs.items()):
        model, bench = key.split("||", 1)
        n = st.get("n", 0)
        if n == 0:
            continue
        rows.append({
            "model": model,
            "benchmark": bench,
            "n_responses": n,
            "n_correct": st.get("correct", 0),
            "accuracy": st.get("correct", 0) / n,
            "n_decline_phrase": st.get("decline_phrase", 0),
            "decline_rate": st.get("decline_phrase", 0) / n,
            "n_stated_confidence": st.get("stated_conf", 0),
            "n_empty": st.get("empty", 0),
            "n_unextracted": st.get("unextracted", 0),
        })
    with (PROCESSED / "census_matrix.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total = sum(r["n_responses"] for r in rows)
    with (PROCESSED / "census_matrix_summary.json").open("w") as fh:
        json.dump({
            "pulled": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
            "cells": len(rows),
            "models": len({r["model"] for r in rows}),
            "benchmarks": len({r["benchmark"] for r in rows}),
            "responses": total,
            "note": ("fresh re-stream; promoted to the headline census on "
                     "2026-09-02 (see census_summary.csv)"),
        }, fh, indent=2)
    print(f"census_matrix.csv: {len(rows)} cells, "
          f"{len({r['model'] for r in rows})} models, "
          f"{len({r['benchmark'] for r in rows})} benchmarks, "
          f"{total:,} responses")
    if "--promote" in sys.argv:
        promote(sweep)


def promote(sweep: dict) -> None:
    """Rewrite the three headline census files from this sweep.

    Same schemas as the Aug-15 files so every consumer (build_site.py, the
    essay builder, the data dictionary) reads them unchanged. Refuses if the
    sweep recorded any failed file: a headline must never be promoted from a
    partial stream, which is how the Aug-28 re-stream (258 silent failures)
    came to disagree with the frozen pull by 14% of responses.
    """
    if sweep.get("files_failed"):
        raise SystemExit(f"refusing to promote: {sweep['files_failed']} files failed")
    by_bench = sweep["by_bench"]
    by_model = sweep["by_model"]
    bench_rows = []
    for bench, st in by_bench.items():
        n = st.get("n", 0)
        if n == 0:
            continue
        bench_rows.append({
            "benchmark": bench, "n_responses": n, "n_correct": st.get("correct", 0),
            "accuracy": round(st.get("correct", 0) / n, 4),
            "n_decline_phrase": st.get("decline_phrase", 0),
            "decline_rate": round(st.get("decline_phrase", 0) / n, 5),
            "n_stated_confidence": st.get("stated_conf", 0),
            "stated_confidence_rate": round(st.get("stated_conf", 0) / n, 5),
            "n_empty": st.get("empty", 0), "n_unextracted": st.get("unextracted", 0),
        })
    bench_rows.sort(key=lambda r: -r["n_responses"])
    model_rows = []
    for model, st in by_model.items():
        n = st.get("n", 0)
        # Same floor as the Aug-15 file: a model with under 50 graded
        # responses gets no row of its own (it still counts in the totals).
        if n < 50:
            continue
        model_rows.append({
            "model": model, "n_responses": n,
            "accuracy": round(st.get("correct", 0) / n, 4),
            "decline_rate": round(st.get("decline_phrase", 0) / n, 5),
            "stated_confidence_rate": round(st.get("stated_conf", 0) / n, 5),
        })
    model_rows.sort(key=lambda r: -r["n_responses"])
    total = sum(r["n_responses"] for r in bench_rows)
    declines = sum(r["n_decline_phrase"] for r in bench_rows)
    stated = sum(r["n_stated_confidence"] for r in bench_rows)
    empty = sum(r["n_empty"] for r in bench_rows)
    summary = [
        # The model count is every model with a graded response, as on Aug 15;
        # the by-model table floors at 50 responses, so its row count is lower.
        ("responses_scanned", total),
        ("models", sum(1 for st in by_model.values() if st.get("n", 0) > 0)),
        ("benchmarks", len(bench_rows)), ("decline_phrase_count", declines),
        ("decline_rate", round(declines / total, 5)),
        ("stated_confidence_count", stated),
        ("stated_confidence_rate", round(stated / total, 5)),
        ("empty_generations", empty),
    ]
    for name, rows in (("census_by_benchmark.csv", bench_rows),
                       ("census_by_model.csv", model_rows)):
        with (PROCESSED / name).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    with (PROCESSED / "census_summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value"])
        w.writerows(summary)
    print(f"promoted headline census: {total:,} responses, "
          f"{declines / total:.3%} declines, {stated / total:.3%} stated probabilities "
          f"(pulled {sweep.get('pulled')})")


if __name__ == "__main__":
    main()
