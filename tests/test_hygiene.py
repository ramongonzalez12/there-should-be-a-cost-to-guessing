"""Repo hygiene: no macOS Finder duplicate files anywhere in the tree.

Finder (and some sync tools) resolve name collisions by appending " 2" before
the extension. Two such copies of committed CSVs sat in site/below-zero/data/
for weeks: build_site.py republishes everything in data/processed/, and CI's
site diff only inspects tracked files, so the strays looked legitimate. This
test makes the pattern a failure wherever it appears, tracked or not, which is
deliberate -- a local stray is exactly the early warning we want.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# " 2.csv", " 3.json", " 12.py" -- a space then digits immediately before the
# final extension is the Finder-copy signature and never a legitimate name here.
STRAY = re.compile(r" \d+\.[^.]+$")

# Directories that hold committed artifacts. runs/ and data/cache/ are
# gitignored scratch space and excluded on purpose.
SCANNED = ["data/processed", "data/slices", "site", "scripts", "tests",
           "src", "notes", "content", "docs"]


def test_no_finder_duplicate_filenames():
    strays = sorted(
        str(p.relative_to(ROOT))
        for d in SCANNED
        for p in (ROOT / d).rglob("*")
        if p.is_file() and STRAY.search(p.name)
    )
    assert not strays, (
        "Finder-style duplicate files found (delete or rename them): "
        f"{strays}"
    )
