"""Readable train-on-A/test-on-B comparisons for the common training matrix.

The display uses numbers in aligned cells, with a light color cue for direction.
It never averages different test subjects into an unspecified transfer result.
"""
from html import escape
from statistics import mean

FAMILIES=('Qwen3 8B','GPT-OSS 20B','Nemotron 3 Nano 30B')
DOMAINS=('math','medicine','ethics')
TESTS=(*DOMAINS,'gpqa')
LABELS={'math':'Math','medicine':'Medicine','ethics':'Ethics','gpqa':'GPQA'}
METRICS={
 'score':('Honest confidence-adjusted accuracy','points; higher is better',1),
 'accuracy':('Accuracy','percentage points; higher is better',1),
 'gap_distance':('Absolute average confidence gap','points; lower is better',-1),
 'tail':('Wrong at 90%+ confidence','per 100 questions; lower is better',-1),
 'coverage':('Questions answered','percentage points; usable answers as a share of all questions',0),
}

CSS='''
#tbl-behavior-summary { scroll-margin-top: 112px; }
.outcome-comparison { font: 13px/1.45 Inter,sans-serif; }
.outcome-comparison table { width: 100%; min-width: 0; table-layout: fixed; border-collapse: collapse; }
.outcome-comparison th { text-align: left; font-weight: 500; text-transform: none; letter-spacing: normal; }
.outcome-comparison small { display: block; font: 11px/1.4 Inter,sans-serif; color: var(--text-muted); margin-top: 5px; }
.outcome-comparison th, .outcome-comparison td { font: 13px/1.45 Inter,sans-serif; padding: 10px 8px; border-bottom: 1px solid var(--rule); vertical-align: middle; }
.outcome-comparison thead th { font-weight: 600; color: var(--text); vertical-align: top; border-bottom-color: var(--rule-strong); }
.outcome-comparison tbody th { font-weight: 500; }
.outcome-desktop th:first-child { width: 22%; }
.outcome-legend { display: flex; flex-wrap: wrap; gap: 8px 20px; margin: 12px 0 5px; }
.outcome-legend span::before { content: ''; display: inline-block; width: 16px; height: 5px; margin: 0 6px 2px 0; background: currentColor; }
.outcome-scale { font: 11px/1.5 Inter,sans-serif; color: var(--text-muted); margin: 0 0 12px; }
.outcome-binary { color: #af6813; }
.outcome-quadratic { color: #294c72; }
.outcome-rate { display: flex; gap: 7px; align-items: center; margin: 4px 0; }
.outcome-rate svg, .outcome-axis svg { width: 100%; min-width: 0; flex: 1; }
.outcome-rate svg rect { fill: currentColor; }
.outcome-rate svg line { stroke: var(--rule); stroke-width: .5; }
.outcome-rate span, .outcome-axis span { width: 55px; flex-shrink: 0; text-align: right; font-variant-numeric: tabular-nums; }
.outcome-comparison .outcome-change { color: #555551; margin-top: 4px; font: 500 12px/1.45 Inter,sans-serif; }
#tbl-behavior-summary .outcome-strip { height: 16px; }
.outcome-axis { display:flex;align-items:center;gap:7px; }
#tbl-behavior-summary .outcome-axis svg { height:14px; }
.outcome-axis text { font:9px Inter,sans-serif;fill:var(--text-muted); }
.outcome-rate svg .outcome-zero { stroke: #777770; stroke-width: 1; }
.outcome-change span { width: 55px; }
.outcome-legend .outcome-change-key { color: #555551; }
.outcome-mobile { display: none; }
@media(max-width:600px) {
 .outcome-desktop { display: none; }
 .outcome-comparison .outcome-legend { gap:5px 14px;font-size:11px; }
 .outcome-mobile { display: block; }
 .outcome-mobile table + table { margin-top: 24px; }
 .outcome-mobile caption { text-align: left; font-weight: 600; padding-bottom: 8px; }
 .outcome-mobile th:first-child { width: 34%; }
 .outcome-mobile th, .outcome-mobile td { padding: 12px 4px; font-size: 12px; }
 .outcome-mobile .outcome-change { margin-top: 9px; }
 .outcome-mobile td { text-align: right; font-variant-numeric: tabular-nums; }
}

.transfer-exhibit { clear: both; max-width: 880px; margin: 28px 0; }
.transfer-exhibit .transfer-controls { display: flex; flex-wrap: wrap; gap: 7px; margin: 14px 0 18px; }
.transfer-exhibit button { font: 12px/1.35 Inter,sans-serif; background: transparent; color: var(--text); border: 1px solid var(--rule); padding: 7px 10px; cursor: pointer; }
.transfer-exhibit button[aria-pressed="true"] { background: #294c72; border-color: #294c72; color: white; }
.transfer-exhibit .transfer-cell-button { border: 0; padding: 0; width: 100%; color: inherit; background: transparent; }
.transfer-exhibit .transfer-cell-button:focus-visible { outline: 2px solid #294c72; outline-offset: 4px; }
.transfer-exhibit .transfer-cell-detail { font: 12px/1.5 Inter,sans-serif; margin: 12px 0 0; }
.transfer-exhibit .transfer-panel[hidden] { display: none; }
.transfer-exhibit .transfer-direction { font: 13px/1.5 Inter,sans-serif; margin-bottom: 14px; }
.transfer-model { margin: 0 0 28px; }
.transfer-model h4 { font: 600 15px/1.5 Inter,sans-serif; margin: 0 0 8px; }
.transfer-exhibit .transfer-matrix { min-width: 0; width: 100%; border-collapse: collapse; table-layout: fixed; font: 13px/1.4 Inter,sans-serif; }
.transfer-matrix th { text-align: center; font-weight: 500; padding: 9px 4px; }
.transfer-matrix thead th { border-bottom: 1px solid var(--rule-strong); text-transform: none; letter-spacing: normal; }
.transfer-matrix thead th:first-child { text-align: left; width: 20%; white-space: nowrap; }
.transfer-matrix tbody th { text-align: left; }
.transfer-matrix td { text-align: center; padding: 12px 4px; border-bottom: 1px solid var(--rule); }
.transfer-matrix .transfer-value { font-size: 21px; font-variant-numeric: tabular-nums; display: block; }
.transfer-matrix .transfer-levels { display: block; color: var(--text-muted); font-size: 11px; margin-top: 4px; font-variant-numeric: tabular-nums; }
.transfer-matrix .transfer-improved { background: #edf3ef; color: #225d4e; }
.transfer-matrix .transfer-worsened { background: #f5ecef; color: #833657; }
.transfer-matrix .transfer-same-subject { box-shadow: inset 0 0 0 1px #b7b2a9; }
.transfer-matrix .transfer-gpqa { border-left: 1px solid var(--rule); }
.transfer-matrix .transfer-row-label small { display: block; color: var(--text-muted); font-size: 10px; font-weight: 400; }
.transfer-key { font: 12px/1.5 Inter,sans-serif; color: var(--text-muted); margin-top: 10px; }
@media(max-width:600px) {
 #tbl-behavior-summary table.essay, #tbl-common-pushback table.essay, #tbl-common-thresholds table.essay {
   min-width: 0; width: 100%; table-layout: fixed;
 }
 #tbl-behavior-summary table.essay th, #tbl-behavior-summary table.essay td,
 #tbl-common-pushback table.essay th, #tbl-common-pushback table.essay td,
 #tbl-common-thresholds table.essay th, #tbl-common-thresholds table.essay td {
   padding: 9px 4px; white-space: normal; font-size: 11px;
 }
 #tbl-behavior-summary table.essay th:first-child, #tbl-common-pushback table.essay th:first-child,
 #tbl-common-thresholds table.essay th:first-child { width: 29%; }
 #tbl-behavior-summary .sub, #tbl-common-pushback .sub, #tbl-common-thresholds .sub {
   font-size: 9px; line-height: 1.4; white-space: normal;
 }

 .transfer-exhibit .transfer-matrix { font-size: 11px; }
 .transfer-matrix thead th:first-child { width: 19%; }
 .transfer-matrix .transfer-value { font-size: 17px; }
 .transfer-matrix .transfer-levels { font-size: 9px; }
 .transfer-matrix td { padding: 11px 2px; }
 .transfer-exhibit button { font-size: 11px; }
}
'''

