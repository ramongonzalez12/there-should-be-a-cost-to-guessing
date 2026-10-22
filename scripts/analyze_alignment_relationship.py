#!/usr/bin/env python3
"""Test whether better confidence calibration tracks alignment indicators.

The dose grid contains 100 fine-tuned checkpoints: five training objectives at
20 saved steps.  Every checkpoint saw the same knowledge, constraint, and
social-pressure evaluations.  This script joins those committed outputs and
asks a deliberately narrow question: within a training objective, do
checkpoints with a higher confidence-calibrated score also behave better on
the alignment-adjacent checks?

The output is descriptive.  Checkpoints along one training trajectory are not
independent model replications, so the correlations should not be treated as
confidence intervals or causal estimates.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
OUTPUT = PROCESSED / "alignment_relationship.csv"

OBJECTIVES = ("binary", "quadratic", "quad_cost_0.04", "quad_cost_0.09", "quad_cost_0.16")
EXPECTED_STEPS = tuple(range(25, 501, 25))


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV as dictionaries so column names remain explicit."""
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def average_ranks(values: Iterable[float]) -> list[float]:
    """Return one-based ranks, assigning tied values their average rank."""
    values = list(values)
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2
        for index in order[start:end]:
            ranks[index] = average
        start = end
    return ranks


def pearson(xs: Iterable[float], ys: Iterable[float]) -> float:
    """Compute a Pearson correlation and fail on a constant input."""
    xs, ys = list(xs), list(ys)
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("correlation inputs must have the same length >= 2")
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_delta = [value - x_mean for value in xs]
    y_delta = [value - y_mean for value in ys]
    denominator = math.sqrt(
        sum(value * value for value in x_delta)
        * sum(value * value for value in y_delta)
    )
    if denominator == 0:
        raise ValueError("correlation is undefined for a constant input")
    return sum(x * y for x, y in zip(x_delta, y_delta)) / denominator


def spearman(xs: Iterable[float], ys: Iterable[float]) -> float:
    """Compute Spearman's rank correlation with average ranks for ties."""
    return pearson(average_ranks(xs), average_ranks(ys))


def checkpoint_key(row: dict[str, str]) -> tuple[str, int]:
    """Use training objective and saved step as the cross-file identity."""
    return row["objective"], int(row["step"])


def validate_grid(keys: set[tuple[str, int]], label: str) -> None:
    """Require the complete frozen 5-by-20 grid before reporting a result."""
    expected = {(objective, step) for objective in OBJECTIVES for step in EXPECTED_STEPS}
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise ValueError(f"{label} grid mismatch; missing={missing}, extra={extra}")


def build_checkpoint_rows(processed: Path = PROCESSED) -> list[dict[str, float | int | str]]:
    """Join calibration and alignment outcomes for all 100 checkpoints."""
    knowledge_rows = [
        row for row in read_rows(processed / "dose_grid_knowledge.csv")
        if row["objective"] != "base"
    ]
    behaviour_rows = [
        row for row in read_rows(processed / "dose_grid_behaviour.csv")
        if row["objective"] != "base"
    ]
    pressure_rows = read_rows(processed / "dose_grid_sycophancy.csv")

    knowledge = {checkpoint_key(row): row for row in knowledge_rows}
    behaviour = {checkpoint_key(row): row for row in behaviour_rows}
    pressure: dict[tuple[str, int], dict[str, dict[str, str]]] = {}
    for row in pressure_rows:
        pressure.setdefault(checkpoint_key(row), {})[row["pressure_arm"]] = row

    validate_grid(set(knowledge), "knowledge")
    validate_grid(set(behaviour), "behaviour")
    validate_grid(set(pressure), "social-pressure")
    if any(set(arms) != {"right", "wrong"} for arms in pressure.values()):
        raise ValueError("every checkpoint must have right and wrong pushback arms")

    joined = []
    for objective in OBJECTIVES:
        for step in EXPECTED_STEPS:
            key = objective, step
            wrong_adoption = float(pressure[key]["wrong"]["adoption_rate"])
            right_adoption = float(pressure[key]["right"]["adoption_rate"])
            joined.append({
                "objective": objective,
                "step": step,
                "confidence_calibrated_score": float(knowledge[key]["score_quadratic"]),
                "constraint_adherence": 1 - float(behaviour[key]["violation_rate"]),
                "resists_wrong_pushback": 1 - wrong_adoption,
                "appropriate_updating": right_adoption,
                # This paired endpoint rewards accepting good corrections and
                # resisting bad ones.  Wrong-pushback resistance alone would
                # mistake indiscriminate stubbornness for alignment.
                "pressure_discernment": right_adoption - wrong_adoption,
            })
    return joined


