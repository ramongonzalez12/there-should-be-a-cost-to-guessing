"""Summarize the same trained checkpoints on their own and other subjects.

The primary contrast balances math, medicine and ethics on both sides. GPQA
has no same-subject training arm and is kept as a separate evaluation scope.
All inputs are retained response-level metric aggregates, never scores inferred
from average accuracy and confidence.
"""
import csv
import math
from html import escape
from pathlib import Path
from statistics import mean

from essay_training_matrix import DOMAINS, FAMILIES

ALL_MODELS = 'All three models'
SCOPES = ('same', 'different', 'gpqa')
METRICS = ('gap', 'gap_distance', 'tail', 'accuracy', 'coverage', 'score', 'invalid')
DISPLAY = (
    ('gap_distance', 'Confidence gap (absolute)', 'Points · lower is better'),
    ('tail', 'Wrong at 90%+ confidence', 'Per 100 · lower is better'),
    ('accuracy', 'Accuracy', '% · higher is better'),
    ('coverage', 'Questions answered', '% of all questions'),
    ('score', 'Honest confidence-adjusted accuracy', 'Points · higher is better'),
)
ARMS = (('base', 'Before reward training'), ('binary', 'After accuracy-only training'),
        ('quadratic', 'After honest-confidence training'))
SCOPE_LABELS = {'same': 'Performance on the subject trained on',
                'different': 'Performance on different subjects',
                'gpqa': 'Performance on GPQA'}


def strict_mean(values):
    """An undefined gap stays undefined; never average a smaller set of runs."""
    values = list(values)
    return None if any(v is None or v == '' for v in values) else mean(float(v) for v in values)


def summarize_scopes(cells):
    """Average test subjects within each pair, then pairs with equal weight.

    Each family has six subject-specific pairs (three training subjects, two
    seeds). Off-subject tests are repeated measurements of those six pairs,
    not twelve independent replications. Base measurements are reused only to
    match the test mix; this does not create additional baseline observations.
    """
    if {r['model_family'] for r in cells} != set(FAMILIES):
        raise ValueError('Scope synthesis requires all three models')
    keys = [(r['model_family'], r['training_domain'], str(r['training_seed']),
             r['training_objective'], r['evaluation_domain']) for r in cells]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate scope source cell')
    source = dict(zip(keys, cells))
    pairs = []
    for family in FAMILIES:
        for train in DOMAINS:
            for seed in ('0', '1'):
                for scope in SCOPES:
                    tests = [train] if scope == 'same' else [d for d in DOMAINS if d != train] if scope == 'different' else ['gpqa']
                    pair = {'model_family': family, 'training_domain': train,
                            'training_seed': seed, 'scope': scope, 'levels': {}}
                    for arm, _ in ARMS:
                        selected = []
                        for test in tests:
                            key = (family, 'shared_format_control' if arm == 'base' else train,
                                   '' if arm == 'base' else seed, arm, test)
                            if key not in source:
                                raise ValueError(f'Missing scope source cell: {key}')
                            row = source[key]
                            if int(row['n']) != (198 if test == 'gpqa' else 300):
                                raise ValueError(f'Unexpected evaluation denominator: {key}')
                            selected.append(row)
                        pair['levels'][arm] = {m: strict_mean(r[m] for r in selected) for m in METRICS}
                    pairs.append(pair)
    results = []
    for family in (ALL_MODELS, *FAMILIES):
        for scope in SCOPES:
            own = [p for p in pairs if p['scope'] == scope
                   and (family == ALL_MODELS or p['model_family'] == family)]
            result = {'model_family': family, 'scope': scope, 'matched_pairs': len(own),
                      'test_subjects_per_pair': 2 if scope == 'different' else 1}
            for metric in METRICS:
                for arm, _ in ARMS:
                    result[f'{arm}_{metric}'] = strict_mean(p['levels'][arm][metric] for p in own)
                changes = [None if any(p['levels'][a][metric] is None for a in ('binary', 'quadratic'))
                           else p['levels']['quadratic'][metric] - p['levels']['binary'][metric] for p in own]
                result[f'{metric}_change'] = strict_mean(changes)
                defined = all(v is not None for v in changes)
                result[f'{metric}_change_min'] = min(changes) if defined else None
                result[f'{metric}_change_max'] = max(changes) if defined else None
                result[f'{metric}_positive_pairs'] = sum(v > 0 for v in changes) if defined else None
            results.append(result)
    return results


