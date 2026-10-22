#!/usr/bin/env python3
"""Say what the replication runs establish, and refuse to say more.

Three questions, in descending order of how well the data can answer them.

1. **Does the contrast have a consistent sign?** A sign test. Cheap to support,
   tolerant of runs that are not exchangeable for anything else, and the actual
   claim under dispute when someone asks whether a result replicates.
2. **How much does the effect move between runs?** A spread, reported with its
   degrees of freedom attached.
3. **How much of that movement was the curriculum?** A nested descriptive bound,
   and deliberately NOT a test. See ``decomposition`` for why.

The refusals matter as much as the outputs. With a handful of runs it is very
easy to produce a p-value or a variance component that looks like an answer and
is noise with a decimal point on it.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import pathlib
import statistics

# Runs whose curriculum was the frozen file order. Seeds 0 and 1 were trained
# before --seed reached the item ordering, so they differ from each other only
# in the provider's sampling stream. Everything else varies item order too.
FIXED_CURRICULUM_SEEDS = (0, 1)

OBJECTIVES = (("binary", "accuracy only"),
              ("quadratic", "confidence-aware"),
              ("quad_cost_0.09", "+ assertion cost"))

MEASURES = (("score_quadratic", "quadratic score"),
            ("accuracy", "plain accuracy"),
            ("overconfidence", "calibration gap"))


def load(path: pathlib.Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def delta(rows: list[dict], seed: int, objective: str, step: int, column: str
          ) -> float | None:
    """A version's change from ITS OWN run's untuned base.

    Each run is measured against its own base rather than a shared one, because
    the base is re-measured per run and those measurements differ by about as
    much as several of the effects being compared.
    """
    def one(obj, st):
        for row in rows:
            if (int(row["seed"]) == seed and row["objective"] == obj
                    and int(row["step"]) == st and row.get(column) not in (None, "")):
                return float(row[column])
        return None
    base, value = one("base", 0), one(objective, step)
    if base is None or value is None:
        return None
    return value - base


def sign_test(values: list[float]) -> dict:
    """Unanimity across independent runs, and what that is worth.

    Under a null where the contrast has no consistent direction, each run is a
    coin flip and P(all n agree) = 2^-(n-1). This is the one inference here that
    survives the runs not being exchangeable for a variance estimate: seeds 0 and
    1 held the curriculum fixed and the rest did not, which rules out pooling
    them into one spread, but under "the sign is arbitrary" they are exchangeable
    enough to count.
    """
    positive = sum(v > 0 for v in values)
    negative = sum(v < 0 for v in values)
    n = len(values)
    unanimous = n > 0 and (positive == n or negative == n)
    return {
        "n": n,
        "positive": positive,
        "negative": negative,
        "unanimous": unanimous,
        # Two-sided: either direction would have counted as unanimous.
        "p_if_unanimous": 2.0 ** -(n - 1) if unanimous and n > 1 else None,
    }


def decomposition(fixed: list[float], varied: list[float]) -> dict:
    """Spread with the curriculum held fixed, against spread with it varying.

    Reported as a NESTED DESCRIPTIVE BOUND with degrees of freedom stated, and
    deliberately not as a test or a subtracted component. Two reasons, both of
    which make the tempting version worthless here:

    * As a test it is an F with tiny df. With one and three degrees of freedom
      the 95th percentile is near 216, so it cannot separate "the curriculum
      contributes nothing" from "the curriculum triples the variance".
    * As a subtracted component, ``s2_varied - s2_fixed`` is frequently negative
      with this little data, and the instinct to truncate at zero biases it
      upward exactly when it is least reliable.

    So the honest statement is that the first spread is a COMPONENT of the
    second, that the published interval previously used only the first, and how
    many degrees of freedom each rests on.
    """
    out: dict = {}
    for name, values in (("fixed_curriculum", fixed), ("varied_curriculum", varied)):
        out[name] = {
            "n": len(values),
            "df": max(len(values) - 1, 0),
            "sd": statistics.stdev(values) if len(values) > 1 else None,
            "range": (max(values) - min(values)) if values else None,
            "mean": statistics.fmean(values) if values else None,
        }
    out["note"] = (
        "sampling-stream variation alone is a component of the total; it is not "
        "a separate quantity to subtract, and the ratio is not tested"
    )
    return out


def report(
    rows: list[dict],
    *,
    dose: int,
    floor: dict | None,
    run_inventory: dict | None = None,
) -> dict:
    # A multi-dose CSV can contain a partial seed at earlier steps. The header
    # and fixed/varied groupings must describe the requested dose, not every
    # seed that appears anywhere in the file.
    seeds = sorted(
        {
            int(row["seed"])
            for row in rows
            if row["objective"] != "base" and int(row["step"]) == dose
        }
    )
    fixed = [s for s in seeds if s in FIXED_CURRICULUM_SEEDS]
    varied = [s for s in seeds if s not in FIXED_CURRICULUM_SEEDS]
    out: dict = {"dose": dose, "seeds": seeds,
                 "fixed_curriculum_seeds": fixed,
                 "varied_curriculum_seeds": varied,
                 "run_inventory": run_inventory or {},
                 "objectives": {}}

    for objective, label in OBJECTIVES:
        entry: dict = {"label": label, "measures": {}}
        for column, measure in MEASURES:
            values = {s: delta(rows, s, objective, dose, column) for s in seeds}
            present = {s: v for s, v in values.items() if v is not None}
            if not present:
                continue
            entry["measures"][measure] = {
                "per_seed": {str(s): round(v, 4) for s, v in present.items()},
                "sign": sign_test(list(present.values())),
                "decomposition": decomposition(
                    [present[s] for s in fixed if s in present],
                    [present[s] for s in varied if s in present],
                ),
            }
            if floor and column in ("score_quadratic", "accuracy"):
                key = "quadratic" if column == "score_quadratic" else "accuracy"
                band = floor.get(key, {}).get("range", 0.0) / 2
                entry["measures"][measure]["within_measurement_band"] = [
                    str(s) for s, v in present.items() if abs(v) < band
                ]
        out["objectives"][objective] = entry

    # Between-version contrasts, which is what the write-up actually argues.
    out["contrasts"] = {}
    for (a, la), (b, lb) in itertools.combinations(OBJECTIVES, 2):
        for column, measure in MEASURES:
            paired = {}
            for s in seeds:
                va = delta(rows, s, a, dose, column)
                vb = delta(rows, s, b, dose, column)
                if va is not None and vb is not None:
                    paired[s] = vb - va
            if len(paired) > 1:
                out["contrasts"][f"{lb} minus {la}: {measure}"] = {
                    "per_seed": {str(s): round(v, 4) for s, v in paired.items()},
                    "sign": sign_test(list(paired.values())),
                }
    return out


def render(result: dict) -> str:
    header = (f"  runs: {result['seeds']}  "
              f"(fixed curriculum {result['fixed_curriculum_seeds']}, "
              f"varied {result['varied_curriculum_seeds']})")
    lines = [f"REPLICATION VERDICT at {result['dose']} steps", header]
    missing_at_dose = {
        seed: record
        for seed, record in result.get("run_inventory", {}).items()
        if result["dose"] not in record.get("doses", [])
    }
    if missing_at_dose:
        lines.append(
            f"  no numeric row at {result['dose']} steps, retained as observed runs:"
        )
        for seed, record in sorted(
            missing_at_dose.items(), key=lambda item: int(item[0])
        ):
            lines.append(
                f"    seed {seed}: {record.get('status')} "
                f"({record.get('exclusion_reason') or 'dose_not_completed'}); "
                f"available doses {record.get('doses', [])}; stages "
                f"{record.get('stage_statuses', {})}"
            )
    nonterminal_at_dose = {
        seed: record
        for seed, record in result.get("run_inventory", {}).items()
        if result["dose"] in record.get("doses", [])
        and record.get("status") != "COMPLETE"
    }
    if nonterminal_at_dose:
        lines.append("  numeric row comes from a nonterminal program:")
        for seed, record in sorted(
            nonterminal_at_dose.items(), key=lambda item: int(item[0])
        ):
            lines.append(
                f"    seed {seed}: {record.get('status')}; available doses "
                f"{record.get('doses', [])}; stages "
                f"{record.get('stage_statuses', {})}"
            )
    lines.append("")
    for entry in result["objectives"].values():
        lines.append(f"  {entry['label']}")
        for measure, data in entry["measures"].items():
            sign = data["sign"]
            mark = "unanimous" if sign["unanimous"] else (
                f"{max(sign['positive'], sign['negative'])}/{sign['n']}")
            p = (f", p={sign['p_if_unanimous']:.4f}"
                 if sign["p_if_unanimous"] else "")
            varied = data["decomposition"]["varied_curriculum"]
            spread = (f"  varied sd {varied['sd']:.4f} (df {varied['df']})"
                      if varied["sd"] is not None else "")
            lines.append(f"    {measure:18s} {mark}{p}{spread}")
        lines.append("")
    lines.append("  contrasts")
    for name, data in result["contrasts"].items():
        sign = data["sign"]
        mark = "unanimous" if sign["unanimous"] else (
            f"{max(sign['positive'], sign['negative'])}/{sign['n']}")
        p = f", p={sign['p_if_unanimous']:.4f}" if sign["p_if_unanimous"] else ""
        lines.append(f"    {name:52s} {mark}{p}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge", type=pathlib.Path,
                        default=root / "data" / "processed"
                        / "seed_replication_knowledge.csv")
    parser.add_argument("--manifest", type=pathlib.Path,
                        default=root / "data" / "processed"
                        / "seed_replication_manifest.json")
    parser.add_argument("--dose", type=int, default=125)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    rows = load(args.knowledge)
    floor = None
    run_inventory = None
    if args.manifest.exists():
        manifest = json.loads(args.manifest.read_text())
        floor = manifest.get("noise_floor")
        run_inventory = manifest.get("replication_runs")
    result = report(
        rows, dose=args.dose, floor=floor, run_inventory=run_inventory
    )
    print(render(result))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
