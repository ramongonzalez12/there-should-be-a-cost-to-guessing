#!/usr/bin/env python3
"""Apply the pilot format gate to a prompt-arm pilot database and print the table.

WHY THIS EXISTS
---------------
Every prompt-arm extension (Sep 4, Sep 5, Sep 6, Sep 12) piloted 20 items per
benchmark and admitted a model's arm only if every cell had at most one
malformed response. The gate table was assembled by hand each time, in a
note, from ad-hoc SQL, and the hand-assembled tables disagreed with the
databases in small ways (a "10 of 20 on GPQA" that was BoolQ). This script
reads the same database the runner wrote and prints the table the note should
carry, with the finish reasons that decide whether a re-pilot at a higher
ceiling is allowed (only `length` failures qualify).

The gate, as pre-registered on 2026-09-05 and tightened on 2026-09-06:

  * 20 items on each of MMLU-Pro, BoolQ, GPQA-parity and MATH-500;
  * a cell passes with at most ONE malformed response (parse_failure = 1);
  * a cell with exactly TWO extends to 60 items on that benchmark, and then
    passes at 5% (3 of 60) or below;
  * a model's arm is admitted only when every cell passes;
  * a model enters P only when all three arms are admitted.

Free: reads one SQLite database, writes nothing. Usage:

    python3 scripts/gate_prompt_arm_pilot.py runs/prompt_arms_4k_20260912.db
    python3 scripts/gate_prompt_arm_pilot.py DB --markdown   # for the note
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict

PILOT_BENCHMARKS = ("mmlu_pro", "boolq", "gpqa_parity", "math500")
ARMS = ("control", "quad_score_only", "hedge_placebo")
PILOT_ITEMS = 20
PASS_AT_20 = 1          # at most one malformed of twenty
EXTEND_AT_20 = 2        # exactly two: extend the cell to sixty items
EXTENDED_ITEMS = 60
PASS_RATE_EXTENDED = 0.05


def gate_table(db_path: str) -> dict[tuple[str, str, str], dict]:
    """(model, arm, benchmark) -> counts and verdict."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cells: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"items": set(), "malformed": 0, "length": 0, "stop": 0,
                 "other": 0, "errors": 0})
    for r in con.execute(
            "SELECT a.model, a.contract, a.benchmark, a.item_id, a.parse_failure, "
            "a.error, m.finish_reason FROM answers a "
            "LEFT JOIN call_meta m USING (key)"):
        cell = cells[(r["model"], r["contract"], r["benchmark"])]
        if r["error"]:
            cell["errors"] += 1
            continue
        cell["items"].add(r["item_id"])
        if r["parse_failure"]:
            cell["malformed"] += 1
            reason = (r["finish_reason"] or "").lower()
            if reason == "length":
                cell["length"] += 1
            elif reason == "stop":
                cell["stop"] += 1
            else:
                cell["other"] += 1
    con.close()
    for cell in cells.values():
        n = len(cell["items"])
        cell["n"] = n
        if n >= EXTENDED_ITEMS:
            cell["verdict"] = ("pass" if cell["malformed"] / n <= PASS_RATE_EXTENDED
                               else "fail")
        elif n >= PILOT_ITEMS:
            if cell["malformed"] <= PASS_AT_20:
                cell["verdict"] = "pass"
            elif cell["malformed"] == EXTEND_AT_20:
                cell["verdict"] = "extend"
            else:
                cell["verdict"] = "fail"
        else:
            cell["verdict"] = "incomplete"
    return dict(cells)


def arm_verdicts(cells: dict) -> dict[tuple[str, str], str]:
    """(model, arm) -> pass | fail | extend | incomplete over the four cells."""
    out = {}
    for model in sorted({m for m, _, _ in cells}):
        for arm in ARMS:
            verdicts = [cells.get((model, arm, b), {}).get("verdict", "incomplete")
                        for b in PILOT_BENCHMARKS]
            if "fail" in verdicts:
                out[(model, arm)] = "fail"
            elif "incomplete" in verdicts:
                out[(model, arm)] = "incomplete"
            elif "extend" in verdicts:
                out[(model, arm)] = "extend"
            else:
                out[(model, arm)] = "pass"
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db")
    parser.add_argument("--markdown", action="store_true",
                        help="print the per-model table as a Markdown table for a note")
    args = parser.parse_args(argv)
    cells = gate_table(args.db)
    arms = arm_verdicts(cells)
    models = sorted({m for m, _ in arms})

    def cell_text(model, arm, bench):
        c = cells.get((model, arm, bench))
        if not c or c["n"] == 0:
            return "-"
        tags = []
        if c["length"]:
            tags.append(f"{c['length']}L")
        if c["stop"]:
            tags.append(f"{c['stop']}S")
        if c["other"]:
            tags.append(f"{c['other']}?")
        return f"{c['malformed']}/{c['n']}" + (f" ({' '.join(tags)})" if tags else "")

    if args.markdown:
        print("| model | arm | " + " | ".join(PILOT_BENCHMARKS) + " | verdict |")
        print("|---|---|" + "---|" * len(PILOT_BENCHMARKS) + "---|")
    else:
        print(f"{'model':40s} {'arm':16s} " + " ".join(f"{b:>14s}" for b in PILOT_BENCHMARKS)
              + "  verdict")
    for model in models:
        for arm in ARMS:
            row = [cell_text(model, arm, b) for b in PILOT_BENCHMARKS]
            verdict = arms[(model, arm)]
            if args.markdown:
                print(f"| `{model}` | {arm} | " + " | ".join(row) + f" | {verdict} |")
            else:
                print(f"{model:40s} {arm:16s} " + " ".join(f"{t:>14s}" for t in row)
                      + f"  {verdict}")
    print()
    for model in models:
        verdicts = [arms[(model, arm)] for arm in ARMS]
        status = ("ADMITTED to P" if all(v == "pass" for v in verdicts)
                  else "extend then decide" if "extend" in verdicts and "fail" not in verdicts
                  else "incomplete" if "incomplete" in verdicts and "fail" not in verdicts
                  else "OUT")
        print(f"{model:40s} {' / '.join(verdicts):32s} {status}")
    print("\nmalformed counts are parse_failure=1 responses; L = finish_reason length, "
          "S = stop, ? = other/unknown")


if __name__ == "__main__":
    main()
