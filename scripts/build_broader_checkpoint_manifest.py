#!/usr/bin/env python3
"""Build the exact 18-checkpoint manifest for the broader evaluation."""

from __future__ import annotations

import argparse
import json
import pathlib
import tempfile

SEED0_ARMS = (
    "binary",
    "quadratic",
    "quad_cost_0.04",
    "quad_cost_0.09",
    "quad_cost_0.16",
)
REPLICATION_ARMS = ("binary", "quadratic", "quad_cost_0.09")


def _load(path: pathlib.Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"checkpoint manifest must be an object: {path}")
    return payload


def _validate_entry(
    entry: dict[str, object], *, arm: str, dose: int, seed: int | None
) -> None:
    if entry.get("arm") != arm or float(entry.get("dose", -1)) != dose:
        raise ValueError(f"expected {arm} at dose {dose}")
    if entry.get("training_seed") != seed:
        raise ValueError(f"expected {arm} to carry training seed {seed}")
    if not entry.get("sampler_path"):
        raise ValueError(f"{arm} is missing its sampler path")


def build(
    seed0: dict[str, dict[str, object]],
    replications: list[dict[str, dict[str, object]]],
    *,
    expected_seeds: tuple[int, ...] = (1, 2, 4, 5),
    dose: int = 500,
) -> dict[str, dict[str, object]]:
    """Return base, five seed-0 approaches, and three arms per replication."""
    base = seed0.get("base")
    if not base or base.get("arm") != "base" or float(base.get("dose", -1)) != 0:
        raise ValueError("seed-0 manifest must contain the untuned base")
    result = {"base": {"arm": "base", "dose": 0, "sampler_path": None}}
    for arm in SEED0_ARMS:
        entry = seed0.get(arm)
        if entry is None:
            raise ValueError(f"seed-0 manifest is missing {arm}")
        # The original dose-grid manifest predates the replication schema and
        # therefore has no training_seed field. Stamp its known seed here so
        # downstream exports can calculate five-seed dispersion without
        # silently dropping the first completed run.
        _validate_entry(entry, arm=arm, dose=dose, seed=None)
        result[f"seed0-{arm}"] = {**entry, "training_seed": 0}

    found_seeds = []
    for manifest in replications:
        arm_seeds = {
            manifest.get(arm, {}).get("training_seed") for arm in REPLICATION_ARMS
        }
        if len(arm_seeds) != 1:
            raise ValueError("replication arms do not share one training seed")
        seed = arm_seeds.pop()
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("replication training seed must be an integer")
        found_seeds.append(seed)
        for arm in REPLICATION_ARMS:
            entry = manifest.get(arm)
            if entry is None:
                raise ValueError(f"seed {seed} manifest is missing {arm}")
            _validate_entry(entry, arm=arm, dose=dose, seed=seed)
            result[f"seed{seed}-{arm}"] = dict(entry)
    if tuple(sorted(found_seeds)) != tuple(sorted(expected_seeds)):
        raise ValueError(
            f"expected replication seeds {sorted(expected_seeds)}, got {sorted(found_seeds)}"
        )
    if len(result) != 1 + len(SEED0_ARMS) + len(expected_seeds) * len(
        REPLICATION_ARMS
    ):
        raise RuntimeError("the broader checkpoint manifest has the wrong size")
    return result


def _atomic_json(path: pathlib.Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed0", type=pathlib.Path, required=True)
    parser.add_argument("--replications", type=pathlib.Path, nargs="+", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(_load(args.seed0), [_load(path) for path in args.replications])
    _atomic_json(args.out, manifest)
    print(json.dumps({"status": "READY", "checkpoints": len(manifest)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