JS='''
document.querySelectorAll('.transfer-exhibit').forEach(function(exhibit) {
  exhibit.querySelectorAll('[data-transfer-detail]').forEach(function(button) {
    button.addEventListener('click', function() {
      var detail = document.getElementById(button.dataset.detailTarget);
      detail.textContent = button.dataset.transferDetail;
      detail.hidden = false;
    });
  });
  exhibit.querySelectorAll('[data-transfer-metric]').forEach(function(button) {
    button.addEventListener('click', function() {
      var metric = button.dataset.transferMetric;
      exhibit.querySelectorAll('[data-transfer-metric]').forEach(function(other) {
        other.setAttribute('aria-pressed', String(other === button));
      });
      exhibit.querySelectorAll('[data-transfer-panel]').forEach(function(panel) {
        panel.hidden = panel.dataset.transferPanel !== metric;
      });
    });
  });
});
'''


def signed(value):
    rounded=round(value,1)
    return ('+' if rounded>0 else '−' if rounded<0 else '')+f'{abs(rounded):.1f}'


def behavior_summary(external,prudence):
    """Collapse test settings within a seed before measuring run variation."""
    specs=[('Truth under pressure',external,'pressure_truth_rate',
            lambda r:r['family']=='honesty under pressure',1),
           ('Instruction-hierarchy accuracy',external,'accuracy',
            lambda r:r['family']=='instruction hierarchy',1),
           ('Unauthorized shortcuts',prudence,'integrity_unauthorized_shortcut_rate',
            lambda r:r['framing']=='neutral',-1)]
    result=[]
    for label,source,field,predicate,direction in specs:
        cells={}
        for family in FAMILIES:
            levels={}
            for arm in ('binary','quadratic'):
                for seed in (0,1):
                    selected=[r for r in source if r['model_family']==family
                              and r['training_objective']==arm and str(r['training_seed'])==str(seed)
                              and predicate(r)]
                    if not selected or any(r[field]=='' for r in selected):
                        raise ValueError(f'missing behavior metric: {family}/{field}/{arm}/{seed}')
                    levels[arm,seed]=100*mean(float(r[field]) for r in selected)
            changes=[levels['quadratic',seed]-levels['binary',seed] for seed in (0,1)]
            cells[family]={'binary':mean(levels['binary',seed] for seed in (0,1)),
                           'quadratic':mean(levels['quadratic',seed] for seed in (0,1)),
                           'change':mean(changes),'min':min(changes),'max':max(changes),'pairs':2}
        result.append({'label':label,'cells':cells,'improving_direction':direction})
    return result


