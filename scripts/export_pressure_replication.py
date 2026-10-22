#!/usr/bin/env python3
"""Export the larger matched social-pressure replication for the brief.

The raw run is intentionally gitignored because it contains every conversation.
This script reduces its frozen summary to two committed tables: absolute levels
by reward and dose, and matched confidence-versus-accuracy contrasts by seed.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get(
    "BELOWZERO_PRESSURE_REPLICATION_SUMMARY",
    ROOT / "runs" / "finetune" / "alignment_pressure_replication_v1" / "summary.json",
))
LEVELS_OUT = ROOT / "data" / "processed" / "alignment_pressure_replication.csv"
CONTRASTS_OUT = ROOT / "data" / "processed" / "alignment_pressure_contrasts.csv"

REWARD_LABELS = {
    "base": "Untuned base",
    "binary": "Accuracy only",
    "quadratic": "Confidence-calibrated",
    "quad_cost": "Confidence-calibrated + fixed cost",
}


def read_checkpoint_rows(source: Path = SOURCE) -> list[dict[str, object]]:
    """Pair the right and wrong arms for every saved checkpoint."""
    payload = json.loads(source.read_text(encoding="utf-8"))
    arms: dict[str, dict[str, dict[str, object]]] = {}
    for identity, row in payload["by_checkpoint_arm"].items():
        checkpoint, arm = identity.rsplit("|", 1)
        arms.setdefault(checkpoint, {})[arm] = row

    paired = []
    for checkpoint, checkpoint_arms in arms.items():
        if set(checkpoint_arms) != {"right", "wrong"}:
            raise ValueError(f"{checkpoint} does not have both pressure arms")
        wrong, right = checkpoint_arms["wrong"], checkpoint_arms["right"]
        for field in ("reward_rule", "step", "seed"):
            if wrong[field] != right[field]:
                raise ValueError(f"{checkpoint} arms disagree on {field}")
        if wrong["second_turn_invalid_rate"] != 0 or right["second_turn_invalid_rate"] != 0:
            raise ValueError(f"{checkpoint} contains invalid second-turn responses")
        wrong_rate = float(wrong["adoption_rate"])
        right_rate = float(right["adoption_rate"])
        paired.append({
            "checkpoint": checkpoint,
            "reward": str(wrong["reward_rule"]),
            "step": int(wrong["step"]),
            "seed": "" if wrong["seed"] is None else str(wrong["seed"]),
            "wrong_n": int(wrong["n"]),
            "right_n": int(right["n"]),
            "wrong_adoption": wrong_rate,
            "right_adoption": right_rate,
            "pressure_discernment": right_rate - wrong_rate,
        })
    return paired


def mean(rows: list[dict[str, object]], field: str) -> float:
    return sum(float(row[field]) for row in rows) / len(rows)


def build_levels(checkpoints: list[dict[str, object]]) -> list[dict[str, str]]:
    """Average seeds equally so one seed cannot dominate through item count."""
    groups: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in checkpoints:
        groups.setdefault((str(row["reward"]), int(row["step"])), []).append(row)

    output = []
    reward_order = {name: index for index, name in enumerate(REWARD_LABELS)}
    for (reward, step), rows in sorted(
        groups.items(), key=lambda pair: (reward_order[pair[0][0]], pair[0][1])
    ):
        expected_seeds = {""} if reward == "base" else {"0", "1"}
        if {str(row["seed"]) for row in rows} != expected_seeds:
            raise ValueError(f"{reward}@{step} does not contain the frozen seeds")
        output.append({
            "reward": reward,
            "reward_label": REWARD_LABELS[reward],
            "step": str(step),
            "n_seeds": str(len(rows)),
            "wrong_items": str(sum(int(row["wrong_n"]) for row in rows)),
            "right_items": str(sum(int(row["right_n"]) for row in rows)),
            "accepts_wrong_pushback": f'{mean(rows, "wrong_adoption"):.6f}',
            "accepts_right_pushback": f'{mean(rows, "right_adoption"):.6f}',
            "pressure_discernment": f'{mean(rows, "pressure_discernment"):.6f}',
        })
    return output


def build_contrasts(checkpoints: list[dict[str, object]]) -> list[dict[str, str]]:
    """Compare quadratic and accuracy objectives at the same seed and dose."""
    keyed = {
        (str(row["reward"]), int(row["step"]), str(row["seed"])): row
        for row in checkpoints
    }
    output = []
    for step in (50, 100, 125):
        for seed in ("0", "1"):
            treatment = keyed[("quadratic", step, seed)]
            control = keyed[("binary", step, seed)]
            output.append({
                "step": str(step),
                "seed": seed,
                "delta_wrong_adoption": f'{float(treatment["wrong_adoption"]) - float(control["wrong_adoption"]):.6f}',
                "delta_right_adoption": f'{float(treatment["right_adoption"]) - float(control["right_adoption"]):.6f}',
                "delta_pressure_discernment": f'{float(treatment["pressure_discernment"]) - float(control["pressure_discernment"]):.6f}',
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
    checkpoints = read_checkpoint_rows()
    levels = build_levels(checkpoints)
    contrasts = build_contrasts(checkpoints)
    write_csv(LEVELS_OUT, levels)
    write_csv(CONTRASTS_OUT, contrasts)
    print(
        f"wrote {len(levels)} levels and {len(contrasts)} matched contrasts "
        f"from {len(checkpoints)} checkpoints"
    )


if __name__ == "__main__":
    main()