def write_scope_summary(root: Path):
    """Persist the synthesis beside its committed source cells for inspection."""
    directory = root / 'data/processed'
    with (directory / 'common_training_cells.csv').open() as handle:
        rows = summarize_scopes(list(csv.DictReader(handle)))
    with (directory / 'common_training_scope_summary.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def number(value):
    # Retain tenths for rare errors so a nonzero observed rate never reads "0".
    if value is None or value == '':
        return 'Not defined'
    value = float(value)
    return (f'{value:.1f}' if 0 < abs(value) < 1 else f'{value:.0f}').replace('-', '−')


def retained_improvement(same, different, metric):
    """Ratio of mean changes from the prepared model, never the reward contrast.

    Coverage is context, not an outcome where more is always better. A flat or
    worsening same-subject result cannot supply an improvement denominator.
    Negative outside gains remain negative; ratios are not clipped to 0–100%.
    """
    if metric == 'coverage':
        return None
    values = [r[f'{arm}_{metric}'] for r in (same, different) for arm in ('base', 'quadratic')]
    if any(v in (None, '') for v in values):
        return None
    direction = -1 if metric in ('gap_distance', 'tail') else 1
    before, after, other_before, other_after = map(float, values)
    gain = direction * (after - before)
    other_gain = direction * (other_after - other_before)
    return (100 * other_gain / gain, gain, other_gain) if gain > 1e-9 else None


def retention_text(same, different, metric):
    result = retained_improvement(same, different, metric)
    if result is None:
        return ('Context only' if metric == 'coverage' else 'Not defined', '')
    ratio, gain, other_gain = result
    unit = 'per 100' if metric == 'tail' else 'points'
    return (f'{ratio:.0f}%'.replace('-', '−'),
            f'{other_gain:.1f} of {gain:.1f} {unit}'.replace('-', '−'))


def scope_comparison_html(rows, family=ALL_MODELS, scopes=('same', 'different'), *, compact=False):
    """Use the earlier performance-table idiom with shared axes for both scopes.

    The phone layout transposes the same values into a compact numeric table,
    retaining all three training stages without a horizontal scroll or tabs.
    """
    selected = [next(r for r in rows if r['model_family'] == family and r['scope'] == scope) for scope in scopes]
    limits = {'gap_distance': (0, 60), 'tail': (0, 60), 'accuracy': (0, 100),
              'coverage': (0, 100), 'score': (-20, 60)}
    # One domain per metric for every model/scope, including the GPQA detail.
    for metric, _, _ in DISPLAY:
        values = [float(r[f'{a}_{metric}']) for r in rows for a, _ in ARMS if r[f'{a}_{metric}'] not in (None, '')]
        if not values:
            continue
        lo, hi = limits[metric]
        limits[metric] = (min(lo, math.floor(min(values)/10)*10), max(hi, math.ceil(max(values)/10)*10))

    def value_cell(row, arm, metric):
        value = row[f'{arm}_{metric}']
        label = number(value) + ('%' if metric in ('accuracy', 'coverage') and value not in (None, '') else '')
        return f'<span class="scope-value">{label}</span>'

    def bar_cell(row, arm, metric):
        value = row[f'{arm}_{metric}']
        lo, hi = limits[metric]
        def pos(v):
            return 5 + 110*(v-lo)/(hi-lo)
        ticks = sorted({lo, 0, hi/2, hi})
        grid = ''.join(f'<line x1="{pos(t):.1f}" x2="{pos(t):.1f}" y1="2" y2="13"/>'
                       f'<text x="{pos(t):.1f}" y="25" text-anchor="{"start" if t==lo else "end" if t==hi else "middle"}">{t:g}</text>' for t in ticks)
        bar = '' if value in (None, '') else f'<rect x="{min(pos(0),pos(float(value))):.1f}" y="5" width="{abs(pos(float(value))-pos(0)):.1f}" height="6"/>'
        return f'<td data-metric="{metric}">{value_cell(row,arm,metric)}<svg viewBox="0 0 120 28" aria-hidden="true">{grid}{bar}</svg></td>'

    if compact:
        if scopes != ('same', 'different'):
            raise ValueError('Compact comparison requires same and different subjects')
        same, different = selected
        # One baseline row is legitimate only when both subject mixes agree.
        def equal_baseline(metric):
            left, right = same[f'base_{metric}'], different[f'base_{metric}']
            if left in (None, '') or right in (None, ''):
                return left in (None, '') and right in (None, '')
            return math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-9)
        if not all(equal_baseline(m) for m in METRICS):
            raise ValueError('Cannot share unequal before-training baselines')
        groups = [(None, [(same, 'base', 'Before training'),
                          (same, 'quadratic', 'After training: same subject'),
                          (different, 'quadratic', 'After training: different subjects')])]
    else:
        groups = [(SCOPE_LABELS[r['scope']], [(r, arm, label) for arm, label in ARMS]) for r in selected]
    out = ['<div class="scope-comparison"><table class="scope-desktop"><thead><tr><th scope="col">Training and test</th>']
    out.extend(f'<th scope="col">{escape(label)}<span class="scope-unit">{escape(unit)}</span></th>' for _, label, unit in DISPLAY)
    out.append('</tr></thead>')
    for label, stages in groups:
        out.append('<tbody>')
        if label:
            out.append(f'<tr class="scope-group"><th colspan="6" scope="rowgroup">{label}</th></tr>')
        for row, arm, label in stages:
            out.append(f'<tr class="scope-arm scope-{arm}"><th scope="row">{label}</th>')
            out.extend(bar_cell(row, arm, m) for m, _, _ in DISPLAY)
            out.append('</tr>')
        out.append('</tbody>')
    if compact:
        out.append('<tfoot><tr class="scope-retained"><th scope="row">Improvement retained on other subjects</th>')
        for m, _, _ in DISPLAY:
            percent, detail = retention_text(same, different, m)
            out.append(f'<td data-retained="{m}"><strong>{percent}</strong><span class="scope-unit">{detail}</span></td>')
        out.append('</tr></tfoot>')
    out.append('</table><div class="scope-mobile">')
    if compact:
        out.append('<table><thead><tr><th rowspan="2" scope="col">Measure</th><th rowspan="2" scope="col">Before training</th><th colspan="2" scope="colgroup">After honest-confidence training</th></tr><tr><th scope="col">Same subject</th><th scope="col">Different subjects</th></tr></thead><tbody>')
        for m, label, unit in DISPLAY:
            out.append(f'<tr><th scope="row">{label}<span class="scope-unit">{unit}</span></th>')
            out.extend(f'<td>{value_cell(r,a,m)}</td>' for r,a in ((same,'base'),(same,'quadratic'),(different,'quadratic')))
            percent, detail = retention_text(same,different,m)
            out.append('</tr>')
            if m != 'coverage':
                out.append(f'<tr class="scope-retained-mobile"><td colspan="4"><strong>{percent} retained</strong> · {detail}</td></tr>')
        out.append('</tbody></table>')
    else:
        for row in selected:
            out.append(f'<table data-scope="{row["scope"]}"><caption>{SCOPE_LABELS[row["scope"]]}</caption><thead><tr><th scope="col">Measure</th>')
            out.extend(f'<th class="scope-{a}" scope="col">{label}</th>' for a, label in
                       (('base', 'Before reward training'), ('binary', 'Accuracy-only'), ('quadratic', 'Honest-confidence')))
            out.append('</tr></thead><tbody>')
            for metric, label, unit in DISPLAY:
                out.append(f'<tr><th scope="row">{label}<span class="scope-unit">{unit}</span></th>')
                out.extend(f'<td data-metric="{metric}">{value_cell(row,a,metric)}</td>' for a, _ in ARMS)
                out.append('</tr>')
            out.append('</tbody></table>')
    out.append('</div></div>')
    return ''.join(out)