def pressure_summary(rows):
    """Keep receptiveness to wrong and right advice together for every model."""
    result=[]
    for field,label in (('wrong_adoption','Accepts incorrect pushback'),('right_adoption','Accepts valid correction')):
        cells={}
        for family in FAMILIES:
            selected={(r['training_objective'],str(r['training_seed'])):r
                      for r in rows if r['model_family']==family and r['training_objective']!='base'}
            expected={(arm,str(seed)) for arm in ('binary','quadratic') for seed in (0,1)}
            if set(selected)!=expected:raise ValueError('incomplete pushback pairs')
            changes=[];levels={}
            for arm,seed in expected:
                value=selected[arm,seed][field]
                if value=='':raise ValueError('undefined adoption rate must be disclosed')
                levels[arm,seed]=100*float(value)
            for seed in ('0','1'):
                changes.append(levels['quadratic',seed]-levels['binary',seed])
            cells[family]={'change':mean(changes),'min':min(changes),'max':max(changes),'pairs':2,
                           'binary':mean(levels['binary',seed] for seed in ('0','1')),
                           'quadratic':mean(levels['quadratic',seed] for seed in ('0','1'))}
        result.append({'label':label,'cells':cells})
    return result


def behavior_rows(summary):
    return [[r['label']]+[f"{signed(r['cells'][f]['change'])}"
             f"{{sub:{signed(r['cells'][f]['min'])} to {signed(r['cells'][f]['max'])}}}"
             for f in FAMILIES] for r in summary]


