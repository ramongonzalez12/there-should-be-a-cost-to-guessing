"""Which code produced an artifact, and when that claim is untrustworthy.

The failure this guards is not a crash. It is a manifest that records a commit
hash which does not describe the code that ran, which reads as provenance and is
not. The second failure is subtler: putting the commit inside a manifest's frozen
design, which would make every stage after any commit refuse to resume a run
whose design never changed.
"""

import subprocess

from belowzero.provenance import git_commit, git_dirty, provenance


def fake_run(stdout="", returncode=0, *, status_stdout=""):
    """A git stand-in that answers rev-parse and status separately.

    They are different questions and a fake that returns one string for both
    silently makes a clean tree look dirty, which is how the first version of
    these tests failed.
    """
    def run(argv, **kwargs):
        out = status_stdout if "status" in argv else stdout
        return subprocess.CompletedProcess(argv, returncode, stdout=out, stderr="")
    return run


def test_commit_is_the_short_hash():
    assert git_commit(".", run=fake_run("a392a45\n")) == "a392a45"


def test_commit_is_none_when_git_fails():
    """Never raise. Provenance is worth recording and not worth failing a run over."""
    assert git_commit(".", run=fake_run("", returncode=128)) is None


def test_commit_is_none_on_empty_output():
    assert git_commit(".", run=fake_run("\n")) is None


def test_a_clean_tree_is_not_dirty():
    assert git_dirty(".", run=fake_run(status_stdout="")) is False


def test_any_uncommitted_change_is_dirty():
    assert git_dirty(
        ".", run=fake_run(status_stdout=" M scripts/census.py\n")) is True


def test_unknown_is_distinct_from_clean():
    """None and False are different claims and callers act on them differently.

    A runner that refuses to spend on a dirty tree has to decide for itself what
    to do when git could not answer; collapsing that into "clean" makes the
    decision for it, in the permissive direction.
    """
    assert git_dirty(".", run=fake_run("", returncode=128)) is None
    assert git_dirty(".", run=fake_run("", returncode=128)) is not False


def test_provenance_carries_both_facts():
    record = provenance("/tmp/repo", run=fake_run("a392a45\n"))
    assert record["git_commit"] == "a392a45"
    assert record["git_dirty"] is False
    assert record["root"] == "/tmp/repo"


def test_the_real_repository_answers():
    """Smoke test against the actual checkout, not a fake."""
    commit = git_commit(".")
    assert commit is None or (commit and " " not in commit)