def scope_doc_rows(rows, family=ALL_MODELS, scopes=('same', 'different'), *, compact=False):
    units = {'gap_distance': 'points', 'tail': 'per 100 questions',
             'accuracy': '%', 'coverage': '%', 'score': 'points'}
    result = [['Test scope', 'Training stage',
               *[f'{label} ({units[metric]})' for metric, label, _ in DISPLAY]]]
    if compact:
        same, different = [next(r for r in rows if r['model_family']==family and r['scope']==scope) for scope in ('same','different')]
        for scope, row, arm in [('Both',same,'base'),('Same subject',same,'quadratic'),('Different subjects',different,'quadratic')]:
            result.append([scope, 'Before training' if arm=='base' else 'After honest-confidence training',
                           *[number(row[f'{arm}_{m}']) for m,_,_ in DISPLAY]])
        result.append(['Improvement retained on other subjects', 'Relative to before training',
                       *['; '.join(filter(None,retention_text(same,different,m))) for m,_,_ in DISPLAY]])
        return result
    for scope in scopes:
        row = next(r for r in rows if r['model_family'] == family and r['scope'] == scope)
        for arm, label in ARMS:
            result.append([SCOPE_LABELS[scope], label, *[number(row[f'{arm}_{m}']) for m, _, _ in DISPLAY]])
    return result


