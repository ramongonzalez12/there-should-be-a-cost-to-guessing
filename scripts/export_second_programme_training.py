#!/usr/bin/env python3
"""Export the second training programme's trajectories and decision battery.

WHY THIS EXISTS
---------------
The second programme (2026-09-12) is the first time all three families have
per-step checkpoints and the decision battery under one recipe. The two
exporters that carried those exhibits before were built around one family:
`export_seed_dense_knowledge.py` keys its sources by Qwen seed and parses the
seed out of the arm label, and `export_cross_family_completion.py` hard-codes
a two-family tuple. Reshaping either would change files the notes page keeps
for the first programme, so the second programme gets its own tables with a
`family` column, computed with the same metric definitions:

  data/processed/second_programme_trajectories.csv
      family, seed, objective, step, n, accuracy, coverage, abstention_rate,
      invalid_rate, mean_probability, overconfidence,
      confidence_adjusted_accuracy, high_confidence_error_90_rate
      (one row per family x seed x reward x step from
      runs/finetune/second_programme_v1/<family>/eval_trajectory/responses.jsonl,
      plus one `base` row per family at step 0; metrics as in
      export_seed_dense_knowledge.py: coverage and overconfidence among
      genuine answers, the score and the 90%+ tail over every item)
  data/processed/second_programme_prudence_levels.csv
  data/processed/second_programme_prudence_contrasts.csv
      model_family + the columns export_plural_prudence.py writes, from
      runs/finetune/second_programme_v1/<family>/eval_prudence/summary.json
  data/processed/second_programme_training_manifest.json

A family whose evaluation is absent is skipped with a message; when every
family is absent nothing is written, so a checkout without runs/ keeps the
committed tables. Standard library only. Free.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PROGRAMME = ROOT / "runs" / "finetune" / "second_programme_v1"
DP = ROOT / "data" / "processed"

FAMILIES = (("qwen", "Qwen3 8B"), ("gpt_oss", "GPT-OSS 20B"),
            ("nemotron", "Nemotron 3 Nano 30B"))
REWARDS = ("binary", "quadratic")

TRAJECTORY_FIELDS = ("family", "seed", "objective", "step", "n", "accuracy", "coverage",
                     "abstention_rate", "invalid_rate", "mean_probability", "overconfidence",
                     "confidence_adjusted_accuracy", "high_confidence_error_90_rate")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def cell_metrics(rs: list[dict]) -> dict:
    """The dense-track definitions, copied from export_seed_dense_knowledge.py
    so the two trajectory files can never disagree on a denominator."""
    n = len(rs)
    answered = [r for r in rs if not r["abstained"] and r["formatted"]
                and r["probability"] is not None]
    correct = sum(1 for r in answered if r["correct"])
    mean_p = (sum(r["probability"] for r in answered) / len(answered)
              if answered else float("nan"))
    over = mean_p - (correct / len(answered)) if answered else float("nan")
    return {
        "n": n,
        "accuracy": round(correct / n, 4),
        "coverage": round(len(answered) / n, 4),
        "abstention_rate": round(sum(1 for r in rs if r["abstained"]) / n, 4),
        "invalid_rate": round(sum(1 for r in rs if not r["formatted"]) / n, 4),
        "mean_probability": round(mean_p, 4),
        "overconfidence": round(over, 4),
        "confidence_adjusted_accuracy": round(
            sum(float(r["scores"]["quadratic"]) for r in rs) / n, 4),
        "high_confidence_error_90_rate": round(sum(
            r["outcome"] == "INCORRECT" and r.get("probability") is not None
            and float(r["probability"]) >= 0.9 for r in rs) / n, 4),
    }


def _complete(status_file: Path) -> bool:
    """An evaluation counts only when its own record says COMPLETE. The
    responses file exists from the first row written, so its presence is not
    readiness; a half-written run would export as a plausible partial table."""
    if not status_file.exists():
        return False
    try:
        return json.loads(status_file.read_text(encoding="utf-8")).get("status") in ("COMPLETE", "COMPLETED")
    except (OSError, ValueError):
        return False


def trajectories() -> tuple[list[dict], list[Path]]:
    rows: list[dict] = []
    sources: list[Path] = []
    for key, family in FAMILIES:
        path = PROGRAMME / key / "eval_trajectory" / "responses.jsonl"
        if not _complete(PROGRAMME / key / "eval_trajectory" / "evaluation.json"):
            print(f"{family}: trajectory evaluation absent or not complete, skipped")
            continue
        sources.append(path)
        cells: dict[tuple, list[dict]] = defaultdict(list)
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            arm = r["arm"]
            if arm == "base":
                cells[("", "base", 0)].append(r)
            elif arm in REWARDS:
                # One file holds every seed; the seed is a field, never
                # parsed out of the label.
                cells[(int(r["training_seed"]), arm, int(r["dose"]))].append(r)
        for (seed, objective, step), rs in sorted(cells.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])):
            rows.append({"family": family, "seed": seed, "objective": objective,
                         "step": step, **cell_metrics(rs)})
    return rows, sources


def prudence() -> tuple[list[dict], list[dict], list[Path], tuple, tuple]:
    """Levels and within-seed training contrasts, the same rows
    export_plural_prudence.py writes, but over whichever framings the run
    holds: the second programme ran the neutral framing only, and that
    exporter's contrast loop assumes all four."""
    from export_plural_prudence import (
        CONTRAST_FIELDS,
        LEVEL_FIELDS,
        METRIC_FIELDS,
        _delta,
        _flatten,
    )
    levels: list[dict] = []
    contrasts: list[dict] = []
    sources: list[Path] = []
    for key, family in FAMILIES:
        path = PROGRAMME / key / "eval_prudence" / "summary.json"
        if not _complete(PROGRAMME / key / "eval_prudence" / "manifest.json"):
            print(f"{family}: decision-battery evaluation absent or not complete, skipped")
            continue
        sources.append(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        family_levels = [_flatten(cell) for cell in payload["by_cell"].values()]
        family_levels.sort(key=lambda row: (row["training_seed"] == "", str(row["training_seed"]),
                                            str(row["training_objective"]), str(row["framing"])))
        by_identity = {(str(r["training_objective"]), str(r["training_seed"]), str(r["framing"])): r
                       for r in family_levels}
        framings = sorted({str(r["framing"]) for r in family_levels})
        seeds = sorted({seed for obj, seed, _ in by_identity if obj == "binary" and seed}, key=int)
        for seed in seeds:
            for framing in framings:
                if ("binary", seed, framing) not in by_identity or ("quadratic", seed, framing) not in by_identity:
                    continue
                control = by_identity[("binary", seed, framing)]
                treatment = by_identity[("quadratic", seed, framing)]
                row = {"training_seed": seed, "framing": framing,
                       "treatment_objective": "quadratic", "control_objective": "binary"}
                row.update({f"{field}_change": _delta(control[field], treatment[field])
                            for field in METRIC_FIELDS})
                contrasts.append({"model_family": family, **row})
        levels.extend({"model_family": family, **row} for row in family_levels)
    return levels, contrasts, sources, LEVEL_FIELDS, CONTRAST_FIELDS


def main() -> int:
    traj_rows, traj_sources = trajectories()
    prud_levels, prud_contrasts, prud_sources, level_fields, contrast_fields = prudence()
    if not traj_sources and not prud_sources:
        print("second programme: no evaluations present; nothing written")
        return 0
    outputs = []
    if traj_rows:
        out = DP / "second_programme_trajectories.csv"
        _write(out, TRAJECTORY_FIELDS, traj_rows)
        outputs.append(str(out.relative_to(ROOT)))
        print(f"wrote {out.name}: {len(traj_rows)} rows, "
              f"{len({r['family'] for r in traj_rows})} families")
    if prud_levels:
        out = DP / "second_programme_prudence_levels.csv"
        _write(out, ("model_family",) + tuple(level_fields), prud_levels)
        outputs.append(str(out.relative_to(ROOT)))
        out2 = DP / "second_programme_prudence_contrasts.csv"
        _write(out2, ("model_family",) + tuple(contrast_fields), prud_contrasts)
        outputs.append(str(out2.relative_to(ROOT)))
        print(f"wrote {out.name}: {len(prud_levels)} level rows, "
              f"{len(prud_contrasts)} contrasts")
    manifest = {
        "created_by": "scripts/export_second_programme_training.py",
        "sources": {str(p.relative_to(ROOT)): _sha256(p) for p in traj_sources + prud_sources},
        "outputs": outputs,
    }
    (DP / "second_programme_training_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
