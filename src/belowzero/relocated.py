"""Resolve retained path references without rewriting frozen experiment records.

Only the former below-zero checkouts are aliases. Missing copied files still
raise at the read/open boundary; this resolver never falls back to iCloud.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def retained_path(value, *parts):
    """Map a former checkout's runs to this checkout's shared runs symlink."""
    if value is None or value == "":
        raise ValueError("A retained path must be explicitly recorded")
    path = Path(value, *parts).expanduser()
    for base in (Path.home() / "Documents/Projects", Path.home() / "dev"):
        if not path.is_relative_to(base):
            continue
        relative = path.relative_to(base).parts
        if not relative or not (relative[0] == "below-zero" or relative[0].startswith("below-zero-")):
            continue
        # The new primary checkout and its worktrees already use the new layout.
        if base == Path.home() / "dev" and relative[0] == "below-zero":
            return path
        suffix = relative[1:]
        if ".." in suffix:
            raise ValueError("A retained checkout reference cannot escape its root")
        if suffix and suffix[0] not in {"runs", "notes", "lab", "scripts", "experiments", "src", ".venv"}:
            raise ValueError(f"Unmapped retained checkout path: {path}")
        return ROOT.joinpath(*suffix)
    return path
