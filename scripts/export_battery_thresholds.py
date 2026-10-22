"""Apply confidence gates to the essay's retained baseline responses, without API calls."""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from analyze_notation_artifact import cell_metrics, load_group, usable

ROOT = Path(__file__).resolve().parents[1]
DP = ROOT / 'data/processed'
THRESHOLDS = (0, .5, .6, .7, .8, .9, .95, 1)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-root', type=Path, required=True)
    args = parser.parse_args()
    cohort_path = DP / 'battery_cohort.csv'
    registry = [r for r in csv.DictReader(cohort_path.open()) if r['in_p'] == '1']
    manifest = json.loads((DP / 'battery_cohort_manifest.json').read_text())
    expected = {Path(r['path']).name:r['sha256'] for r in manifest['inputs']}
    names = sorted({Path(r['control_db']).name for r in registry})
    sources = {}
    for name in names:
        path = args.runs_root / name
        assert path.is_file(), f'Missing retained source: {path}'
        sources[name] = digest(path)
        assert sources[name] == expected[name], f'Source hash mismatch: {name}'
    raw = load_group('rerun', [args.runs_root / name for name in names], ('control',))
    # The registry selects exactly one baseline source for each included model.
    # We reproduce the published per-benchmark metrics before exporting gates.
    published = {(r['model'],r['benchmark']):r for r in csv.DictReader((DP/'notation_rerun_cells.csv').open()) if r['arm']=='control'}
    output = []
    confidence_audit = {}
    for entry in registry:
        rows = [r for r in raw if r.model == entry['model'] and r.source == Path(entry['control_db']).name]
        assert len(rows) == int(entry['control_rows']), (entry['model'],len(rows),entry['control_rows'])
        counts = Counter(r.benchmark for r in rows)
        assert len(counts)==8 and len(set(counts.values()))==1 and min(counts.values())>=100
        for benchmark in counts:
            cell = [r for r in rows if r.benchmark==benchmark]
            actual = cell_metrics(cell,'corrected')
            for metric in ('overall_accuracy','calibrated_score','usable_confidence_rate','high_confidence_error_90_rate'):
                assert math.isclose(actual[metric],float(published[entry['model'],benchmark][metric]),abs_tol=1e-10), (entry['model'],benchmark,metric)
        for threshold in THRESHOLDS:
            accepted = []
            for row in rows:
                conf = row.corrected_conf if row.corrected_conf is not None else row.stored_conf
                if usable(row,conf) and conf >= threshold:
                    accepted.append(row)
            if threshold == 0:
                # Count strictly above 40%, including the same count among
                # wrong answers. Binned charts cannot resolve this boundary.
                above = [r for r in accepted if
                         (r.corrected_conf if r.corrected_conf is not None else r.stored_conf) > .4]
                confidence_audit[entry['model']] = {
                    'usable': len(accepted), 'above_40': len(above),
                    'wrong': sum(not r.correct for r in accepted),
                    'wrong_above_40': sum(not r.correct for r in above)}
            correct = sum(r.correct for r in accepted)
            wrong = len(accepted)-correct
            output.append({'model':entry['model'],'threshold':threshold,'questions':len(rows),
                           'accepted':len(accepted),'correct':correct,'wrong':wrong,
                           'coverage':len(accepted)/len(rows),
                           'wrong_among_accepted':wrong/len(accepted) if accepted else '',
                           'wrong_per_question':wrong/len(rows)})
    out = DP/'battery_confidence_thresholds.csv'
    with out.open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(output[0]));writer.writeheader();writer.writerows(output)
    proof={'cohort_sha256':digest(cohort_path),'source_sha256':sources,'output_sha256':digest(out),
           'models':len(registry),'rows':len(output),'thresholds':THRESHOLDS,
           'published_cell_metrics_reproduced':True,
           'confidence_audit':confidence_audit,
           'confidence_audit_policy':'Strictly greater than 40% corrected confidence among usable baseline answers; declines and malformed responses excluded.',
           'denominators':{'wrong_among_accepted':'wrong / accepted; undefined if no answers pass',
                           'coverage':'accepted / all questions','wrong_per_question':'wrong / all questions'},
           'policy':'Accept usable baseline answers with corrected confidence >= threshold. No model or answer changes.',
           'weighting':'Pool questions within each model. Across models, weight models equally rather than pooling unequal run sizes.'}
    (DP/'battery_confidence_thresholds_manifest.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,indent=2))


if __name__ == '__main__':
    main()