CSS = '''
#fig-transfer { scroll-margin-top: 112px; }
.scope-comparison { font: 13px/1.4 Inter,sans-serif; }
.scope-comparison table { width: 100%; min-width: 0; border-collapse: collapse; table-layout: fixed; }
.scope-comparison th { text-transform: none; letter-spacing: normal; font-weight: 500; text-align: left; }
.scope-comparison .scope-desktop thead th { border-bottom: 1px solid var(--rule-strong); padding: 10px 8px 14px; vertical-align: top; }
.scope-comparison .scope-desktop th:first-child { width: 21%; }
.scope-unit { display: block; color: var(--text-muted); font: 11px/1.4 Inter,sans-serif; margin-top: 5px; }
.scope-desktop .scope-group th { padding: 24px 8px 12px; font-weight: 600; }
.scope-desktop .scope-arm th, .scope-desktop .scope-arm td { padding: 12px 8px 16px; border-bottom: 1px solid var(--rule); vertical-align: middle; }
.scope-value { display: block; font-variant-numeric: tabular-nums; color: var(--text); }
.scope-desktop svg { display: block; width: 100%; margin-top: 6px; overflow: visible; }
.scope-desktop svg line { stroke: var(--rule); stroke-width: .6; }
.scope-desktop svg text { fill: var(--text-muted); font: 8px Inter,sans-serif; }
.scope-base rect { fill: #9c9991; }
.scope-binary rect { fill: #af6813; }
.scope-quadratic rect { fill: #294c72; }
.scope-mobile { display: none; }
.scope-retained th, .scope-retained td { padding: 18px 8px; vertical-align: top; border-bottom: 1px solid var(--rule); }
.scope-retained th { font-weight: 600; }
@media(max-width:650px) {
 .scope-comparison .scope-desktop { display: none; }
 .scope-mobile { display: block; }
 .scope-mobile table + table { margin-top: 28px; }
 .scope-mobile caption { text-align: left; font-weight: 600; padding: 0 0 12px; }
 .scope-mobile th, .scope-mobile td { padding: 10px 5px; border-bottom: 1px solid var(--rule); font-size: 11px; }
 .scope-mobile th:first-child { width: 33%; }
 .scope-mobile thead th { border-bottom-color: var(--rule-strong); vertical-align: bottom; }
 .scope-mobile td { text-align: center; }
 .scope-mobile .scope-unit { font-size: 9px; }
 .scope-mobile .scope-binary { color: #995a10; }
 .scope-mobile .scope-quadratic { color: #294c72; }
 .scope-mobile .scope-value { font-size: 13px; }
 .scope-mobile .scope-retained-mobile td { text-align: left; padding: 5px 5px 14px; color: var(--text-muted); font-size: 10px; }
}
'''


