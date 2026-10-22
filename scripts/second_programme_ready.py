#!/usr/bin/env python3
"""Exit 0 only when the second training programme's evaluations are complete.

A readiness gate for the lab Makefile: its `make processed` must never pool a
half-finished programme (a run directory exists the moment an evaluator
starts writing, long before its status is COMPLETE), so the pickup keys on
this script rather than on the directories' existence. Prints one line per
evaluation with its status; standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAMME = ROOT / "runs" / "finetune" / "second_programme_v1"

# (family, evaluation directory, status file, key path to the status)
REQUIRED = []
for family in ("qwen", "gpt_oss", "nemotron"):
    REQUIRED += [
        (family, "eval_trajectory", "evaluation.json"),
        (family, "eval_final_batteries", "manifest.json"),
        (family, "eval_prudence", "manifest.json"),
    ]
    if family != "qwen":   # Qwen's shared-battery rows are reused from the first programme
        REQUIRED.append((family, "eval_shared_battery", "evaluation.json"))
REQUIRED.append(("nemotron", "eval_control_prompt_arms", "evaluation.json"))


def status_of(path: Path) -> str:
    if not path.exists():
        return "absent"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    return str(payload.get("status", "no status"))


def main() -> int:
    ready = True
    for family, directory, marker in REQUIRED:
        status = status_of(PROGRAMME / family / directory / marker)
        ok = status in ("COMPLETE", "COMPLETED")
        ready &= ok
        print(f"{family:9s} {directory:26s} {status}")
    print("READY" if ready else "NOT READY")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
