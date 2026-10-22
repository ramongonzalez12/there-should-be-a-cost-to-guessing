#!/usr/bin/env python3
"""Export the crossed training-by-prompt social-pressure experiment.

Each raw summary contains paired wrong- and correct-pushback arms.  The export
keeps both because wrong-pushback resistance alone rewards indiscriminate
stubbornness.  Seeds are averaged equally before any training contrast is
computed, so a small difference in usable item counts cannot reweight a seed.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path(os.environ.get(
    "BELOWZERO_PRESSURE_PROMPT_RUN_ROOT", ROOT / "runs" / "finetune"
))
SOURCES = {
    "neutral": RUN_ROOT / "alignment_pressure_replication_v1" / "summary.json",
    "binary": RUN_ROOT / "alignment_pressure_prompt_binary_v1" / "summary.json",
    "quadratic": RUN_ROOT / "alignment_pressure_prompt_quadratic_v1" / "summary.json",
    "quad_cost": RUN_ROOT / "alignment_pressure_prompt_quad_cost_v1" / "summary.json",
}
LEVELS_OUT = ROOT / "data" / "processed" / "alignment_pressure_prompting.csv"
CONTRASTS_OUT = (
    ROOT / "data" / "processed" / "alignment_pressure_prompt_contrasts.csv"
)
SPEND_OUT = ROOT / "data" / "processed" / "alignment_pressure_spend.csv"

SPEND_RUNS = [
    "alignment_pressure_pilot_v1",
    "alignment_pressure_replication_v1",
    "alignment_pressure_prompt_binary_pilot_v1",
    "alignment_pressure_prompt_quadratic_pilot_v1",
    "alignment_pressure_prompt_quad_cost_pilot_v1",
    "alignment_pressure_prompt_binary_v1",
    "alignment_pressure_prompt_quadratic_v1",
    "alignment_pressure_prompt_quad_cost_v1",
]

REWARD_LABELS = {
    "base": "Untuned base",
    "binary": "Accuracy only",
    "quadratic": "Confidence-calibrated",
    "quad_cost": "Confidence-calibrated + fixed cost",
}
PROMPT_LABELS = {
    "neutral": "No scoring rule announced",
    "binary": "Accuracy scoring announced",
    "quadratic": "Confidence scoring announced",
    "quad_cost": "Confidence scoring + fixed cost announced",
}


def read_condition(condition: str, source: Path) -> list[dict[str, object]]:
    """Return paired step-125 checkpoint rows from one prompt condition."""
    payload = json.loads(source.read_text(encoding="utf-8"))
    arms: dict[str, dict[str, dict[str, object]]] = {}
    for identity, row in payload["by_checkpoint_arm"].items():
        checkpoint, arm = identity.rsplit("|", 1)
        if row["reward_rule"] != "base" and int(row["step"]) != 125:
            continue
        arms.setdefault(checkpoint, {})[arm] = row

    expected = {"base": 1, "binary": 2, "quadratic": 2, "quad_cost": 2}
    observed = {reward: 0 for reward in expected}
    paired = []
    for checkpoint, checkpoint_arms in arms.items():
        if set(checkpoint_arms) != {"right", "wrong"}:
            raise ValueError(f"{condition}/{checkpoint} lacks a pressure arm")
        wrong, right = checkpoint_arms["wrong"], checkpoint_arms["right"]
        for field in ("reward_rule", "step", "seed"):
            if wrong[field] != right[field]:
                raise ValueError(f"{condition}/{checkpoint} arms disagree on {field}")
        if wrong["second_turn_invalid_rate"] != 0 or right["second_turn_invalid_rate"] != 0:
            raise ValueError(f"{condition}/{checkpoint} has invalid second turns")

        reward = str(wrong["reward_rule"])
        if reward not in expected:
            raise ValueError(f"unexpected reward {reward}")
        observed[reward] += 1
        wrong_rate = float(wrong["adoption_rate"])
        right_rate = float(right["adoption_rate"])
        paired.append({
            "condition": condition,
            "reward": reward,
            "seed": "" if wrong["seed"] is None else str(wrong["seed"]),
            "wrong_n": int(wrong["n"]),
            "right_n": int(right["n"]),
            "wrong_adoption": wrong_rate,
            "right_adoption": right_rate,
            "pressure_discernment": right_rate - wrong_rate,
        })
    if observed != expected:
        raise ValueError(f"{condition} checkpoint counts {observed}, expected {expected}")
    return paired


def mean(records: list[dict[str, object]], field: str) -> float:
    return sum(float(record[field]) for record in records) / len(records)


def build_levels(records: list[dict[str, object]]) -> list[dict[str, str]]:
    """Aggregate the frozen base and two seeds for every crossed condition."""
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for record in records:
        groups.setdefault(
            (str(record["condition"]), str(record["reward"])), []
        ).append(record)

    output = []
    for condition, prompt_label in PROMPT_LABELS.items():
        for reward, reward_label in REWARD_LABELS.items():
            selected = groups[(condition, reward)]
            expected_seeds = {""} if reward == "base" else {"0", "1"}
            if {str(record["seed"]) for record in selected} != expected_seeds:
                raise ValueError(f"{condition}/{reward} has the wrong seeds")
            output.append({
                "prompt_condition": condition,
                "prompt_label": prompt_label,
                "reward": reward,
                "reward_label": reward_label,
                "n_seeds": str(len(selected)),
                "wrong_items": str(sum(int(record["wrong_n"]) for record in selected)),
                "right_items": str(sum(int(record["right_n"]) for record in selected)),
                "wrong_adoption": f'{mean(selected, "wrong_adoption"):.6f}',
                "right_adoption": f'{mean(selected, "right_adoption"):.6f}',
                "pressure_discernment": f'{mean(selected, "pressure_discernment"):.6f}',
            })
    return output


def build_contrasts(levels: list[dict[str, str]]) -> list[dict[str, str]]:
    """Compare confidence-calibrated with accuracy training under each prompt."""
    indexed = {
        (row["prompt_condition"], row["reward"]): row for row in levels
    }
    output = []
    for condition, prompt_label in PROMPT_LABELS.items():
        treatment = indexed[(condition, "quadratic")]
        control = indexed[(condition, "binary")]
        output.append({
            "prompt_condition": condition,
            "prompt_label": prompt_label,
            "delta_wrong_adoption": f'{float(treatment["wrong_adoption"]) - float(control["wrong_adoption"]):.6f}',
            "delta_right_adoption": f'{float(treatment["right_adoption"]) - float(control["right_adoption"]):.6f}',
            "delta_pressure_discernment": f'{float(treatment["pressure_discernment"]) - float(control["pressure_discernment"]):.6f}',
        })
    return output


def build_spend(run_root: Path = RUN_ROOT) -> list[dict[str, str]]:
    """Read every capped ledger so the published total cannot drift."""
    output = []
    for run in SPEND_RUNS:
        source = run_root / run / "spend.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload["status"] != "COMPLETE":
            raise ValueError(f"{run} is not complete")
        spent = float(payload["spent_usd"])
        cap = float(payload["cap_usd"])
        if spent > cap:
            raise ValueError(f"{run} exceeded its cap")
        output.append({
            "run": run,
            "scope": "pilot" if "pilot" in run else "full",
            "cap_usd": f"{cap:.6f}",
            "conservative_spend_usd": f"{spent:.6f}",
            "rows": str(payload["rows"]),
            "status": str(payload["status"]),
        })
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    records = []
    for condition, source in SOURCES.items():
        records.extend(read_condition(condition, source))
    levels = build_levels(records)
    contrasts = build_contrasts(levels)
    spend = build_spend()
    write_csv(LEVELS_OUT, levels)
    write_csv(CONTRASTS_OUT, contrasts)
    write_csv(SPEND_OUT, spend)
    print(
        f"wrote {len(levels)} crossed levels, {len(contrasts)} prompt contrasts, "
        f"and {len(spend)} spend ledgers"
    )


if __name__ == "__main__":
    main()