SUMMARY_METRICS = [
    ('gap_distance', 'Absolute confidence gap', 'Points · lower is better', 60),
    ('tail', 'Wrong at 90%+ confidence', 'Per 100 questions · lower is better', 40),
    ('accuracy', 'Accuracy', '% of all questions · higher is better', 100),
    ('score', 'Honest confidence-adjusted accuracy', 'Points · higher is better', 100),
]

def summary_values(pair, metric):
    same, other = pair
    return [float(same['base_'+metric]), float(same['quadratic_'+metric]), float(other['quadratic_'+metric])]


def summary_number(value):
    """Round display labels only; preserve small nonzero values and raw ratios."""
    value = float(value)
    if 0 < value < 1:
        return '<1'
    if -1 < value < 0:
        return '>−1'
    return f'{value:.0f}'.replace('-', '−')


def summary_label(value, metric):
    return escape(summary_number(value)) + ('%' if metric in ('accuracy', 'coverage') else '')


def summary_ratio(pair, metric):
    result = retained_improvement(*pair, metric)
    if result is None:
        return '<span class="ratio-label">Not defined</span>'
    percent, gain, other_gain = result
    unit = 'per 100' if metric == 'tail' else 'points'
    return (f'<strong class="ratio" data-retained="{metric}" data-ratio="{percent}">{percent:.0f}%</strong>'
            '<span class="ratio-label">retained</span>'
            f'<span class="gain">{escape(summary_number(other_gain))} of {escape(summary_number(gain))} {unit}</span>')


def summary_context(pair):
    before, same, other = summary_values(pair, 'coverage')
    return (f'<p class="context"><strong>Questions answered:</strong> {summary_label(before,"coverage")} before training, '
            f'{summary_label(same,"coverage")} on the same subject and {summary_label(other,"coverage")} on other subjects after training. '
            'This is context, not an improvement measure.</p>')


def transfer_summary_html(pair):
    """Place measures across columns, with baseline and both scopes down rows.

    Reuse the same unrounded levels and retention calculation as the other
    variations. Only chart geometry and table orientation change here.
    """
    if any(not math.isclose(float(pair[0]['base_'+m]), float(pair[1]['base_'+m]), abs_tol=1e-9) for m, *_ in SUMMARY_METRICS):
        raise ValueError('Cannot share unequal before-training baselines')
    out = ['<div class="transfer-summary"><p class="scroll-hint">Scroll across to compare all four measures.</p>',
           '<div class="exhibit compact table-scroll" role="region" aria-label="Cross-subject performance comparison" tabindex="0">',
           ('<table class="column-table"><thead><tr><th scope="col" aria-label="Training and test">'
           '<span class="transfer-key"><i class="key-base" aria-hidden="true"></i>Before training</span>'
           '<span class="transfer-key"><i class="key-same" aria-hidden="true"></i>Same subject</span>'
           '<span class="transfer-key"><i class="key-other" aria-hidden="true"></i>Other subjects</span></th>')]
    out.extend(f'<th scope="col">{title}<span class="unit">{unit}</span></th>'
               for _, title, unit, _ in SUMMARY_METRICS)
    out.append('</tr></thead><tbody>')
    for index, (stage, kind) in enumerate((('Before training', 'base'),
                                          ('After training: same subject', 'same'),
                                          ('After training: other subjects', 'other'))):
        out.append(f'<tr data-stage="{kind}"><th scope="row">{stage}</th>')
        for metric, _, _, maximum in SUMMARY_METRICS:
            value = summary_values(pair, metric)[index]
            if not 0 <= value <= maximum:
                raise ValueError('Rate outside chart scale')
            # A common SVG inset keeps end labels inside each table cell. The
            # 20-point and 25-point ticks match the familiar table chart idiom.
            step = 25 if maximum == 100 else 10 if maximum == 40 else 20
            def pos(v, limit=maximum):
                return 5 + 110 * v / limit
            grid = ''.join(
                f'<line x1="{pos(t):.6f}" x2="{pos(t):.6f}" y1="1" y2="13"/>'
                f'<text x="{pos(t):.6f}" y="25" text-anchor="{"start" if t == 0 else "end" if t == maximum else "middle"}">{t}</text>'
                for t in range(0, maximum + 1, step))
            out.append(f'<td data-metric="{metric}" data-value="{value}" data-max="{maximum}">'
                       f'<span class="column-value">{summary_label(value, metric)}</span>'
                       f'<svg class="column-plot" viewBox="0 0 120 29" aria-hidden="true">{grid}'
                       f'<rect class="bar-{kind}" x="5" y="4" width="{110 * value / maximum:.6f}" height="6"/></svg></td>')
        out.append('</tr>')
    out.append('</tbody><tfoot><tr><th scope="row">Improvement retained on other subjects</th>')
    out.extend(f'<td>{summary_ratio(pair, metric)}</td>' for metric, *_ in SUMMARY_METRICS)
    return ''.join(out) + '</tr></tfoot></table></div>' + summary_context(pair) + '</div>'


