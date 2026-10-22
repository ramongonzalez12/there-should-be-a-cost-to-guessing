#!/usr/bin/env python3
"""Build the battery's cohort registry: one row per model, one status per arm.

WHY THIS EXISTS
---------------
The 42-model battery grew in four launches (Aug 27, Sep 4, Sep 5, Sep 6) and
its three prompt arms ended up admitted, format-failed or never run on a
per-model, per-arm basis. Until 2026-09-12 that bookkeeping lived in three
places that were kept in step by hand: a 19-entry ``--exclude-model`` list in
the Makefile, the notation analyzer's own "incomplete arms" drop, and gate
tables inside dated notes. Each exhibit then quoted whichever count its own
path produced (42 for the measurement, 32 for the rule, 31 for the warning),
and every one of those numbers cost the essay a caveat sentence.

This script derives the registry from the run databases and writes it once,
to ``data/processed/battery_cohort.csv``. Every analyzer that reads the
battery then takes ``--cohort data/processed/battery_cohort.csv`` and uses it
for three decisions it used to make on its own:

  1. which models are in the battery (a complete baseline arm);
  2. which database is the source for each admitted (model, arm), so a
     re-run at a different token ceiling SUPERSEDES the old rows by
     precedence instead of anything being deleted from a manifest-pinned
     database;
  3. which models form P, the set that kept the answer format under all
     three prompts at one per-model ceiling. Both prompt levers (the rule
     and the warning) are read on P against P's own baseline, so no two
     exhibits about the same intervention can use different model sets.

HOW A ROW IS DECIDED
--------------------
An arm is *admitted* for a model when some database in SOURCES holds it
complete: every one of the eight frozen benchmarks with at least 100 distinct
items answered without a terminal provider error. SOURCES is in precedence
order and the first database holding the arm complete is named as its source.
A later re-run therefore wins simply by being listed first.

An arm that no database holds complete must be explained: GATE_FAILURES maps
(model, arm) to the pilot-gate outcome recorded in the dated notes. A
non-admitted arm with no entry there is a hard error, and so is an entry whose
arm has since become admitted (the entry is stale and must be removed in the
same change that landed the new database). The registry can therefore never
drift silently in either direction.

Standard library only, like every other tool in this repository.

Usage (free; reads runs/, writes two files under data/processed/):

    python3 scripts/build_battery_cohort.py
    python3 scripts/build_battery_cohort.py --check   # verify, write nothing
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
PROCESSED = ROOT / "data" / "processed"
CATALOG = ROOT / "data" / "models_catalog.csv"
OUT_CSV = PROCESSED / "battery_cohort.csv"
OUT_MANIFEST = PROCESSED / "battery_cohort_manifest.json"

# The eight frozen benchmarks of the battery and the items each carries. An
# arm is complete only when every benchmark reaches ITEMS distinct items.
BENCHMARKS = ("mmlu_pro", "gpqa_parity", "medmcqa", "math500", "boolq",
              "truthfulqa_mc", "ethics_hard", "bbq")
ITEMS = 100

# The three arms of the battery, in the order the registry's columns use, and
# the short name each gets in column headers.
ARMS = (("control", "control"), ("quad_score_only", "rule"),
        ("hedge_placebo", "warning"))

# Response databases that can hold a battery arm, in PRECEDENCE order: the
# first database that holds a (model, arm) complete is that arm's source.
# A re-run at a new ceiling goes at the top so it supersedes the earlier
# rows without those rows being touched (they stay in their manifest-pinned
# database; the analyzers skip them because the registry names a different
# source). A path that does not exist yet is skipped, so this list can name
# a planned database before it lands.
SOURCES = (
    # 2026-09-12: the length-failure models re-run at a 4,000-token ceiling
    # in all three arms (plan: coverage equalisation, Part 2 A1).
    "runs/prompt_arms_4k_20260912.db",
    # the pre-registered ten, control and rule, 2026-08-27
    "runs/notation_rerun_20260827.db",
    # Sep 4 extension: Gemini 3.8 Flash, Claude Fable 5.1, Muse Glimmer 30B
    "runs/newmodels_notation_20260904.db",
    # Sep 5 vintage extension: checkpoints listed May 2023 to April 2026
    "runs/oldmodels_prompt_only_20260905.db",
    # the warning arm on the pre-registered ten, reasoning off and low
    "runs/prompt_arm_ident_main_off_20260827.db",
    "runs/prompt_arm_ident_main_low_20260827.db",
    # the warning arm on the Sep 4 extension
    "runs/newmodels_prompt_arm_ident_20260904.db",
    # Sep 6: the warning arm on the nineteen rule-arm models that lacked one
    "runs/warning_extension_20260906.db",
)

# The ten models pre-registered in August 2026 (PREREGISTRATION.md). Every
# other battery model was added in September under the same frozen items.
PREREGISTERED = frozenset({
    "openai/gpt-5.6-sol", "anthropic/claude-sonnet-5",
    "deepseek/deepseek-v4-pro-0813", "moonshotai/kimi-k3",
    "mistralai/mistral-medium-3-5", "nvidia/nemotron-3-ultra-550b-a55b",
    "qwen/qwen3-30b-a3b-instruct-2507", "meta-llama/llama-4-maverick",
    "google/gemini-3.7-flash", "openai/gpt-oss-120b",
})

# Why an arm was not admitted, per (model, arm): the pilot-gate outcome as
# the dated notes record it, with the note that holds the gate table. The
# gate was 20 items on MMLU-Pro, BoolQ, GPQA-parity and MATH-500 with at
# most one malformed response per cell (a cell at exactly two extends to
# sixty items). "length" means the response hit the token ceiling; "stop"
# means the model finished on its own without the required lines.
#
# Mistral Medium 3 and Qwen3 Next 80B recovered on 2026-09-12: re-piloted
# at 4,000 tokens they passed every cell in all three arms and were run in
# full at that ceiling (runs/prompt_arms_4k_20260912.db, first in SOURCES),
# so they carry no entry here and enter P.
# Status vocabulary: format_failure (the arm was piloted and failed its
# gate), not_run (the arm was never launched because an earlier arm's
# failure took the model out of scope, or because the cost was declined).
GATE_FAILURES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("openai/gpt-3.5-turbo", "quad_score_only"): (
        "format_failure",
        ("omits the PROBABILITY line (finish stop) on BoolQ 10/20 and MMLU-Pro "
        "8/20 at 900 tokens; not a ceiling failure, no re-pilot"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("openai/gpt-3.5-turbo", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("openai/gpt-4", "quad_score_only"): (
        "format_failure",
        ("MATH-500 5/20 (4 stop, 1 length) at 900 tokens; a 4,000-token "
        "re-pilot is not fundable for this route"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("openai/gpt-4", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("openai/gpt-4-turbo", "quad_score_only"): (
        "format_failure",
        ("MATH-500 6/20 (5 stop, 1 length) at 900 tokens; a 4,000-token "
        "re-pilot is not fundable for this route"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("openai/gpt-4-turbo", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("openai/gpt-4o-2024-08-06", "quad_score_only"): (
        "format_failure",
        ("MATH-500 11/60 (7 stop, 4 length) and GPQA 1/20 (length) at 900 "
        "tokens; re-piloted 2026-09-12 at 4,000: MATH-500 3/20 (2 length, 1 "
        "stop), fails again"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("openai/gpt-4o-2024-08-06", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("meta-llama/llama-3.3-70b-instruct", "quad_score_only"): (
        "format_failure",
        ("GPQA 4/20 (length), MATH-500 4/20 (3 stop, 1 length) and MMLU-Pro "
        "2/20 (length) at 900 tokens; re-piloted 2026-09-12 at 4,000: MATH-500 "
        "5/19 (all stop), fails again"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("meta-llama/llama-3.3-70b-instruct", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("deepseek/deepseek-chat", "hedge_placebo"): (
        "format_failure",
        ("warning pilot MATH-500 4/20 and GPQA 1/20, all length, at 900 "
        "tokens; re-piloted 2026-09-12 at 4,000 in all three arms: warning "
        "MATH-500 3/20 (2 length, 1 stop), fails again; the pilot rows stay in "
        "their databases"),
        "notes/2026-09-06-warning-arm-extension.md"),
    ("google/gemma-3-27b-it", "quad_score_only"): (
        "format_failure",
        ("MATH-500 5/20, all length, at 900 tokens; re-piloted 2026-09-12 at "
        "4,000: MATH-500 4/20 (2 length, 2 stop), fails again"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("google/gemma-3-27b-it", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("deepseek/deepseek-chat-v3-0324", "quad_score_only"): (
        "format_failure",
        ("MATH-500 11/20, GPQA 2/20 and MMLU-Pro 1/20, all length, at 900 "
        "tokens; re-piloted 2026-09-12 at 4,000: the baseline itself fails "
        "(MATH-500 3/20, all length) and the rule arm 6/20"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("deepseek/deepseek-chat-v3-0324", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
    ("meta-llama/llama-4-scout", "quad_score_only"): (
        "format_failure",
        ("GPQA 9/20 and MMLU-Pro 4/20, all stop, at 4,000 tokens (the "
        "control arm was itself re-piloted to 4,000)"),
        "notes/2026-09-06-vintage-rule-arm.md"),
    ("meta-llama/llama-4-scout", "hedge_placebo"): (
        "not_run", "rule arm failed its gate; the warning was never in scope",
        "notes/2026-09-06-warning-arm-extension.md"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=False,
                            capture_output=True, text=True)
    return result.stdout.strip()


def listing_dates() -> dict[str, str]:
    """OpenRouter listing date per model id from the committed catalogue
    (the `created` epoch), the same column the vintage analyzer uses."""
    dates = {}
    with CATALOG.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            created = int(row["created"])
            dates[row["id"]] = datetime.fromtimestamp(
                created, tz=timezone.utc).date().isoformat()
    return dates


def reasoning_label(raw: str | None) -> str:
    """Collapse the request's reasoning block to the two settings the battery
    used: `off` (absent, or enabled=false) and `low` (effort=low)."""
    if not raw:
        return "off"
    try:
        block = json.loads(raw)
    except (TypeError, ValueError):
        return "off"
    if not isinstance(block, dict):
        return "off"
    if block.get("enabled") is False:
        return "off"
    effort = block.get("effort")
    return str(effort) if effort else "off"


def scan(path: Path) -> dict[tuple[str, str], dict]:
    """Every complete (model, arm) a database holds, with its row count and
    the request settings it was generated under.

    Completeness is judged on distinct items per benchmark with no terminal
    error, so a pilot (20 items on four benchmarks) or a run that stopped at
    its spend cap never counts as a source. Rows are counted separately so
    the registry records a two-rep arm as 1,600 rows, not 800."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    items: dict[tuple[str, str], dict[str, set]] = defaultdict(lambda: defaultdict(set))
    rows: dict[tuple[str, str], int] = defaultdict(int)
    settings: dict[tuple[str, str], set] = defaultdict(set)
    for r in con.execute(
            "SELECT a.model, a.contract, a.benchmark, a.item_id, "
            "json_extract(m.request_json, '$.max_tokens') AS max_tokens, "
            "json_extract(m.request_json, '$.reasoning') AS reasoning "
            "FROM answers a JOIN call_meta m USING (key) "
            "WHERE a.error IS NULL"):
        key = (r["model"], r["contract"])
        items[key][r["benchmark"]].add(r["item_id"])
        rows[key] += 1
        settings[key].add((r["max_tokens"], reasoning_label(r["reasoning"])))
    con.close()
    complete = {}
    for key, per_bench in items.items():
        if all(len(per_bench.get(b, ())) >= ITEMS for b in BENCHMARKS):
            if len(settings[key]) != 1:
                raise SystemExit(
                    f"{path.name}: {key} was generated under more than one "
                    f"ceiling or reasoning setting: {sorted(settings[key])}")
            max_tokens, reasoning = next(iter(settings[key]))
            complete[key] = {"rows": rows[key], "max_tokens": int(max_tokens),
                             "reasoning": reasoning}
    return complete


