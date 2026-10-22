#!/usr/bin/env python3
"""Export the prospectively gated GPT-OSS and Kimi family screen."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "runs" / "finetune" / "openweight_family_v1"
DEFAULT_OUT = ROOT / "data" / "processed"


def _portable_path(path) -> str:
    """Manifest paths are labels; the identity of an input is its content.
    Record repo-relative (or sibling-relative) strings so a committed manifest
    never contains an absolute home directory."""
    p = pathlib.Path(path).resolve()
    for base in (ROOT, ROOT.parent):
        try:
            return str(p.relative_to(base))
        except ValueError:
            continue
    return p.name


def _read(path: pathlib.Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: pathlib.Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spend(run: pathlib.Path) -> tuple[float, list[dict[str, object]]]:
    rows = []
    total = 0.0
    for ledger in sorted(run.glob("**/spend.jsonl")):
        cost = sum(float(row.get("cost_usd", 0.0)) for row in _jsonl(ledger))
        rows.append({"run": str(ledger.parent.relative_to(run)), "spent_usd": cost})
        total += cost
    return total, rows


def _gate_row(run: pathlib.Path, directory: str, stage: str) -> dict[str, object]:
    path = run / directory
    arm = _read(path / "arm.json")
    responses = _jsonl(path / "rollouts.jsonl")
    invalid = sum(row["outcome"] == "INVALID" for row in responses)
    first_raw = str(responses[0]["raw"])
    if directory == "gpt_oss_route":
        observation = "No final answer within 128 tokens"
        decision = "stop_before_full_profile"
    elif directory == "kimi_route":
        observation = "Answer reached, but extra text violated the grammar"
        decision = "continue_to_full_profile"
    else:
        observation = f"{invalid:,} malformed responses; at most 19 allowed"
        decision = "stop_before_reward_training"
    return {
        "model": arm["model"],
        "stage": stage,
        "sample_size": len(responses),
        "invalid_count": invalid,
        "invalid_rate": invalid / len(responses),
        "max_completion_tokens": arm["workload"]["max_tokens"],
        "observation": observation,
        "decision": decision,
        "rollouts_sha256": _sha256(path / "rollouts.jsonl"),
        # Store only the hash in the committed export. The full response stays
        # in the local, append-only run directory.
        "first_response_sha256": hashlib.sha256(first_raw.encode()).hexdigest(),
    }


def export(run: pathlib.Path, output: pathlib.Path) -> dict[str, object]:
    gates = [
        _gate_row(run, "gpt_oss_route", "one_response_route_check"),
        _gate_row(run, "kimi_route", "one_response_route_check"),
        _gate_row(run, "kimi_profile_101", "full_profile_seed101"),
    ]
    output.mkdir(parents=True, exist_ok=True)
    gate_path = output / "openweight_family_gates.csv"
    with gate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(gates[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(gates)

    spent, spend_rows = _spend(run)
    spend_path = output / "openweight_family_spend.csv"
    with spend_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(spend_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(spend_rows)

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "run_root": _portable_path(run),
        "git_commit": commit,
        "candidate_families": 2,
        "full_profile_responses": 1920,
        "reward_training_runs": 0,
        "actual_spend_usd": round(spent, 9),
        "hard_program_cap_usd": 20.0,
        "unspent_authorization_usd": round(20.0 - spent, 9),
        "outputs": [
            "data/processed/openweight_family_gates.csv",
            "data/processed/openweight_family_spend.csv",
        ],
    }
    (output / "openweight_family_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=pathlib.Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    print(json.dumps(export(args.run, args.out), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