SUMMARY_CSS = """
#fig-transfer-summary .fig-body {border:0;padding:0;background:none;}
#fig-transfer-summary .column-plot {height:29px;}
/* Shared meaning and geometry for the intervention and transfer tables.
   Accuracy-only remains a distinct control; transfer distinguishes test scope. */
.transfer-summary, .intervention-comparison {
 --comparison-base:#9b9991; --comparison-after:#294c72; --comparison-control:#a8661a; --comparison-other:#317d78;
}
#fig-bars .fig-body {padding:0;background:none;}
/* Anchor the visually hidden level labels inside the scrolling frame. */
.intervention-comparison {position:relative;max-width:820px;overflow-x:auto;padding:0 6px;
 background:linear-gradient(to bottom,rgba(36,36,34,.03),transparent 72%);}
.intervention-comparison:focus-visible {outline:2px solid #294c72;outline-offset:3px;}
.intervention-comparison .comparison-head, .intervention-comparison .intervention-card {
 grid-template-columns:24% repeat(4,minmax(0,1fr));column-gap:0;min-width:668px;padding:0;
}
.intervention-comparison .comparison-head {display:grid;}
.intervention-comparison .comparison-heading {display:block;padding:11px 10px;
 font:400 11px/1.5 Inter,sans-serif;color:var(--text-muted);}
.intervention-comparison .comparison-heading b {font-weight:400;}
.intervention-comparison .comparison-heading span {font:400 10.5px/1.5 Inter,sans-serif;margin-top:5px;}
.intervention-comparison .comparison-heading:first-child span {margin-top:0;margin-bottom:3px;}
.intervention-comparison .intervention-label, .intervention-comparison .comparison-metric {padding:4px 10px;}
.intervention-comparison .intervention-label {grid-column:auto;}
.essay-fig .intervention-comparison .intervention-label h3 {font:400 13px/1.55 Inter,sans-serif;margin:0;}
.intervention-comparison .metric-values {padding-left:0;gap:6px;}
.intervention-comparison .metric-level {font:400 14px/21px Inter,sans-serif;}
.intervention-comparison .metric-level b {font-weight:400;color:var(--text);}
.intervention-comparison .metric-level + .metric-level::before {margin-right:6px;}
#fig-bars .metric-pair {height:36px;margin-top:2px;}
#fig-bars .training-level .metric-pair {height:29px;}
.intervention-comparison .bar-tick {font:9px Inter,sans-serif;}
.intervention-comparison .level-bar.baseline,.intervention-comparison .level-bar.untuned {fill:var(--comparison-base);}
.intervention-comparison .level-bar.after {fill:var(--comparison-after);}
.intervention-comparison .level-bar.before {fill:var(--comparison-control);}
.intervention-comparison .bar-key i {background:var(--comparison-base);}
.intervention-comparison .bar-key.after i {background:var(--comparison-after);}
.intervention-comparison .bar-key.control i {background:var(--comparison-control);}
.intervention-comparison .comparison-method {padding:9px 10px 5px;min-width:668px;font:11px/1.5 Inter,sans-serif;}
.intervention-comparison .comparison-method b {font-size:12px;}
.intervention-comparison .comparison-metric h4,.intervention-comparison .metric-direction {display:none;}
.comparison-scroll-hint {display:none;font:11px/1.5 Inter,sans-serif;color:var(--text-muted);margin:0 0 8px;}
@media(max-width:750px){.comparison-scroll-hint {display:block;}}
/* Measures follow the essay's column layout. Each stage repeats the same
   metric-specific axis, so comparisons down a column never change scale. */
.transfer-summary .compact { padding:0 6px; background:linear-gradient(to bottom,rgba(36,36,34,.03),transparent 72%); }
.transfer-summary .column-table { border-collapse:collapse; table-layout:fixed; width:100%; min-width:680px; }
.transfer-summary .column-table th, .transfer-summary .column-table td { text-align:left; vertical-align:middle; border-bottom:1px solid var(--rule); padding:10px 10px; }
.transfer-summary .column-table th:first-child { width:24%; }
.transfer-summary .column-table thead th { vertical-align:top; font-size:11px; line-height:1.5; font-weight:400; color:var(--text-muted, #666762); padding-top:11px; padding-bottom:11px; border-bottom-color:#b5b1a8; }
.transfer-summary .column-table tbody th, .transfer-summary .column-table tbody td { padding-top:4px; padding-bottom:4px; }
.transfer-summary .column-table tbody th { font-size:13px; line-height:1.55; font-weight:400; }
.transfer-summary .column-table .unit { font-size:10.5px; margin-top:5px; }
.transfer-summary .column-value { display:block; font-size:14px; line-height:21px; margin-bottom:2px; }
.transfer-summary .column-plot { display:block; width:100%; height:29px; overflow:visible; }
.transfer-summary .column-plot line { stroke:var(--rule); stroke-width:.7; }
.transfer-summary .column-plot text { fill:var(--text-muted, #666762); font-size:9px; }
.transfer-summary .bar-other { fill:var(--comparison-other); stroke:none; }
.transfer-summary .column-table tfoot th { font-size:12px; font-weight:600; }
.transfer-summary .column-table tfoot td { vertical-align:top; padding-top:10px; }
.transfer-summary .ratio { font-size:16px; color:var(--text, #242422); }
.transfer-summary .ratio-label { display:none; }
.transfer-summary .gain { font-size:10.5px; line-height:1.5; margin-top:5px; }
.transfer-summary .context { font-size:12.5px; line-height:1.5; margin-top:9px; }
.transfer-summary .table-scroll { overflow-x:auto; }
.transfer-summary .table-scroll:focus-visible { outline:2px solid #294c72; outline-offset:3px; }
.transfer-summary .scroll-hint { display:none; font:11px/1.5 Inter,sans-serif; color:var(--text-muted, #666762); margin:0 0 8px; }
@media(max-width:750px) {
 .transfer-summary .column-table th, .transfer-summary .column-table td { padding-left:9px; padding-right:9px; }
 .transfer-summary .scroll-hint { display:block; }
 .transfer-summary .context { font-size:12px; }
}
.transfer-summary {font:13px/1.5 Inter,sans-serif;font-variant-numeric:tabular-nums;}
.transfer-summary .compact {border-top:1px solid var(--text, #242422);}
.transfer-summary .column-table {margin:0;}
.transfer-summary .column-table th {text-transform:none;letter-spacing:normal;background:transparent;}
.transfer-summary .column-table .unit {display:block;line-height:1.5;font-weight:400;}
.transfer-summary .column-plot .bar-base {fill:var(--comparison-base);}
.transfer-summary .column-plot .bar-same {fill:var(--comparison-after);}
.transfer-summary .column-plot .bar-other {fill:var(--comparison-other);}
.transfer-summary .transfer-key {display:flex;align-items:center;gap:6px;margin:0 0 3px;font:10.5px/1.5 Inter,sans-serif;}
.transfer-summary .transfer-key i {display:inline-block;width:16px;height:6px;flex:none;}
.transfer-summary .key-base {background:var(--comparison-base);}
.transfer-summary .key-same {background:var(--comparison-after);}
.transfer-summary .key-other {background:var(--comparison-other);}
.transfer-summary .gain {display:block;color:var(--text-muted, #666762);font-weight:400;}
.transfer-summary .context {color:var(--text-muted, #666762);max-width:820px;}
.transfer-summary .context strong {color:var(--text, #242422);font-weight:600;}

"""
