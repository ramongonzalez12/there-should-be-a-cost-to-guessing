"""Explicit, opt-in source transitions for the shared-store layout migration.

Original manifests stay byte-for-byte intact. The tracked transition receipt
lists exact old and new source hashes; arbitrary source edits still fail.
"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "lab/provider_recovery/runtime-relocation.json"


def source_matches(path, expected):
    """Accept unchanged source, or an explicitly pinned layout-only transition."""
    path = Path(path).resolve()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual == expected:
        return True
    if os.environ.get("BELOWZERO_LAYOUT_MIGRATION") != "20260924":
        return False
    if not path.is_relative_to(ROOT.resolve()):
        return False
    receipt = json.loads(RECEIPT.read_text())
    # Pin the new support code too: a changed resolver must not silently change
    # the meaning of an otherwise approved source transition.
    for name, digest in receipt["support_hashes"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            return False
    transition = receipt["files"].get(str(path.relative_to(ROOT.resolve())), {})
    return expected in transition.get("before", []) and actual == transition.get("after")