def coverage_controls(superseded=frozenset()) -> dict[str, set[tuple[str, str]]]:
    """Admit only the manifest-verified controls from the coverage study.

    Two reused databases also contain treatment arms. Their presence is not
    authorization to enlarge the paired study: only the explicitly validated
    (model, control) records belong to this descriptive cohort.
    """
    selection_path = PROCESSED / "model_coverage_extension_selection.json"
    manifest_path = PROCESSED / "model_coverage_extension_manifest.json"
    if not selection_path.exists():
        return {}
    selection = json.loads(selection_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if sha256(selection_path) != manifest["selection_sha256"]:
        raise SystemExit("coverage selection differs from its validated manifest")
    accepted = {r["model"]: r for r in selection["candidates"]
                if r["status"] in {"complete", "reused"}}
    inputs = {r["model"]: r for r in manifest["inputs"]}
    if set(accepted) != set(inputs):
        raise SystemExit("coverage manifest and selected controls disagree")
    allowed: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for model, candidate in accepted.items():
        # A fully validated replacement triple owns its control. The earlier
        # control remains documented, but is not an input to this rebuild.
        if model in superseded:
            continue
        source = candidate["source"]
        path = ROOT / source
        if inputs[model]["path"] != source or not path.is_file():
            raise SystemExit(f"{model}: validated coverage source is unavailable")
        if sha256(path) != inputs[model]["sha256"]:
            raise SystemExit(f"{model}: coverage database differs from its validated hash")
        allowed[source].add((model, "control"))
    return dict(allowed)



def prompt_extension_sources():
    """Load only triples independently validated against the frozen protocol.

    Pilot or partially written databases are never auto-discovered. The
    selection and all named sources must match the exporter's saved hashes.
    """
    selection_path = PROCESSED / "prompt_extension_selection.json"
    if not selection_path.exists():
        return {}, {}
    manifest = json.loads((PROCESSED / "prompt_extension_manifest.json").read_text())
    if sha256(selection_path) != manifest["selection_sha256"]:
        raise SystemExit("prompt extension selection differs from validated manifest")
    selection = json.loads(selection_path.read_text())
    accepted_rows = {r["model"]: r for r in selection["candidates"]
                     if r["status"] in {"complete", "reused"}}
    accepted = set(accepted_rows)
    if accepted != {r["model"] for r in manifest["accepted"]}:
        raise SystemExit("prompt extension acceptance sets disagree")
    source_paths = {path for r in manifest["accepted"] for path in r["sources"].values()}
    if source_paths != {r["path"] for r in manifest["inputs"]}:
        raise SystemExit("prompt extension source hashes do not cover accepted sources")
    for record in manifest["accepted"]:
        if record["sources"] != accepted_rows[record["model"]]["sources"]:
            raise SystemExit("prompt extension accepted sources differ from selection")
    for item in manifest["inputs"]:
        path = ROOT / item["path"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise SystemExit(f"prompt extension source unavailable or changed: {item['path']}")
    allowed = defaultdict(set)
    for record in manifest["accepted"]:
        for arm, path in record["sources"].items():
            allowed[path].add((record["model"], arm))
    outcomes = {}
    for candidate in selection["candidates"]:
        if candidate["model"] in accepted:
            continue
        for arm, outcome in candidate.get("arm_outcomes", {}).items():
            outcomes[(candidate["model"], arm)] = (
                outcome["status"], outcome["reason"],
                "notes/2026-09-13-prompt-extension-results.md")
    return dict(allowed), outcomes


def build() -> tuple[list[dict], dict]:
    dates = listing_dates()
    prompted, outcomes = prompt_extension_sources()
    superseded = {model for keys in prompted.values() for model, arm in keys if arm == "control"}
    extension = coverage_controls(superseded)
    gate_failures = dict(GATE_FAILURES)
    for keys in extension.values():
        for model, _ in keys:
            for arm, _ in ARMS[1:]:
                gate_failures[(model, arm)] = (
                    "not_run", ("only the control was validated for this descriptive "
                    "assessment; other arms are outside this cohort"),
                    "notes/2026-09-13-model-coverage-results.md")
    gate_failures.update(outcomes)
    for source_path, keys in prompted.items():
        extension.setdefault(source_path, set()).update(keys)
        for key in keys:
            gate_failures.pop(key, None)
    ordered_sources = dict.fromkeys((*prompted, *extension, *SOURCES))
    present = [ROOT / p for p in ordered_sources if (ROOT / p).exists()]
    if not present:
        raise SystemExit("no run databases found under runs/; nothing to build")
    # (model, arm) -> first database (by precedence) holding it complete
    source: dict[tuple[str, str], tuple[Path, dict]] = {}
    for path in present:
        for key, info in scan(path).items():
            restriction = extension.get(str(path.relative_to(ROOT)))
            if restriction is not None and key not in restriction:
                continue
            source.setdefault(key, (path, info))

    battery = sorted(m for (m, arm) in source if arm == "control")
    problems: list[str] = []
    records = []
    for model in battery:
        rec: dict = {
            "model": model,
            "cohort": "preregistered" if model in PREREGISTERED else "added",
            "listed_date": dates.get(model, ""),
        }
        if not rec["listed_date"]:
            problems.append(f"{model}: not in {CATALOG.name}; the listing date "
                            "column would be blank")
        ceilings = set()
        reasons = []
        admitted_all = True
        for arm, short in ARMS:
            key = (model, arm)
            if key in source:
                path, info = source[key]
                if key in gate_failures:
                    problems.append(
                        f"{model} {arm}: GATE_FAILURES still lists a failure but "
                        f"{path.name} now holds the arm complete; remove the "
                        "stale entry in the same change")
                rec[f"{short}_status"] = "admitted"
                rec[f"{short}_db"] = str(path.relative_to(ROOT))
                rec[f"{short}_rows"] = info["rows"]
                ceilings.add((info["max_tokens"], info["reasoning"]))
            else:
                admitted_all = False
                if key not in gate_failures:
                    problems.append(
                        f"{model} {arm}: not admitted and no GATE_FAILURES entry "
                        "explains why")
                    status, reason = "unexplained", ""
                else:
                    status, reason, note = gate_failures[key]
                    reasons.append(f"{short}: {reason} ({note})")
                rec[f"{short}_status"] = status
                rec[f"{short}_db"] = ""
                rec[f"{short}_rows"] = 0
        # The protocol's invariant: one ceiling and one reasoning setting per
        # model across its admitted arms. A violation means two arms of one
        # model were generated under different inference settings, and their
        # contrast would be confounded by the setting rather than the prompt.
        if len(ceilings) != 1:
            problems.append(f"{model}: admitted arms disagree on ceiling or "
                            f"reasoning: {sorted(ceilings)}")
            max_tokens, reasoning = "", ""
        else:
            max_tokens, reasoning = next(iter(ceilings))
        rec["max_tokens"] = max_tokens
        rec["reasoning"] = reasoning
        rec["in_p"] = int(admitted_all)
        rec["reason"] = " | ".join(reasons)
        records.append(rec)

    # Every GATE_FAILURES key must name a battery model; a typo would
    # otherwise sit there forever explaining nothing.
    for (model, arm) in gate_failures:
        if model not in battery:
            problems.append(f"GATE_FAILURES names {model}, which has no complete "
                            "control arm in any source database")
    if problems:
        raise SystemExit("battery cohort registry cannot be built:\n  "
                         + "\n  ".join(problems))

    columns = ["model", "cohort", "listed_date", "max_tokens", "reasoning"]
    for _, short in ARMS:
        columns += [f"{short}_status", f"{short}_db", f"{short}_rows"]
    columns += ["in_p", "reason"]
    records = [{c: rec[c] for c in columns} for rec in records]
    records.sort(key=lambda r: (r["listed_date"], r["model"]))

    counts = {
        "models": len(records),
        **{f"{short}_admitted": sum(1 for r in records
                                    if r[f"{short}_status"] == "admitted")
           for _, short in ARMS},
        "p": sum(r["in_p"] for r in records),
        "two_rep_control": sum(1 for r in records if r["control_rows"] > 800),
    }
    manifest = {
        "created_by": "scripts/build_battery_cohort.py",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "benchmarks": list(BENCHMARKS),
        "items_per_benchmark": ITEMS,
        "sources_in_precedence_order": [str(p.relative_to(ROOT)) for p in present],
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)}
                   for p in present],
        "catalog_sha256": sha256(CATALOG),
        "counts": counts,
        "p_models": [r["model"] for r in records if r["in_p"]],
        "gate_notes": sorted({note for _, _, note in gate_failures.values()}),
        "prompt_extension_selection": ("data/processed/prompt_extension_selection.json" if prompted else None),
        "control_only_selection": (
            "data/processed/model_coverage_extension_selection.json" if extension else None),
    }
    return records, manifest


def read_registry(path: Path = OUT_CSV) -> list[dict]:
    """The committed registry, typed: counts as int, in_p as int."""
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for column in list(row):
            if column.endswith("_rows") or column in ("in_p", "max_tokens"):
                row[column] = int(row[column]) if row[column] != "" else 0
    return rows


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="rebuild in memory and compare with the committed "
                             "registry; exit non-zero on any difference")
    args = parser.parse_args(argv)
    records, manifest = build()
    if args.check:
        committed = read_registry()
        if committed != records:
            raise SystemExit("data/processed/battery_cohort.csv is stale; run "
                             "scripts/build_battery_cohort.py")
        print("battery_cohort.csv matches the run databases")
        return
    PROCESSED.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]),
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    c = manifest["counts"]
    print(f"battery {c['models']} models: control {c['control_admitted']}, "
          f"rule {c['rule_admitted']}, warning {c['warning_admitted']}, "
          f"P {c['p']} (two-rep control arms: {c['two_rep_control']})")
    for row in records:
        if not row["in_p"]:
            print(f"  outside P: {row['model']:40s} rule={row['rule_status']:15s} "
                  f"warning={row['warning_status']}")


if __name__ == "__main__":
    sys.exit(main())