INDICATORS = (
    ("constraint_adherence", "Constraint adherence"),
    ("resists_wrong_pushback", "Resistance to wrong pushback"),
    ("appropriate_updating", "Appropriate updating"),
    ("pressure_discernment", "Pressure discernment"),
)


def summarize(checkpoints: list[dict[str, float | int | str]]) -> list[dict[str, str]]:
    """Summarize levels and associations without treating rows as independent."""
    output = []
    calibration = [float(row["confidence_calibrated_score"]) for row in checkpoints]

    for field, label in INDICATORS:
        values = [float(row[field]) for row in checkpoints]
        objective_rhos: dict[str, float | None] = {}
        pooled_calibration_ranks: list[float] = []
        pooled_indicator_ranks: list[float] = []
        lower_quartile: list[float] = []
        upper_quartile: list[float] = []

        for objective in OBJECTIVES:
            group = [row for row in checkpoints if row["objective"] == objective]
            group_calibration = [float(row["confidence_calibrated_score"]) for row in group]
            group_values = [float(row[field]) for row in group]
            # A blank is more honest than zero when an indicator never changes
            # within an objective and its correlation is therefore undefined.
            try:
                objective_rhos[objective] = spearman(group_calibration, group_values)
            except ValueError:
                objective_rhos[objective] = None
            pooled_calibration_ranks.extend(average_ranks(group_calibration))
            pooled_indicator_ranks.extend(average_ranks(group_values))

            # Quartiles are selected separately inside each training objective.
            # This compares checkpoint dose, not objectives with different
            # baseline behavior.  Twenty checkpoints means five per quartile.
            ordered = sorted(group, key=lambda row: float(row["confidence_calibrated_score"]))
            lower_quartile.extend(float(row[field]) for row in ordered[:5])
            upper_quartile.extend(float(row[field]) for row in ordered[-5:])

        lower_mean = sum(lower_quartile) / len(lower_quartile)
        upper_mean = sum(upper_quartile) / len(upper_quartile)
        output.append({
            "indicator": label,
            "n_checkpoints": str(len(checkpoints)),
            "all_checkpoint_spearman": f"{spearman(calibration, values):.6f}",
            "within_objective_rank_correlation": f"{pearson(pooled_calibration_ranks, pooled_indicator_ranks):.6f}",
            "lower_calibration_quartile_mean": f"{lower_mean:.6f}",
            "upper_calibration_quartile_mean": f"{upper_mean:.6f}",
            "quartile_change": f"{upper_mean - lower_mean:.6f}",
            **{f"{objective}_spearman": (
                   "" if objective_rhos[objective] is None
                   else f"{objective_rhos[objective]:.6f}"
               )
               for objective in OBJECTIVES},
        })
    return output


def write_summary(rows: list[dict[str, str]], output: Path = OUTPUT) -> None:
    """Persist the audit table beside the committed experiment summaries."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = summarize(build_checkpoint_rows())
    write_summary(rows)
    print(f"wrote {len(rows)} indicators from 100 checkpoints to {OUTPUT}")


if __name__ == "__main__":
    main()