def paired_outcome_table(summary):
    """Compare levels and changes on one scale, without amplifying small effects.

    Means come from the existing within-seed aggregation. The compact exhibit
    does not reweight settings or interpret a trained control as an untreated
    baseline. Seed ranges remain in the adjoining disclosure/technical notes.
    """
    # Rates and changes share the same coordinate transform and zero. A
    # negative quarter of the axis accommodates decreases without magnifying
    # the change bars relative to the rates directly above them.
    ticks = (-25, 0, 25, 50, 75, 100)

    def pos(value):
        return 4 + (value + 25)

    def strip(value):
        if not -25 <= value <= 100:
            raise ValueError('Broader-behavior value exceeds shared -25 to 100 scale')
        grid = ''.join(f'<line class="{"outcome-zero" if t == 0 else "outcome-grid"}" '
                       f'x1="{pos(t)}" x2="{pos(t)}" y1="1" y2="15"/>' for t in ticks)
        return ('<svg class="outcome-strip" viewBox="0 0 133 16" aria-hidden="true">'
                + grid + f'<rect x="{pos(min(value, 0)):.6f}" y="5" height="6" '
                f'width="{abs(value):.6f}"/></svg>')

    def axis():
        marks = ''.join(f'<text x="{pos(t)}" y="10" text-anchor="'
                        f'{"start" if t == -25 else "end" if t == 100 else "middle"}">'
                        f'{str(t).replace("-", "−")}</text>' for t in ticks)
        return ('<div class="outcome-axis" aria-hidden="true">'
                '<svg viewBox="0 0 133 14">' + marks + '</svg><span></span></div>')

    def bars(cell):
        parts=[]
        for arm in ('binary','quadratic'):
            value=cell[arm]
            label='Accuracy-only training' if arm=='binary' else 'Honest-confidence training'
            if not 0 <= value <= 100:
                raise ValueError('Outcome bars require percentage rates')
            parts.append(f'<div class="outcome-rate outcome-{arm}" data-rate="{value}">'
                         +strip(value)+f'<span aria-label="{label}: {value:.1f}%">{value:.1f}%</span></div>')
        return ''.join(parts)

    def change_bar(cell):
        delta=cell['change']
        return (f'<div class="outcome-rate outcome-change" data-delta="{delta}">'
                +strip(delta)+f'<span aria-label="Change: {signed(delta)} percentage points">{signed(delta)} pp</span></div>'
                +axis())

    out=[('<div class="outcome-comparison"><div class="outcome-legend">'
         '<span class="outcome-binary">Accuracy-only training</span>'
         '<span class="outcome-quadratic">Honest-confidence training</span>'
         '<span class="outcome-change-key">Change</span></div>'
         '<p class="outcome-scale">All bars share one axis: −25 to 100. Rates are percentages; changes are percentage points (pp).</p>'
         '<table class="outcome-desktop"><thead><tr><th scope="col">Model</th>')]
    for row in summary:
        direction='Higher is better' if row['improving_direction']>0 else 'Lower is better'
        out.append(f'<th scope="col">{escape(row["label"])}<small>{direction}</small></th>')
    out.append('</tr></thead><tbody>')
    for family in FAMILIES:
        out.append(f'<tr><th scope="row">{escape(family)}</th>')
        for row in summary:
            cell=row['cells'][family]
            out.append(f'<td data-outcome-family="{escape(family)}" data-outcome="{escape(row["label"])}" '
                       f'data-before="{cell["binary"]}" data-after="{cell["quadratic"]}" data-change="{cell["change"]}">'
                       +bars(cell)+change_bar(cell))
            out.append('</td>')
        out.append('</tr>')
    out.append('</tbody></table><div class="outcome-mobile">')
    for family in FAMILIES:
        out.append(f'<table><caption>{escape(family)}</caption><thead><tr><th scope="col">Test</th>'
                   '<th scope="col">Rates and change</th></tr></thead><tbody>')
        for row in summary:
            cell=row['cells'][family]
            direction='Higher' if row['improving_direction']>0 else 'Lower'
            out.append(f'<tr><th scope="row">{escape(row["label"])}<small>{direction} is better</small>'
                       '</th><td>'+bars(cell)+change_bar(cell)+'</td></tr>')
        out.append('</tbody></table>')
    out.append('</div></div>')
    return ''.join(out)


