#!/usr/bin/env python3
"""The census benchmarks the essay's [1.A] comparison leaves out, and both census figures.

    python scripts/census_exclusions.py      # print both figures from data/processed/census_by_benchmark.csv

The response census (scripts/census.py) covers every benchmark in
data/processed/census_by_benchmark.csv. The essay's [1.A] compares those with
one checkable answer and no feedback to the model, and leaves out 14: five
where declining is not comparable (rubric-graded advice, judging other
answers, instruction following, and a context-withheld puzzle set with its
control), and nine agentic tasks where the model can see an action fail. Both
figures are reported, so a reader can see what the exclusion changes.

Sample output:
    all 36 benchmarks:  1,089,024 responses, 7,472 with an uncertainty or decline phrase (0.69%), 1,217 blank
    the 22 compared:    1,023,437 responses, 4,556 with an uncertainty or decline phrase (0.45%), 926 blank
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENSUS = ROOT / "data/processed/census_by_benchmark.csv"

# The 14 benchmarks left out of [1.A], by why (the essay layer's LEFT_OUT).
LEFT_OUT = {
    "rubric": ('healthbench', 'judgebench', 'IFEval', 'lingoly_context', 'lingoly_nocontext'),
    "agent": ('agentharm', 'cvebench', 'swe-bench-verified-mini', 'cybench', 'GAIA', 'terminalbench', 'BountyBench', 'gdm_intercode_ctf', 'swebenchpro'),
}


def left_out() -> set[str]:
    """Every left-out benchmark key."""
    return set(LEFT_OUT["rubric"]) | set(LEFT_OUT["agent"])


def figures(rows: list[dict] | None = None) -> dict:
    """Responses and decline phrases over all census benchmarks and over the compared ones."""
    if rows is None:
        with CENSUS.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    left = left_out()
    missing = left - {r["benchmark"] for r in rows}
    if missing:
        raise SystemExit(f"left-out benchmarks missing from the census table: {sorted(missing)}")
    out = {}
    for name, own in (("all", rows), ("compared", [r for r in rows if r["benchmark"] not in left])):
        n = sum(int(r["n_responses"]) for r in own)
        d = sum(int(r["n_decline_phrase"]) for r in own)
        out[name] = {"benchmarks": len(own), "responses": n, "decline_phrase": d, "rate": d / n,
                     "empty": sum(int(r["n_empty"]) for r in own)}
    return out


def lines() -> list[str]:
    f = figures()
    out = []
    for name, label in (("all", f"all {f['all']['benchmarks']} benchmarks"),
                        ("compared", f"the {f['compared']['benchmarks']} compared")):
        v = f[name]
        out.append(f"{label + ':':<20}{v['responses']:,} responses, {v['decline_phrase']:,} with an uncertainty "
                   f"or decline phrase ({v['rate'] * 100:.2f}%), {v['empty']:,} blank")
    return out


def main() -> int:
    print("\n".join(lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
