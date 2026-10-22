#!/usr/bin/env python3
"""Export the coverage table: one row per evidence block, its universe stated once.

WHY THIS EXISTS
---------------
The essay's evidence blocks drifted apart as the programme grew: 42 models
for the measurement, 32 for the rule prompt, 31 for the warning, 13 for the
same-run study, five, four and three seed pairs for the three fine-tuned
families. None of those numbers was wrong; together they were a distraction,
and every one cost a caveat sentence. The 2026-09-12 coverage-equalisation
plan states each block's universe ONCE, on the notes page, in a table that is
generated from the same files the exhibits read, so the table can never say
one thing while an exhibit says another.

Rows come from:
  data/processed/battery_cohort.csv                the prompt-side registry
  data/processed/pooled_training_levels.csv        matched seed pairs per family
  data/processed/training_common_battery_contrasts.csv  pairs on the shared battery
  data/processed/openweight_plural_prudence_levels.csv  decision-battery checkpoints
  data/processed/seed_dense_knowledge.csv          trajectory seeds (dense track)
  data/processed/training_effect_synthesis.csv     the first programme's pairs

Output: data/processed/coverage_universes.csv with columns
  block, universe, models_or_families, benchmarks_or_batteries, arms_or_rewards,
  items, seeds_or_pairs, recipe, reads_on, note

Standard library only. Free.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DP = ROOT / "data" / "processed"
OUT = DP / "coverage_universes.csv"
MANIFEST = DP / "coverage_universes_manifest.json"

COLUMNS = ("block", "universe", "models_or_families", "benchmarks_or_batteries",
           "arms_or_rewards", "items", "seeds_or_pairs", "recipe", "reads_on", "note")


def _csv(name: str) -> list[dict]:
    with (DP / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prompt_rows() -> list[dict]:
    reg = _csv("battery_cohort.csv")
    p = [r for r in reg if r["in_p"] == "1"]
    n = len(p)
    two_rep = sum(1 for r in p if int(r["control_rows"]) > 800)
    ceilings = sorted({f"{r['max_tokens']} ({r['reasoning']})" for r in p})
    outside = [r for r in reg if r["in_p"] != "1"]
    rows = [{
        "block": "U1 Measurement",
        "universe": "P, the same models as the prompt comparisons",
        "models_or_families": f"{n} models",
        "benchmarks_or_batteries": "8 benchmarks",
        "arms_or_rewards": "baseline prompt",
        "items": "100 frozen items per benchmark",
        "seeds_or_pairs": f"1 rep ({n - two_rep} models) or 2 reps ({two_rep} models), equal weight per cell",
        "recipe": "temperature 0 where supported; one token ceiling per model: " + ", ".join(ceilings),
        "reads_on": "the overconfidence measurement, the vintage plane, the rescored leaderboard",
        "note": (f"The same {n} models as both prompt comparisons; ten pre-registered. "
                 f"All {len(reg)} complete baselines remain in the full assessment registry."),
    }, {
        "block": "U2 Prompt interventions",
        "universe": "P, the models admitted under all three prompts",
        "models_or_families": f"{len(p)} models",
        "benchmarks_or_batteries": "8 benchmarks",
        "arms_or_rewards": "baseline, scoring-rule prompt, warning",
        "items": "100 frozen items per benchmark, identical across arms",
        "seeds_or_pairs": "paired within model and item",
        "recipe": "the model's own ceiling in every arm",
        "reads_on": "both prompt levers, against P's own baseline",
        "note": ("P is every battery model that kept the answer format under all three prompts. "
                 "Outside P: " + "; ".join(
                     f"{r['model']} ({'rule' if r['rule_status'] != 'admitted' else 'warning'} "
                     f"{r['rule_status'] if r['rule_status'] != 'admitted' else r['warning_status']})"
                     for r in outside) + "."),
    }]
    return rows


def training_rows() -> list[dict]:
    pairs = _csv("common_training_pairs.csv")
    families = sorted({r["model_family"] for r in pairs})
    identities = {(r["model_family"], r["training_domain"], r["training_seed"]) for r in pairs}
    if len(families) != 3 or len(identities) != 24 or len(pairs) != 96:
        raise ValueError("Coverage requires the complete common training matrix")
    family_text = ", ".join(families)
    rows = []
    specifications = [
        ("Pooled results", "pooled training", "4 held-out benchmarks: math, medicine, ethics, GPQA",
         "1,098 questions per checkpoint", "2 pairs per model; 6 total",
         "training overview, family levels, confidence distribution and external gate"),
        ("Cross-domain transfer", "single-subject training, all directional routes", "train math, medicine or ethics; test all three plus GPQA",
         "300 math, 300 medicine, 300 ethics and 198 GPQA questions per checkpoint", "2 pairs per model and training subject; 18 total",
         "the train-on/test-on matrix"),
        ("Broader behavior", "the same pooled final checkpoints", "MASK, instruction hierarchy and five decision/behavior tracks",
         "483 MASK, 200 hierarchy, 450 free-form, and 344 decision/behavior items", "2 pairs per model; control once",
         "truth, hierarchy, unauthorized shortcuts and decision results"),
        ("Social pressure", "the same pooled final checkpoints", "math, medicine and ethics; wrong and correct pushback",
         "150 initial questions per checkpoint; second turns conditional on the first answer", "2 pairs per model; control once",
         "accepting incorrect advice and valid corrections, malformed rates and second-turn accuracy"),
        ("Training trajectories", "the same pooled runs, every five steps", "5 knowledge benchmarks, 20 questions each",
         "100 questions per checkpoint", "2 pairs per model; steps 5 through 60, plus prepared control",
         "the diverging-paths figure"),
    ]
    for label,universe,benchmarks,items,seeds,reads in specifications:
        rows.append({"block":"U3 Training: "+label,"universe":universe,
            "models_or_families":family_text,"benchmarks_or_batteries":benchmarks,
            "arms_or_rewards":"accuracy-only versus honest-confidence; same prepared control",
            "items":items,"seeds_or_pairs":seeds,
            "recipe":"240 frozen questions per training context; 60 steps; batch 4; group 8; LoRA 32; learning rate 4e-5; 512 tokens",
            "reads_on":reads,
            "note":"Identical syntax preparation, seed matrix, data, training and evaluation allowances across models. GPT-OSS uses low reasoning; Qwen and Nemotron disable thinking. Malformed outputs count as wrong and do not censor a run."})
    return rows


def notes_only_rows() -> list[dict]:
    synth = _csv("training_effect_synthesis.csv")
    by_prog: dict[str, set] = defaultdict(set)
    for r in synth:
        by_prog[r["programme"]].add(r["pair_id"])
    prog_text = "; ".join(f"{k}: {len(v)} pair{'' if len(v) == 1 else 's'}"
                          for k, v in sorted(by_prog.items()) if k != "second")
    return [{
        "block": "Notes only",
        "universe": "earlier training programmes and supplementary prompting checks",
        "models_or_families": "Qwen3 8B's first programme; the 13-model same-run study; answer-only; test-retest",
        "benchmarks_or_batteries": "various",
        "arms_or_rewards": "various",
        "items": "various",
        "seeds_or_pairs": prog_text,
        "recipe": "mixed",
        "reads_on": "the notes page only, never the headline",
        "note": "Never the headline.",
    }]


def main() -> None:
    rows = prompt_rows() + training_rows() + notes_only_rows()
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    MANIFEST.write_text(json.dumps({
        "created_by": "scripts/export_coverage_universes.py",
        "inputs": ["battery_cohort.csv", "common_training_pairs.csv", "training_effect_synthesis.csv"],
        "rows": len(rows),
    }, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        print(f"{r['block']:34s} {r['models_or_families'][:40]:40s} {r['seeds_or_pairs'][:60]}")


if __name__ == "__main__":
    main()