def matrix_html(rows):
    """Every family, training subject and test subject must have a real cell."""
    data={}
    for row in rows:
        key=(row['model_family'],row['training_domain'],row['evaluation_domain'])
        if key in data:raise ValueError(f'duplicate transfer summary: {key}')
        data[key]=row
    expected={(family,train,test) for family in FAMILIES for train in DOMAINS for test in TESTS}
    missing=expected-set(data)
    if missing:raise ValueError(f'incomplete transfer exhibit: {sorted(missing)}')
    seed_counts={int(data[key]['matched_pairs']) for key in expected}
    if len(seed_counts)!=1:raise ValueError('unequal model/subject replication in common exhibit')
    count=seed_counts.pop()
    out=['<div class="transfer-exhibit" id="fig-transfer">',
         '<p class="tbl-title">If we train on one subject, how much carries to another?</p>',
         ('<p class="tbl-sub">Read across a row: train on the subject at left, test on each subject across the top. '
         'Each number is the change from accuracy-only to honest-confidence training.</p>'),
         '<div class="transfer-controls" role="group" aria-label="Transfer measure">']
    for key,(label,_,_) in METRICS.items():
        out.append(f'<button type="button" data-transfer-metric="{key}" aria-controls="transfer-{key}" aria-pressed="{str(key=="score").lower()}">{escape(label)}</button>')
    out.append('</div>')
    for metric,(label,unit,direction) in METRICS.items():
        hidden='' if metric=='score' else ' hidden'
        out.append(f'<div class="transfer-panel" id="transfer-{metric}" data-transfer-panel="{metric}"{hidden}>')
        guide='Green indicates improvement; plum indicates worsening.' if direction else 'Higher coverage is not necessarily better; read it alongside accuracy and score.'
        out.append(f'<p class="transfer-direction"><strong>{escape(label)}</strong>: {unit}. {guide}</p>')
        for family_index,family in enumerate(FAMILIES):
            detail_id=f'transfer-detail-{metric}-{family_index}'
            out.append(f'<section class="transfer-model"><h4>{escape(family)}</h4>')
            out.append(f'<table class="transfer-matrix" aria-label="{escape(family)}: {escape(label)} transfer"><thead><tr><th scope="col">Train on ↓<br>Test on →</th>')
            out.extend(f'<th scope="col">{LABELS[test]}</th>' for test in TESTS)
            out.append('</tr></thead><tbody>')
            for train in DOMAINS:
                out.append(f'<tr><th class="transfer-row-label" scope="row">{LABELS[train]}</th>')
                for test in TESTS:
                    row=data[family,train,test]
                    if row[f'{metric}_change']=='':
                        title=f'{LABELS[train]} training, {LABELS[test]} test: the gap comparison is undefined because at least one checkpoint gave no usable answers. All scheduled questions still count in accuracy, score and coverage.'
                        safe=escape(title,quote=True)
                        classes=('transfer-same-subject ' if train==test else '')+('transfer-gpqa' if test=='gpqa' else '')
                        out.append(f'<td class="{classes}" title="{safe}"><button type="button" class="transfer-cell-button" '
                                   f'aria-label="{safe}" aria-controls="{detail_id}" data-detail-target="{detail_id}" '
                                   f'data-transfer-detail="{safe}">Not defined</button></td>')
                        continue
                    delta=float(row[f'{metric}_change'])
                    before=float(row[f'binary_{metric}']);after=float(row[f'quadratic_{metric}'])
                    classes=['transfer-improved' if delta*direction>0 else 'transfer-worsened' if delta*direction<0 else '']
                    if train==test:classes.append('transfer-same-subject')
                    if test=='gpqa':classes.append('transfer-gpqa')
                    lo=float(row[f'{metric}_change_min']);hi=float(row[f'{metric}_change_max'])
                    title=f'{LABELS[train]} training, {LABELS[test]} test: change {signed(delta)}; accuracy-only {before:.1f}, honest-confidence {after:.1f}. Range across {count} seeds: {signed(lo)} to {signed(hi)}. {int(row["questions_per_arm"])} questions per checkpoint.'
                    safe=escape(title,quote=True)
                    out.append(f'<td class="{" ".join(classes)}" title="{safe}"><button type="button" class="transfer-cell-button" '
                               f'aria-label="{safe}" aria-controls="{detail_id}" data-detail-target="{detail_id}" '
                               f'data-transfer-detail="{safe}"><span class="transfer-value">{signed(delta)}</span></button></td>')
                out.append('</tr>')
            out.append(f'</tbody></table><p class="transfer-cell-detail" id="{detail_id}" aria-live="polite" hidden></p></section>')
        out.append('</div>')
    out.append(f'<p class="transfer-key">Outlined cells test the training subject; all other cells test transfer. '
               f'GPQA never enters fine-tuning. Each cell averages the same {count} matched seeds; select a cell for the underlying levels and range. '
               'Use accuracy and questions answered to assess the tradeoff behind a score change. '
               'Individual seed results are linked in the <a href="#training-notes">training methods</a>.</p></div>')
    return ''.join(out)
