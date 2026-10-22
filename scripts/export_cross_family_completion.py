#!/usr/bin/env python3
"""Export the Qwen3 8B and GPT-OSS 20B evaluation matrix side by side.

Every combined table keeps model family as an explicit column.  The exporter
also refuses to combine a battery unless the frozen item hashes match, because
shared benchmark names are not enough to establish an apples-to-apples test.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
from collections.abc import Callable

from export_alignment_battery import (
    CONTRAST_FIELDS as ALIGNMENT_CONTRAST_FIELDS,
)
from export_alignment_battery import (
    LEVEL_FIELDS as ALIGNMENT_LEVEL_FIELDS,
)
from export_alignment_battery import (
    export as export_alignment,
)
from export_external_transfer import (
    CONTRAST_FIELDS as EXTERNAL_CONTRAST_FIELDS,
)
from export_external_transfer import (
    LEVEL_FIELDS as EXTERNAL_LEVEL_FIELDS,
)
from export_external_transfer import (
    export as export_external,
)
from export_plural_prudence import (
    CONTRAST_FIELDS as PRUDENCE_CONTRAST_FIELDS,
)
from export_plural_prudence import (
    LEVEL_FIELDS as PRUDENCE_LEVEL_FIELDS,
)
from export_plural_prudence import (
    export as export_prudence,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"

DEFAULTS = {
    "qwen_alignment": ROOT / "runs" / "finetune" / "matched_alignment_battery_v1" / "summary.json",
    "gpt_alignment": ROOT / "runs" / "finetune" / "cross_family_completion_v1" / "gptoss_matched_alignment" / "summary.json",
    "qwen_prudence": ROOT / "runs" / "finetune" / "plural_prudence_v1" / "summary.json",
    "gpt_prudence": ROOT / "runs" / "finetune" / "cross_family_completion_v1" / "gptoss_plural_prudence" / "summary.json",
    "qwen_external": ROOT / "runs" / "finetune" / "external_transfer_v1" / "summary.json",
    "gpt_external": ROOT / "runs" / "finetune" / "cross_family_completion_v1" / "gptoss_external_transfer" / "summary.json",
}

FAMILIES = (("Qwen3 8B", "qwen"), ("GPT-OSS 20B", "gpt"))


def _write(path: pathlib.Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read(path: pathlib.Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"summary must be an object: {path}")
    return payload


def _hash_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_same_items(
    label: str,
    qwen: dict[str, object],
    gpt: dict[str, object],
    design_keys: tuple[str, ...],
) -> None:
    q_design = qwen["design"]
    g_design = gpt["design"]
    assert isinstance(q_design, dict) and isinstance(g_design, dict)
    for key in design_keys:
        if q_design.get(key) != g_design.get(key):
            raise ValueError(f"{label} item identity differs for {key}")


def _combine(
    summaries: dict[str, pathlib.Path],
    exporter: Callable[[pathlib.Path], tuple],
    level_fields: tuple[str, ...],
    contrast_fields: tuple[str, ...],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    levels: list[dict[str, object]] = []
    contrasts: list[dict[str, object]] = []
    for family, prefix in FAMILIES:
        exported = exporter(summaries[prefix])
        family_levels, family_contrasts = exported[0], exported[1]
        levels.extend({"model_family": family, **row} for row in family_levels)
        contrasts.extend({"model_family": family, **row} for row in family_contrasts)
    _write(OUT / summaries["levels_name"], ("model_family",) + level_fields, levels)
    _write(
        OUT / summaries["contrasts_name"],
        ("model_family",) + contrast_fields,
        contrasts,
    )
    return levels, contrasts


def _coverage_rows() -> list[dict[str, object]]:
    """Describe analysis coverage, including honest residual asymmetries."""
    return [
        {
            "evidence_stream": "Matched prompt interventions",
            "qwen3_8b": "complete: baseline, scoring-rule prompt, warning; 800 questions each",
            "gpt_oss_20b": "complete: baseline, scoring-rule prompt, warning; 800 questions each",
            "status": "matched",
            "remaining_limit": "None",
        },
        {
            "evidence_stream": "Matched fine-tuning on common battery",
            "qwen3_8b": "5 binary versus quadratic seed pairs",
            "gpt_oss_20b": "4 binary versus quadratic seed pairs",
            "status": "matched design; unequal seed count",
            "remaining_limit": "A fifth GPT-OSS seed failed its pre-analysis training gate",
        },
        {
            "evidence_stream": "Subject transfer",
            "qwen3_8b": "7 admitted matched pairs across own, other, and never-trained domains",
            "gpt_oss_20b": "3 admitted of 6 planned pairs across the same transfer distances",
            "status": "same matrix; unequal admitted pairs",
            "remaining_limit": "Three GPT-OSS pairs failed frozen format or abstention gates",
        },
        {
            "evidence_stream": "Hidden-opportunity behavior",
            "qwen3_8b": "base plus 24 trained checkpoints",
            "gpt_oss_20b": "format-control base plus 8 trained checkpoints",
            "status": "same scenarios; pooled checkpoints comparable",
            "remaining_limit": "Qwen also has domain-specific checkpoints that GPT-OSS never produced",
        },
        {
            "evidence_stream": "Matched alignment battery",
            "qwen3_8b": "base plus 17 trained checkpoints",
            "gpt_oss_20b": "format-control base plus 8 trained checkpoints",
            "status": "same frozen items",
            "remaining_limit": "Qwen includes a third fixed-cost objective not trained for GPT-OSS",
        },
        {
            "evidence_stream": "Plural-prudence battery",
            "qwen3_8b": "base plus 15 matched primary checkpoints",
            "gpt_oss_20b": "format-control base plus 8 matched checkpoints",
            "status": "same frozen items",
            "remaining_limit": "Qwen includes a third fixed-cost objective not trained for GPT-OSS",
        },
        {
            "evidence_stream": "External transfer battery",
            "qwen3_8b": "base plus 15 matched primary checkpoints",
            "gpt_oss_20b": "format-control base plus 8 matched checkpoints",
            "status": "same frozen items",
            "remaining_limit": "Qwen includes a third fixed-cost objective not trained for GPT-OSS",
        },
        {
            "evidence_stream": "Dose and checkpoint trajectories",
            "qwen3_8b": "18 reward runs across four per-step scales with dense checkpoint evaluation",
            "gpt_oss_20b": "8 final trained checkpoints; one saved state at step 50 and final at step 60",
            "status": "not symmetric",
            "remaining_limit": (
                "A comparable 18-run GPT-OSS grid requires new training because "
                "intermediate sampler checkpoints were not saved. Even an "
                "unrealistically cheap 32-completion-per-step version is estimated "
                "at at least $31.36 for training plus about $10 for 36,000 dense "
                "evaluation responses, above the $33.03 authorization remaining "
                "after the three completed GPT-OSS batteries"
            ),
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=pathlib.Path, default=default)
    args = parser.parse_args(argv)
    paths = {name: getattr(args, name) for name in DEFAULTS}

    payloads = {name: _read(path) for name, path in paths.items()}
    _assert_same_items(
        "alignment",
        payloads["qwen_alignment"],
        payloads["gpt_alignment"],
        ("decision_items_sha256", "evidence_items_sha256", "schemes_sha256"),
    )
    _assert_same_items(
        "plural prudence",
        payloads["qwen_prudence"],
        payloads["gpt_prudence"],
        ("item_hashes",),
    )
    _assert_same_items(
        "external transfer",
        payloads["qwen_external"],
        payloads["gpt_external"],
        ("item_hashes",),
    )

    alignment_levels, alignment_contrasts = _combine(
        {
            "qwen": paths["qwen_alignment"],
            "gpt": paths["gpt_alignment"],
            "levels_name": "openweight_alignment_levels.csv",
            "contrasts_name": "openweight_alignment_contrasts.csv",
        },
        export_alignment,
        ALIGNMENT_LEVEL_FIELDS,
        ALIGNMENT_CONTRAST_FIELDS,
    )
    prudence_levels, prudence_contrasts = _combine(
        {
            "qwen": paths["qwen_prudence"],
            "gpt": paths["gpt_prudence"],
            "levels_name": "openweight_plural_prudence_levels.csv",
            "contrasts_name": "openweight_plural_prudence_contrasts.csv",
        },
        export_prudence,
        PRUDENCE_LEVEL_FIELDS,
        PRUDENCE_CONTRAST_FIELDS,
    )
    external_levels, external_contrasts = _combine(
        {
            "qwen": paths["qwen_external"],
            "gpt": paths["gpt_external"],
            "levels_name": "openweight_external_transfer_levels.csv",
            "contrasts_name": "openweight_external_transfer_contrasts.csv",
        },
        export_external,
        EXTERNAL_LEVEL_FIELDS,
        EXTERNAL_CONTRAST_FIELDS,
    )
    coverage = _coverage_rows()
    _write(
        OUT / "openweight_family_coverage.csv",
        ("evidence_stream", "qwen3_8b", "gpt_oss_20b", "status", "remaining_limit"),
        coverage,
    )

    source_records = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": _hash_file(path),
            "records": payloads[name].get("records"),
            "spend": payloads[name].get("spend"),
        }
        for name, path in paths.items()
    }
    manifest = {
        "schema_version": 1,
        "item_identity": "matched across model families for all three newly completed batteries",
        "sources": source_records,
        "outputs": {
            "alignment_levels": len(alignment_levels),
            "alignment_contrasts": len(alignment_contrasts),
            "prudence_levels": len(prudence_levels),
            "prudence_contrasts": len(prudence_contrasts),
            "external_levels": len(external_levels),
            "external_contrasts": len(external_contrasts),
            "coverage_rows": len(coverage),
        },
    }
    (OUT / "openweight_cross_family_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["outputs"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
