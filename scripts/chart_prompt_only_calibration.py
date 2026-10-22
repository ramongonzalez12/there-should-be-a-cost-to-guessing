#!/usr/bin/env python3
"""Draw the matched prompt-only reliability chart for the report.

The upper panel answers the reader's concrete question: when a model reported a
given confidence, how often was it correct? The lower panel shows how many
responses support each point. Sparse bins are omitted rather than encoded with a
second, confusing hollow-marker grammar.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

COLORS = {
    "control": "#8A8A86",
    "quad_score_only": "#7C2F55",
    "grid": "#E6E3DE",
    "text": "#222222",
    "muted": "#686866",
}
LABELS = {
    "control": "Answer normally",
    "quad_score_only": "Score explained",
}


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data", type=Path,
        default=Path("data/processed/prompt_only_calibration_reliability_bins.csv"),
    )
    parser.add_argument(
        "--summary", type=Path,
        default=Path("data/processed/prompt_only_calibration_summary.json"),
    )
    parser.add_argument(
        "--out", type=Path,
        default=Path("results/prompt_only_calibration_reliability.png"),
    )
    parser.add_argument("--minimum-bin", type=int, default=50)
    args = parser.parse_args()

    rows = load_csv(args.data)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    arm_estimates = {row["arm"]: row for row in summary["arm_estimates"]}
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.edgecolor": COLORS["muted"],
        "axes.labelcolor": COLORS["text"],
        "xtick.color": COLORS["muted"],
        "ytick.color": COLORS["muted"],
    })
    figure = plt.figure(figsize=(8.8, 6.5), facecolor="white")
    grid = figure.add_gridspec(2, 1, height_ratios=[3.7, 1.15], hspace=0.12)
    reliability = figure.add_subplot(grid[0])
    counts = figure.add_subplot(grid[1], sharex=reliability)

    reliability.plot([0, 1], [0, 1], color="#AAA69E", linewidth=1.2,
                     linestyle=(0, (4, 4)), zorder=1)
    reliability.text(0.03, 0.95, "Below the line = overconfident",
                     transform=reliability.transAxes, color=COLORS["muted"],
                     fontsize=9, va="top")

    by_arm = {arm: [] for arm in LABELS}
    omitted = {arm: [0, 0] for arm in LABELS}
    for row in rows:
        arm = row["arm"]
        count = int(row["responses"])
        if count < args.minimum_bin:
            omitted[arm][0] += count
            omitted[arm][1] += 1
            continue
        by_arm[arm].append({
            "x": float(row["mean_stated_confidence"]),
            "y": float(row["accuracy"]),
            "n": count,
            "bin": float(row["confidence_bin"]),
        })

    for arm in ("control", "quad_score_only"):
        points = sorted(by_arm[arm], key=lambda row: row["x"])
        # Connect only adjacent ten-point bins. Bridging an omitted sparse bin
        # would imply evidence about the shape of a curve where none exists.
        segment: list[dict] = []
        for point in points:
            if segment and point["bin"] - segment[-1]["bin"] > 0.1001:
                reliability.plot(
                    [row["x"] for row in segment], [row["y"] for row in segment],
                    color=COLORS[arm], linewidth=2.25, zorder=2,
                )
                segment = []
            segment.append(point)
        if len(segment) > 1:
            reliability.plot(
                [row["x"] for row in segment], [row["y"] for row in segment],
                color=COLORS[arm], linewidth=2.25, zorder=2,
            )
        reliability.scatter(
            [row["x"] for row in points], [row["y"] for row in points],
            color=COLORS[arm], s=45, edgecolors="none", label=LABELS[arm], zorder=3,
        )

    zero_treatment = next(
        (row for row in by_arm["quad_score_only"] if row["bin"] == 0.0), None
    )
    if zero_treatment:
        reliability.annotate(
            f"{zero_treatment['n']:,} near-zero reports\n"
            f"{zero_treatment['y'] * 100:.0f}% were correct",
            xy=(zero_treatment["x"], zero_treatment["y"]), xytext=(0.12, 0.90),
            textcoords="axes fraction", ha="left", va="top", fontsize=9,
            color=COLORS["text"],
            arrowprops={"arrowstyle": "-", "color": COLORS["quad_score_only"],
                        "linewidth": 1.1},
        )

    reliability.set_xlim(0, 1)
    reliability.set_ylim(0, 1)
    reliability.set_ylabel("Accuracy on those responses", fontweight="semibold")
    reliability.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    reliability.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    reliability.grid(True, color=COLORS["grid"], linewidth=0.8)
    reliability.spines[["top", "right"]].set_visible(False)
    reliability.tick_params(axis="x", labelbottom=False)
    reliability.legend(frameon=False, loc="lower right", fontsize=10)

    all_bins = sorted({float(row["confidence_bin"]) for row in rows})
    width = 0.032
    for offset, arm in ((-width / 2, "control"), (width / 2, "quad_score_only")):
        lookup = {
            float(row["confidence_bin"]): int(row["responses"])
            for row in rows if row["arm"] == arm
        }
        counts.bar(
            [value + offset for value in all_bins],
            [lookup.get(value, 0) for value in all_bins],
            width=width, color=COLORS[arm], alpha=0.88,
        )
    counts.set_ylabel("Responses", fontweight="semibold")
    counts.set_xlabel("Stated confidence", fontweight="semibold")
    counts.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    counts.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    counts.spines[["top", "right"]].set_visible(False)

    control = arm_estimates["control"]
    treatment = arm_estimates["quad_score_only"]
    figure.suptitle(
        "Explaining the score lowered confidence, not calibration error",
        x=0.105, y=0.98, ha="left", fontsize=16, fontweight="bold",
        color=COLORS["text"],
    )
    figure.text(
        0.105, 0.935,
        f"Accuracy  {control['accuracy'] * 100:.0f}% to {treatment['accuracy'] * 100:.0f}%    |    "
        f"Confidence  {control['confidence'] * 100:.0f}% to {treatment['confidence'] * 100:.0f}%    |    "
        f"Overconfidence gap  {control['confidence_gap'] * 100:.0f} to {treatment['confidence_gap'] * 100:.0f} points",
        ha="left", fontsize=9.5, color=COLORS["muted"],
    )
    figure.text(
        0.105, 0.907,
        f"Mean absolute cell gap  {control['mean_absolute_confidence_gap'] * 100:.0f} to "
        f"{treatment['mean_absolute_confidence_gap'] * 100:.0f} points    |    "
        f"Confidence-calibrated score  {control['calibrated_score'] * 100:.0f} to "
        f"{treatment['calibrated_score'] * 100:.0f}",
        ha="left", fontsize=10, color=COLORS["muted"],
    )
    omitted_total = sum(value[0] for value in omitted.values())
    omitted_bins = sum(value[1] for value in omitted.values())
    figure.text(
        0.105, 0.012,
        f"Each point is one 10-point confidence bin. Bins with fewer than "
        f"{args.minimum_bin} responses are omitted ({omitted_total:,} responses "
        f"across {omitted_bins} bins).\nBars show the distribution of reports; "
        f"most usable confidence reports were in the 100% bin.",
        ha="left", fontsize=8.5, color=COLORS["muted"],
    )
    figure.subplots_adjust(left=0.105, right=0.97, top=0.87, bottom=0.15)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.out, dpi=220, facecolor="white")
    plt.close(figure)
    print(args.out)


if __name__ == "__main__":
    main()
