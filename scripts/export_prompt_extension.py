#!/usr/bin/env python3
"""Validate complete prompt-extension triples before admitting them to the cohort.

A file's existence or an 800-row count is insufficient. Every arm must contain
exactly the frozen questions and messages at one shared inference setting, and
must pass the prespecified format pilot. Rejected/partial candidates remain in
the selection ledger but cannot acquire paired results through file discovery.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from analyze_notation_artifact import cell_metrics, equal_cell_summary, load_group
from export_model_coverage_extension import BENCHES, METRICS

from belowzero.contracts import CONTRACTS, PROMPT_ONLY_CONTRACTS
from belowzero.datasets import BENCHMARKS
from belowzero.prompts import build_messages, messages_sha256

ARMS = ('control', 'quad_score_only', 'hedge_placebo')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_arm(path, model, arm):
    """Return the configuration and pilot evidence for an exact, graded arm."""
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute('SELECT a.*,m.request_json,m.rep,m.finish_reason FROM answers a '
                           'JOIN call_meta m USING(key) WHERE a.model=? AND a.contract=?',
                           (model, arm)).fetchall()
    frozen = {(b, i['item_id']): i for b in BENCHES for i in BENCHMARKS[b](100)}
    if len(rows) != 800 or {(r['benchmark'], r['item_id']) for r in rows} != set(frozen):
        raise ValueError(f'{model} {arm}: not the exact frozen 800-item matrix')
    settings = set()
    for row in rows:
        if row['error'] or row['verdict'] not in {'CORRECT', 'INCORRECT', 'NOT_ATTEMPTED'}:
            raise ValueError(f'{model} {arm}: provider error or ungraded row')
        if row['parse_failure'] and row['verdict'] != 'INCORRECT':
            raise ValueError(f'{model} {arm}: malformed response not scored incorrect')
        request = json.loads(row['request_json'])
        item = frozen[(row['benchmark'], row['item_id'])]
        messages = build_messages(item, {**CONTRACTS, **PROMPT_ONLY_CONTRACTS}[arm])
        if request['messages'] != messages or request['messages_sha256'] != messages_sha256(messages):
            raise ValueError(f'{model} {arm}: prompt or question differs from frozen specification')
        if row['reference'] != item['reference'] or row['rep'] != 0:
            raise ValueError(f'{model} {arm}: reference or repetition differs')
        # Client timeouts are recorded but do not change the sent inference
        # request. Provider pins, where present, DO belong in this equality.
        settings.add(json.dumps({k: request.get(k) for k in
                                ('model', 'max_tokens', 'reasoning', 'temperature', 'provider')}, sort_keys=True))
    if len(settings) != 1:
        raise ValueError(f'{model} {arm}: mixed inference settings')
    gates = []
    for bench in BENCHES:
        ids = {i['item_id'] for i in BENCHMARKS[bench](20)}
        pilot = [r for r in rows if r['benchmark'] == bench and r['item_id'] in ids]
        bad = sum(r['parse_failure'] for r in pilot)
        if bad == 2:
            ids = {i['item_id'] for i in BENCHMARKS[bench](60)}
            pilot = [r for r in rows if r['benchmark'] == bench and r['item_id'] in ids]
            bad = sum(r['parse_failure'] for r in pilot)
        if bad > (1 if len(pilot) == 20 else 3):
            raise ValueError(f'{model} {arm}: {bench} fails pilot ({bad}/{len(pilot)})')
        gates.append({'benchmark': bench, 'n': len(pilot), 'malformed': bad})
    return {'configuration': json.loads(next(iter(settings))), 'pilot': gates}


def export(selection_path, out):
    selection = json.loads(selection_path.read_text())
    candidates = selection['candidates']
    if len({r['model'] for r in candidates}) != len(candidates):
        raise ValueError('Duplicate candidate model')
    accepted, inputs, metrics = [], {}, []
    for candidate in candidates:
        if candidate['status'] not in {'complete', 'reused'}:
            continue
        model = candidate['model']
        sources = candidate['sources']
        if set(sources) != set(ARMS):
            raise ValueError(f'{model}: all three sources are required')
        evidence = {arm: validate_arm(ROOT / sources[arm], model, arm) for arm in ARMS}
        if len({json.dumps(v['configuration'], sort_keys=True) for v in evidence.values()}) != 1:
            raise ValueError(f'{model}: arms have different inference configurations')
        accepted.append({'model': model, 'sources': sources, 'evidence': evidence})
        for arm, source in sources.items():
            inputs[source] = sha256(ROOT / source)
            rows = [r for r in load_group('prompt_extension', [ROOT / source], (arm,)) if r.model == model]
            overall = equal_cell_summary(rows, 'corrected')
            metrics.append({'model': model, 'arm': arm, 'source': source, 'responses': len(rows),
                            **{label: overall[key] for key, label in METRICS.items()}})
            # Exercise every benchmark group too: the shared metric helpers
            # must see 100 rows per cell, never a pooled ragged denominator.
            for bench in BENCHES:
                cell = [r for r in rows if r.benchmark == bench]
                if len(cell) != 100:
                    raise ValueError(f'{model} {arm} {bench}: incomplete metric cell')
                cell_metrics(cell, 'corrected')
    if not accepted:
        raise ValueError('No validated completed triples')
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'created_by': 'scripts/export_prompt_extension.py',
                'selection': str(selection_path.relative_to(ROOT)),
                'selection_sha256': sha256(selection_path), 'accepted': accepted,
                'inputs': [{'path': k, 'sha256': v} for k, v in sorted(inputs.items())]}
    (out / 'prompt_extension_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with (out / 'prompt_extension_models.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(metrics[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(metrics)
    print(f'Validated {len(accepted)} model triples, {len(metrics)*800:,} responses')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT / 'data/processed')
    args = parser.parse_args()
    export(args.selection.resolve(), args.out)


if __name__ == '__main__':
    main()
