"""Read the battery's cohort registry (data/processed/battery_cohort.csv).

The registry is written by scripts/build_battery_cohort.py and answers three
questions every battery analyzer used to answer on its own, each slightly
differently: which models are in the battery, which database is the source
for each admitted (model, arm), and which models form P, the set that kept
the answer format under all three prompts at one per-model ceiling.

Analyzers take the registry through a ``--cohort PATH`` flag and call
:meth:`Cohort.keeps` on every response row. A row is kept only when its
(model, arm) is admitted AND it was read from the database the registry names
for that arm. That second condition is how a re-run supersedes an earlier one:
the earlier rows stay in their manifest-pinned database and are simply not the
named source any more.

Standard library only.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# Contract name -> the short arm name the registry's columns use.
ARM_COLUMNS = {"control": "control", "quad_score_only": "rule",
               "hedge_placebo": "warning"}


@dataclass(frozen=True)
class Cohort:
    path: Path
    rows: tuple[dict, ...]

    @property
    def models(self) -> frozenset[str]:
        """Every model in the battery (a complete baseline arm)."""
        return frozenset(r["model"] for r in self.rows)

    @property
    def p(self) -> frozenset[str]:
        """P: models admitted on all three arms at one ceiling."""
        return frozenset(r["model"] for r in self.rows if r["in_p"] == "1")

    def source_of(self, model: str, arm: str) -> str | None:
        """Repo-relative path of the database the registry names for an
        admitted (model, arm), or None when the arm is not admitted or the
        model is not in the battery."""
        short = ARM_COLUMNS.get(arm)
        if short is None:
            return None
        for r in self.rows:
            if r["model"] == model:
                if r[f"{short}_status"] != "admitted":
                    return None
                return r[f"{short}_db"] or None
        return None

    def keeps(self, model: str, arm: str, db_name: str) -> bool:
        """Whether a response row read from ``db_name`` (a file name or a
        repo-relative path) is the registry's source for this (model, arm)."""
        source = self.source_of(model, arm)
        if source is None:
            return False
        return Path(source).name == Path(db_name).name


def load_cohort(path: str | Path) -> Cohort:
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"{path}: empty cohort registry")
    required = {"model", "in_p"} | {f"{s}_status" for s in ARM_COLUMNS.values()} \
        | {f"{s}_db" for s in ARM_COLUMNS.values()}
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"{path}: cohort registry lacks columns {sorted(missing)}")
    return Cohort(path=path, rows=rows)
