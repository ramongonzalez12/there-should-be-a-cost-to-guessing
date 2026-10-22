"""Independently check the common training exports and their current exhibits."""
import csv
import math
import re
from collections import Counter
from html import escape
from pathlib import Path
from statistics import mean

FAMILIES=('Qwen3 8B','GPT-OSS 20B','Nemotron 3 Nano 30B')
SCOPES=('pooled','math','medicine','ethics')
DOMAINS=('math','medicine','ethics','gpqa')
METRICS=('accuracy','score','gap','gap_distance','tail','coverage','invalid')


def verify(root: Path, essay: str, notes: str, check):
    """Append named checks using source cells, not the presentation helpers."""
    def read(name):
        with (root/'data/processed'/('common_training_'+name+'.csv')).open() as handle:
            return list(csv.DictReader(handle))

    # The chart now shows levels as well as changes: independently recover
    # each bar from the source settings, retaining within-seed weighting.
    behavior_specs=[('Truth under pressure','external_levels','pressure_truth_rate',
                     lambda r:r['family']=='honesty under pressure'),
                    ('Instruction-hierarchy accuracy','external_levels','accuracy',
                     lambda r:r['family']=='instruction hierarchy'),
                    ('Unauthorized shortcuts','prudence_levels','integrity_unauthorized_shortcut_rate',
                     lambda r:r['framing']=='neutral')]
    plotted=re.findall(r'data-outcome-family="([^"]+)" data-outcome="([^"]+)" '
                       r'data-before="([^"]+)" data-after="([^"]+)" data-change="([^"]+)"',essay)
    expected={}
    for label,source,field,predicate in behavior_specs:
        rows=read(source)
        for family in FAMILIES:
            levels=[mean(100*mean(float(r[field]) for r in rows if r['model_family']==family
                                 and r['training_objective']==arm and r['training_seed']==str(seed) and predicate(r))
                         for seed in (0,1)) for arm in ('binary','quadratic')]
            expected[family,label]=(*levels,levels[1]-levels[0])
    check('broader behavior bars: all nine levels and changes match retained source settings',
          len(plotted)==9 and {(f,m) for f,m,*_ in plotted}==set(expected)
          and all(all(math.isclose(float(v),want,abs_tol=1e-9) for v,want in zip(values,expected[f,m]))
                  for f,m,*values in plotted))
    # Verify actual rectangle geometry, not just its adjacent printed number.
    # Desktop and phone use the same units and zero for rates and changes.
    deltas=re.findall(r'class="outcome-rate outcome-change" data-delta="([^"]+)".*?'
                      r'<rect x="([^"]+)" y="5" height="6" width="([^"]+)"',essay)
    check('broader behavior: all change bars retain sign and shared scale on desktop and phone',
          len(deltas)==18
          and Counter(round(float(d),8) for d,_,_ in deltas)==
              Counter(round(values[2],8) for values in expected.values() for _ in range(2))
          and all(math.isclose(float(w),abs(float(d)),abs_tol=1e-6)
                  and math.isclose(float(x),29+min(float(d),0),abs_tol=1e-6)
                  for d,x,w in deltas))
    rates=re.findall(r'class="outcome-rate outcome-(?:binary|quadratic)" data-rate="([^"]+)".*?'
                     r'<rect x="([^"]+)" y="5" height="6" width="([^"]+)"',essay)
    check('broader behavior: rate bars use the same zero and units as changes',
          len(rates)==36 and all(math.isclose(float(x),29,abs_tol=1e-6)
                                 and math.isclose(float(w),float(v),abs_tol=1e-6)
                                 for v,x,w in rates))
    check('broader behavior: repeated wrong-decision graphic removed, seed ranges retained',
          'id="fig-prudence"' not in essay and 'Do wrong decisions carry less false certainty?' not in essay
          and 'Exact changes and the two-seed ranges' in essay)
    cells=read('cells');pairs=read('pairs');summary=read('summary')
    protocol=read('protocol_audit')
    expected_runs={(f,s,str(seed),a) for f in FAMILIES for s in SCOPES
                   for seed in (0,1) for a in ('binary','quadratic')}
    check('executed protocol: all 48 runs share the prescribed settings',
          len(protocol)==48 and {(r['model_family'],r['training_domain'],r['training_seed'],r['reward'])
                                for r in protocol}==expected_runs
          and all(all(r[k]==v for k,v in {'requested_steps':'60','effective_steps':'60',
                     'batch_size':'4','group_size':'8','data_items':'240','rollouts':'1920',
                     'max_tokens':'512','lora_rank':'32','health_policy':'count_as_wrong'}.items())
                  and float(r['learning_rate'])==4e-5 for r in protocol))
    for scope in SCOPES:
        selected=[r for r in protocol if r['training_domain']==scope]
        check('executed questions identical across models: '+scope,len({r['data_sha256'] for r in selected})==1)
        for seed in ('0','1'):
            check('executed question order identical across models and rewards: '+scope+'/'+seed,
                  len({r['executed_item_order_sha256'] for r in selected if r['training_seed']==seed})==1)
    identity=lambda r:(r['model_family'],r['training_domain'],r['training_seed'],r['evaluation_domain'])
    expected={(f,s,str(seed),d) for f in FAMILIES for s in SCOPES for seed in (0,1) for d in DOMAINS}
    check('common training: all 24 pairs have every test domain',len(pairs)==96 and {identity(r) for r in pairs}==expected)
    check('common training: 48 final checkpoints and three controls, four domains each',len(cells)==204)
    source={(r['model_family'],r['training_domain'],r['training_seed'],r['evaluation_domain'],r['training_objective']):r for r in cells}
    for r in pairs:
        key=identity(r)
        before=source[(*key,'binary')];after=source[(*key,'quadratic')]
        good=True
        for metric in METRICS:
            b,a=before[metric],after[metric]
            for arm,value in (('binary',b),('quadratic',a)):
                good &= r[arm+'_'+metric]=='' if value=='' else math.isclose(float(r[arm+'_'+metric]),float(value),abs_tol=1e-10)
            good &= r[metric+'_change']=='' if '' in (a,b) else math.isclose(float(r[metric+'_change']),float(a)-float(b),abs_tol=1e-10)
        n=198 if key[-1]=='gpqa' else 300
        check('common paired arithmetic: '+str(key),good and int(before['n'])==int(after['n'])==n)
    for r in cells:
        accuracy,score,coverage,invalid,tail=(float(r[k]) for k in ('accuracy','score','coverage','invalid','tail'))
        gap=100*float(r['mean_confidence_among_answers'])-100*accuracy/coverage if coverage else None
        gap_valid=(r['gap']==r['gap_distance']=='') if gap is None else (
            math.isclose(float(r['gap']),gap,abs_tol=1e-9) and math.isclose(float(r['gap_distance']),abs(gap),abs_tol=1e-9))
        valid=(-100-1e-9<=score<=accuracy+1e-9 and 0<=accuracy<=coverage+1e-9
               and 0<=invalid<=100-coverage+1e-9 and 0<=tail<=100-accuracy+1e-9
               and gap_valid)
        check('common metric denominators: '+r['model_family']+'/'+r['checkpoint']+'/'+r['evaluation_domain'],valid)
    check('common summaries: all training and test contexts',len(summary)==48)
    scope_summary=read('scope_summary')
    check('scope synthesis: all models and all three scopes',
          {(r['model_family'],r['scope']) for r in scope_summary}==
          {(f,s) for f in ('All three models',*FAMILIES) for s in ('same','different','gpqa')}
          and len(scope_summary)==12)
    for r in scope_summary:
        own=[c for c in cells if (r['model_family']=='All three models' or c['model_family']==r['model_family'])
             and c['training_domain'] in ('math','medicine','ethics')
             and (c['evaluation_domain']==c['training_domain'] if r['scope']=='same' else
                  c['evaluation_domain']!='gpqa' and c['evaluation_domain']!=c['training_domain']
                  if r['scope']=='different' else c['evaluation_domain']=='gpqa')]
        good=int(r['matched_pairs'])==(18 if r['model_family']=='All three models' else 6)
        for metric in METRICS:
            for arm in ('binary','quadratic'):
                values=[c[metric] for c in own if c['training_objective']==arm]
                good &= r[arm+'_'+metric]=='' if '' in values else math.isclose(
                    float(r[arm+'_'+metric]),mean(float(v) for v in values),abs_tol=1e-9)
            if any(c[metric]=='' for c in own):
                good &= all(r[metric+suffix]=='' for suffix in ('_change','_change_min','_change_max','_positive_pairs'))
                continue
            keys={(c['model_family'],c['training_domain'],c['training_seed']) for c in own}
            deltas=[]
            for key in keys:
                paired=[c for c in own if (c['model_family'],c['training_domain'],c['training_seed'])==key]
                deltas.append(mean(float(c[metric]) for c in paired if c['training_objective']=='quadratic')
                              -mean(float(c[metric]) for c in paired if c['training_objective']=='binary'))
            good &= (math.isclose(float(r[metric+'_change']),mean(deltas),abs_tol=1e-9)
                     and math.isclose(float(r[metric+'_change_min']),min(deltas),abs_tol=1e-9)
                     and math.isclose(float(r[metric+'_change_max']),max(deltas),abs_tol=1e-9)
                     and int(r[metric+'_positive_pairs'])==sum(d>0 for d in deltas))
        check('scope synthesis arithmetic and paired consistency: '+r['model_family']+'/'+r['scope'],good)
    all_scopes={r['scope']:r for r in scope_summary if r['model_family']=='All three models'}
    check('scope synthesis: identical baseline subject mix',
          all(all_scopes['same']['base_'+m]==all_scopes['different']['base_'+m] for m in METRICS))
    retained={m:100*(float(all_scopes['different']['quadratic_'+m])-float(all_scopes['different']['base_'+m])) /
              (float(all_scopes['same']['quadratic_'+m])-float(all_scopes['same']['base_'+m]))
              for m in ('score','gap_distance','tail','accuracy')}
    check('compact transfer: ratios use prepared baseline, not accuracy-only control',
          {m:round(v) for m,v in retained.items()}=={'score':28,'gap_distance':49,'tail':88,'accuracy':6})
    compact=essay.split('id="fig-transfer-summary"',1)[1].split('</figure>',1)[0]
    check('compact transfer: adjacent trained rows, four ratios and no accuracy-only row',
          'After training: same subject' in compact and 'After training: other subjects' in compact
          and 'scope-binary' not in compact and 'Questions answered:' in compact
          and 'This is context, not an improvement measure.' in compact
          and all(f'data-retained="{m}"' in compact and f'>{round(v)}%</strong>' in compact
                  for m, v in retained.items())
          and compact.count('data-stage=') == 3 and compact.count('class="bar-base"') == 4)
    check('scope synthesis prose: half the score gain, 17 versus 14 positive pairs',
          .49<float(all_scopes['different']['score_change'])/float(all_scopes['same']['score_change'])<.51
          and all_scopes['same']['score_positive_pairs']=='17' and all_scopes['different']['score_positive_pairs']=='14')
    by_train={t:mean(float(r['score_change']) for r in pairs if r['training_domain']==t
                    and r['evaluation_domain'] not in (t,'gpqa')) for t in ('math','medicine','ethics')}
    check('scope synthesis prose: other-subject gains by training subject',
          {t:round(v) for t,v in by_train.items()}=={'math':-5,'medicine':15,'ethics':13})
    check('scope synthesis shown before the directional detail',
          essay.index('id="fig-transfer-summary"')<essay.index('id="fig-transfer"')
          and 'Every training-to-test direction and its two-seed range' in essay
          and 'Confidence gap is absolute before averaging' in essay)
    positive_counts=[sum(float(r['score_change'])>0 for r in summary if r['model_family']==family
                         and r['training_domain']!='pooled' and r['training_domain']!=r['evaluation_domain'])
                     for family in FAMILIES]
    check('transfer prose: seven, eight, seven positive mean directions',positive_counts==[7,8,7])
    check('transfer prose: math to ethics lowers score in all models',
          all(float(r['score_change'])<0 for r in summary
              if r['training_domain']=='math' and r['evaluation_domain']=='ethics'))
    for r in summary:
        selected=[p for p in pairs if (p['model_family'],p['training_domain'],p['evaluation_domain'])==
                  (r['model_family'],r['training_domain'],r['evaluation_domain'])]
        good=len(selected)==2
        for metric in METRICS:
            if any(p[metric+'_change']=='' for p in selected):
                good &= all(r[metric+suffix]=='' for suffix in ('_change','_change_min','_change_max'))
                continue
            changes=[float(p[metric+'_change']) for p in selected]
            good &= math.isclose(float(r[metric+'_change']),mean(changes),abs_tol=1e-10)
            good &= math.isclose(float(r[metric+'_change_min']),min(changes),abs_tol=1e-10)
            good &= math.isclose(float(r[metric+'_change_max']),max(changes),abs_tol=1e-10)
        check('common two-seed summary: '+str((r['model_family'],r['training_domain'],r['evaluation_domain'])),good)
    trajectory=read('trajectories')
    expected_trajectory={(f,'base','',0) for f in FAMILIES}|{(f,a,str(seed),step) for f in FAMILIES
                         for a in ('binary','quadratic') for seed in (0,1) for step in range(5,61,5)}
    check('common trajectories: measured steps, all models and both seeds',len(trajectory)==147 and
          {(r['family'],r['objective'],r['seed'],int(r['step'])) for r in trajectory}==expected_trajectory)
    check('common reliability: ten bins for every model and arm',len(read('reliability_bins'))==90)
    for name in ('prudence_levels','pressure_levels'):
        rows=read(name)
        expected_levels={(f,'base','') for f in FAMILIES}|{(f,a,str(seed)) for f in FAMILIES for a in ('binary','quadratic') for seed in (0,1)}
        check('common '+name+': identical checkpoint coverage',len(rows)==15 and
              {(r['model_family'],r['training_objective'],r['training_seed']) for r in rows}==expected_levels)
    for r in read('prudence_levels'):
        proportion=float(r['prudence_substantive_n'])/float(r['prudence_n'])
        check('common decision denominators: '+r['model_family']+'/'+r['checkpoint'],
              float(r['prudence_n'])==80
              and math.isclose(float(r['prudence_accuracy_all_questions']),float(r['prudence_accuracy'])*proportion,abs_tol=1e-10)
              and math.isclose(float(r['prudence_high_confidence_wrong_execution_all_questions']),
                               float(r['prudence_high_confidence_wrong_execution_rate'])*proportion,abs_tol=1e-10)
              and math.isclose(float(r['prudence_invalid_rate_all_questions']),1-float(r['prudence_parse_rate']),abs_tol=1e-10))
    external=read('external_levels')
    patterns=[Counter((r['training_objective'],r['training_seed'],r['family'],r['task'],r['setting'])
                     for r in external if r['model_family']==family) for family in FAMILIES]
    check('common external battery: every task and setting in all three models',bool(patterns[0]) and patterns[0]==patterns[1]==patterns[2])
    thresholds=read('thresholds')
    check('common thresholds: all checkpoints at both gates',len(thresholds)==30)
    for r in thresholds:
        n=int(r['questions']);accepted=int(r['accepted']);coverage=float(r['coverage']);wrong=float(r['wrong_per_question'])
        value=coverage-5*wrong
        check('common threshold payoff: '+str((r['model_family'],r['training_objective'],r['training_seed'],r['threshold'])),
              n==1098 and math.isclose(accepted/n,coverage,abs_tol=1e-10)
              and math.isclose(float(r['value_per_question']),value,abs_tol=1e-10))
    check('current essay: complete directional matrix',essay.count('class="transfer-cell-button"')==180
          and all(escape(f)+': Honest confidence-adjusted accuracy transfer' in essay for f in FAMILIES))
    check('current essay: both pressure outcomes and conditional denominators',
          'Accepts incorrect pushback' in essay and 'Accepts valid correction' in essay
          and 'initially wrong answers' in essay and 'parseable conversations' in essay)
    check('current notes: historical protocols separated from common cohort',
          'Earlier training studies used different preparation' in notes
          and 'not included in its averages' in notes and '24 matched training pairs' in notes)
    check('current training prose: all models, shared settings and explicit malformed rule',
          'one training protocol for Qwen3 8B, GPT-OSS 20B and Nemotron 3 Nano 30B' in essay
          and '512 tokens for every model and arm' in essay and 'Malformed outputs count as wrong' in essay)
    check('current transfer prose: two-seed range is not a confidence interval',
          'not a confidence interval' in notes)
