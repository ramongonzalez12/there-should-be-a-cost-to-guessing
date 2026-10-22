#!/usr/bin/env python3
"""Put the independent training trajectories side by side.

The dose grid trained one policy per reward objective.  That is one draw from a
stochastic process, so every magnitude it produced is a property of a trajectory
until a second trajectory says otherwise.  This script builds the comparison.

Three axes are kept separate throughout, and conflating any two of them is the
main way a reader misreads this kind of result:

* ``objective``     which reward the checkpoint was TRAINED on.
* ``scoring_rule``  which rule its stored answers are SCORED with afterwards.
* ``seed``          which stochastic training trajectory produced it.

The first two are separate because a policy that merely learned to game its own
reward gains under that reward and loses under the others; you cannot see that
if the training reward and the scoring rule are the same word in the same
column.  The third is separate because seed 0's magnitudes did not survive
seed 1, and reporting them as properties of the objective would be wrong.

Everything here is offline.  Stored responses are sufficient statistics for
rescoring under any rule, which is why the runner never baked a scoring
parameter in (see the repo's rule 3).
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_dose_grid_matrix import (
    SCORING_RULES,
    _portable_path,
    _read_jsonl,
    _sha256,
    knowledge_matrix,
)

# The doses the replication ran.  Seed 0 has every 25th step up to 500; the
# comparison is restricted to the doses both seeds actually measured, because a
# gap filled by interpolation would be a drawn claim rather than a measured one.
SHARED_DOSES = (125, 250, 300, 375, 500)

# The three objectives the replication re-ran.  Seed 0 also trained cost 0.04
# and 0.16; those have no second trajectory and so are excluded here rather
# than shown as if they had one.
REPLICATED_OBJECTIVES = ("binary", "quadratic", "quad_cost_0.09")

# Columns copied straight through from either seed's per-checkpoint matrix.
CARRIED = ("n", "accuracy", "coverage", "abstention_rate", "invalid_rate",
           "mean_probability", "brier")


def overconfidence(row: dict[str, object]) -> float | None:
    """Stated confidence minus how often that confidence was right.

    Positive is overconfident, negative under. Signed on purpose: the Brier
    decomposition's ``reliability`` term is squared and therefore says a model is
    miscalibrated without saying which way, which is the direction a reader
    actually wants.

    The denominators are the trap. ``mean_probability`` is averaged over
    ATTEMPTED items, because an abstention states no probability, while
    ``accuracy`` is over ALL items including abstentions and invalids. Subtract
    those two directly and every abstention inflates the apparent
    overconfidence. ``accuracy / coverage`` converts accuracy onto the attempted
    base, which is the only footing on which the subtraction means anything.
    """
    coverage = row.get("coverage")
    probability = row.get("mean_probability")
    accuracy = row.get("accuracy")
    if not coverage or probability is None or accuracy is None:
        return None
    return float(probability) - float(accuracy) / float(coverage)


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"refusing to write an empty matrix: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def replication_stage_matrices(
    run: pathlib.Path, *, condition: str = "neutral"
) -> dict[int, list[dict]]:
    """Score each stage's stored responses with the seed-0 analysis code.

    One stage at a time, deliberately.  Every stage re-evaluates the SAME
    untuned base, so concatenating the files first would silently merge the
    independent base measurements into one row and destroy the only estimate of
    evaluation noise this program has.

    Two directory shapes exist.  Seeds 0 and 1 evaluated the neutral condition
    alone and wrote ``evaluation_step_N_neutral``; later seeds evaluate the
    crossed set and write ``evaluation_step_N_crossed``.  Both are read, and the
    rows are filtered to one condition either way, because a matrix that mixed
    announced and unannounced answers would be measuring two different questions
    in one column.

    Doses are discovered rather than assumed.  A run stopped partway up the
    ladder is a normal outcome of a night that ran out of time, and it should
    contribute the stages it finished rather than raise.
    """
    matrices: dict[int, list[dict]] = {}
    for suffix in ("neutral", "crossed"):
        for path in sorted(run.glob(f"evaluation_step_*_{suffix}/responses.jsonl")):
            dose = int(path.parent.name.split("_")[2])
            rows = [r for r in _read_jsonl(path)
                    if r.get("prompt_condition") == condition]
            if rows:
                matrices[dose] = knowledge_matrix(rows)
    return matrices


def discover_runs(root: pathlib.Path) -> dict[int, pathlib.Path]:
    """Every recorded replication seed under a runs root, keyed by seed.

    Discovery is intentionally not restricted to completed programs. A seed
    stopped by a technical or spend gate is part of the experiment's observed
    outcome and must remain visible even when it has no evaluation matrix.
    """
    found: dict[int, pathlib.Path] = {}
    for path in sorted(root.glob("qwen_seed_replication_seed*/program.json")):
        try:
            seed = int(json.loads(path.read_text())["seed"])
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
        found[seed] = path.parent
    return found


def replication_run_record(
    run: pathlib.Path, matrices: dict[int, list[dict]]
) -> dict[str, object]:
    """Describe one run, including why it can or cannot enter the matrix.

    The numeric comparison can only use stages with stored evaluations. The
    manifest has a broader job: it must enumerate every discovered run so a
    failed gate cannot silently become a successful-seeds-only analysis.
    """
    program = json.loads((run / "program.json").read_text())
    stages = program.get("stages") or {}
    stage_statuses = {
        str(step): record.get("status")
        for step, record in sorted(stages.items(), key=lambda item: int(item[0]))
        if isinstance(record, dict)
    }
    included = bool(matrices)
    return {
        "path": _portable_path(run),
        "status": program.get("status"),
        "stage_statuses": stage_statuses,
        "doses": sorted(matrices),
        "analysis_included": included,
        "exclusion_reason": None if included else "no_completed_evaluation",
    }


def base_draws(matrices: dict[int, list[dict]], *, seed: int) -> list[dict]:
    """The untuned base, re-measured once per stage.

    Same weights, same 100 items, same neutral prompt, once per stage.  Any
    spread across these rows is evaluation noise and nothing else, which makes
    this the program's measured floor rather than an assumed one.  Reading that
    floor off a single stage understates it by roughly a factor of three.

    Both runs produce these, which was missed at first: seed 0 re-evaluated its
    base at three stages and seed 1 at five.  They are draws of the SAME
    quantity, because the untuned base is one fixed model answering one fixed
    item set, so the eight of them pool into a single floor rather than two.
    """
    draws = []
    for dose, matrix in sorted(matrices.items()):
        row = next(r for r in matrix if r["objective"] == "base")
        draws.append({"seed": seed, "measured_at_stage": dose,
                      **{k: row[k] for k in CARRIED if k in row},
                      **{f"score_{rule}": row[f"score_{rule}"]
                         for rule in SCORING_RULES}})
    return draws


def seed0_base_matrices(run: pathlib.Path) -> dict[int, list[dict]]:
    """Seed 0's per-stage base evaluations, restricted to the neutral prompt.

    The dose grid evaluated all six announced-rule conditions, so its stored
    responses carry six rows per item.  Only the neutral ones are comparable
    with seed 1 and with everything else on the page; pooling across conditions
    would measure a different quantity and, because it is six times the sample,
    would look misleadingly precise while doing it.
    """
    matrices: dict[int, list[dict]] = {}
    for path in sorted(run.glob("evaluation_step_*/responses.jsonl")):
        rows = [r for r in _read_jsonl(path)
                if r.get("prompt_condition") == "neutral"
                and r.get("checkpoint") == "base"]
        if not rows:
            continue
        dose = int(path.parent.name.split("_")[-1])
        matrices[dose] = knowledge_matrix(rows)
    return matrices


def noise_floor(draws: list[dict]) -> dict[str, dict[str, float]]:
    """Spread of the repeated base measurement, per scoring rule.

    Reported as both a standard deviation and a full range.  The range is what a
    reader should compare a single difference against: with five draws the sd is
    itself imprecise, and the honest statement is "this rule's identical-model
    measurements spanned this much".
    """
    floors = {}
    for rule in SCORING_RULES:
        values = [float(d[f"score_{rule}"]) for d in draws]
        floors[rule] = {
            "mean": statistics.fmean(values),
            "sd": statistics.stdev(values),
            "min": min(values),
            "max": max(values),
            "range": max(values) - min(values),
        }
    # Accuracy is not a scoring rule but is the page's second reference, so it
    # needs a floor on the same footing or it will be read as noise-free.
    accuracy = [float(d["accuracy"]) for d in draws]
    floors["accuracy"] = {
        "mean": statistics.fmean(accuracy), "sd": statistics.stdev(accuracy),
        "min": min(accuracy), "max": max(accuracy),
        "range": max(accuracy) - min(accuracy),
    }
    return floors


def pooled_base(matrices: dict[int, list[dict]]) -> dict:
    """Seed 1's reference base: every base response from every stage, pooled.

    Pooling 500 responses gives the tightest available estimate of where the
    untuned model actually sits, which is what every delta on the page is
    measured from.  The per-stage draws above answer a different question (how
    much would this number move if we measured it again) and are kept separate
    for exactly that reason.
    """
    weighted: dict[str, float] = {}
    total = sum(next(r for r in m if r["objective"] == "base")["n"]
                for m in matrices.values())
    for column in [*CARRIED, *(f"score_{rule}" for rule in SCORING_RULES)]:
        if column == "n":
            continue
        acc = 0.0
        for matrix in matrices.values():
            row = next(r for r in matrix if r["objective"] == "base")
            if row.get(column) is None:
                acc = None
                break
            acc += float(row[column]) * row["n"]
        weighted[column] = None if acc is None else acc / total
    return {"checkpoint": "base", "objective": "base", "step": 0, "n": total,
            **weighted}


def seed0_rows(path: pathlib.Path) -> list[dict]:
    """Seed 0's committed matrix, narrowed to the replicated design."""
    with path.open(newline="", encoding="utf-8") as handle:
        everything = list(csv.DictReader(handle))
    kept = []
    for row in everything:
        objective, step = row["objective"], int(row["step"])
        # The base is kept at step 0 only, and the trained arms only at the
        # doses seed 1 also ran. Seed 0 measured every 25th step; carrying the
        # extra ones through would put rows in the comparison table that have
        # no counterpart, which is exactly the asymmetry this page exists to
        # avoid.
        is_base = objective == "base" and step == 0
        is_replicated = objective in REPLICATED_OBJECTIVES and step in SHARED_DOSES
        if is_base or is_replicated:
            kept.append(row)
    return kept


