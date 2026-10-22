"""Which code produced an artifact.

Every paid run in this repo writes a program manifest recording the plan, the
caps, the gates and the commands. None of them recorded the code version, so a
run's artifacts cannot be attributed to a commit. That is not academic here: the
orchestration scripts genuinely differed between checkouts while the two
completed runs were executing, and one of those differences was in a gate.

Two rules the callers depend on, both learned the expensive way:

* **Record the commit OUTSIDE any frozen or comparable structure.** These
  manifests fail closed when a frozen field changes, so putting the commit in
  one would make every stage after any commit raise "different frozen design"
  and refuse to resume a run that is perfectly fine.
* **A dirty tree makes the commit a lie.** A recorded hash that does not
  describe the code that ran is worse than no hash, because it invites exactly
  the reconstruction it cannot support.
"""

from __future__ import annotations

import os
import pathlib
import subprocess


def git_commit(root: str | os.PathLike[str], *, run=subprocess.run) -> str | None:
    """The short HEAD hash, or None when git cannot answer.

    Returns None rather than raising: provenance is worth recording when it is
    available and never worth failing a paid run over.
    """
    result = run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_dirty(root: str | os.PathLike[str], *, run=subprocess.run) -> bool | None:
    """Whether the tree has uncommitted changes. None when git cannot answer.

    None is deliberately distinct from False. "There are no changes" and "we
    could not find out" are different claims, and a caller that refuses to spend
    on a dirty tree should treat the unknown case as its own decision rather
    than as a clean bill of health.
    """
    result = run(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def provenance(root: str | os.PathLike[str], *, run=subprocess.run) -> dict[str, object]:
    """Both facts together, in the shape a manifest should store them."""
    return {
        "git_commit": git_commit(root, run=run),
        "git_dirty": git_dirty(root, run=run),
        "root": str(pathlib.Path(root)),
    }