def combined(seed0: list[dict],
             replications: dict[int, tuple[dict[int, list[dict]], dict]]
             ) -> list[dict]:
    """One tidy table: (seed, objective, step) -> outcomes under every rule.

    Takes every replication seed at once rather than one, and iterates the doses
    each run actually produced rather than a fixed ladder, so a seed stopped
    partway contributes what it finished instead of failing the whole table.
    """
    out = []

    def emit(seed: int, row: dict) -> None:
        record = {"seed": seed, "objective": row["objective"],
                  "step": int(row["step"])}
        for column in CARRIED:
            record[column] = row.get(column)
        record["overconfidence"] = overconfidence(
            {k: (float(v) if v not in (None, "") else None)
             for k, v in row.items() if k in
             ("coverage", "mean_probability", "accuracy")})
        for rule in SCORING_RULES:
            record[f"score_{rule}"] = row.get(f"score_{rule}")
        out.append(record)

    for row in seed0:
        emit(0, row)
    for seed, (matrices, base_row) in sorted(replications.items()):
        emit(seed, base_row)
        for _dose, matrix in sorted(matrices.items()):
            for row in matrix:
                if row["objective"] in REPLICATED_OBJECTIVES:
                    emit(seed, row)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=pathlib.Path, default=None,
                        help="discover every qwen_seed_replication_seedN run here")
    parser.add_argument("--replication-run", type=pathlib.Path, action="append",
                        default=[], help="an explicit run directory; repeatable")
    parser.add_argument("--seed0-run", type=pathlib.Path, default=None,
                        help="the qwen_dose_grid_seed0 run directory, for its own "
                             "repeated base measurements")
    parser.add_argument("--seed0-knowledge", type=pathlib.Path,
                        default=ROOT / "data" / "processed" / "dose_grid_knowledge.csv")
    parser.add_argument("--out", type=pathlib.Path,
                        default=ROOT / "data" / "processed")
    args = parser.parse_args(argv)

    runs: dict[int, pathlib.Path] = {}
    if args.runs_root is not None:
        runs.update(discover_runs(args.runs_root))
    for path in args.replication_run:
        runs[int(json.loads((path / "program.json").read_text())["seed"])] = path
    if not runs:
        parser.error("no replication runs given; pass --runs-root or --replication-run")

    replications: dict[int, tuple[dict[int, list[dict]], dict]] = {}
    run_records: dict[int, dict[str, object]] = {}
    draws: list[dict] = []
    # Seed 0 re-measured the same base at its own stages.  Pooling every run's
    # draws is what makes the floor a measurement rather than an assumption
    # carried from one run to the others.
    if args.seed0_run is not None:
        draws += base_draws(seed0_base_matrices(args.seed0_run), seed=0)
    for seed, run in sorted(runs.items()):
        matrices = replication_stage_matrices(run)
        run_records[seed] = replication_run_record(run, matrices)
        if not matrices:
            print(
                f"  seed {seed}: no completed evaluations; retained in manifest "
                f"with stages {run_records[seed]['stage_statuses']}"
            )
            continue
        replications[seed] = (matrices, pooled_base(matrices))
        draws += base_draws(matrices, seed=seed)
        print(f"  seed {seed}: doses {sorted(matrices)}")
    if not replications:
        parser.error("no replication run has a completed evaluation yet")

    floors = noise_floor(draws)
    seed0 = seed0_rows(args.seed0_knowledge)

    _write_csv(args.out / "seed_replication_knowledge.csv",
               combined(seed0, replications))
    _write_csv(args.out / "seed_replication_base_draws.csv", draws)

    # Provenance names the response files themselves, not a summary of them, so
    # a reader can re-derive every published figure from the run that produced
    # it.  A summary field would be a claim about the data; a hash is a handle
    # on it.
    inputs = {}
    for seed, run in sorted(runs.items()):
        if seed not in replications:
            continue
        for path in sorted(run.glob("evaluation_step_*/responses.jsonl")):
            inputs[f"seed{seed}_{path.parent.name}"] = {
                "path": _portable_path(path), "sha256": _sha256(path)}
    manifest = {
        "schema_version": 2,
        "seed0_knowledge_sha256": _sha256(args.seed0_knowledge),
        "replication_runs": {
            str(seed): run_records[seed]
            for seed in sorted(run_records)
        },
        "replicated_objectives": list(REPLICATED_OBJECTIVES),
        "scoring_rules": list(SCORING_RULES),
        "noise_floor": floors,
        "base_draws": len(draws),
        "inputs": inputs,
    }
    (args.out / "seed_replication_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"pooled base draws: {len(draws)}")
    print(f"quadratic noise floor: sd {floors['quadratic']['sd']:.4f}, "
          f"range {floors['quadratic']['range']:.4f} "
          f"({floors['quadratic']['min']:.3f} to {floors['quadratic']['max']:.3f})")
    print(f"wrote {args.out}/seed_replication_knowledge.csv "
          f"and seed_replication_base_draws.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
