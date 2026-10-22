"""An illustrative two-stage action gate, separate from experimental results.

The example answers are fixed. Moving the threshold changes the policy only;
correctness is shown after passage and never enters the admission decision.
"""
import json

EXAMPLES = [
    {'id': 'A', 'confidence': 95, 'correct': True},
    {'id': 'B', 'confidence': 90, 'correct': False},
    {'id': 'C', 'confidence': 85, 'correct': True},
    {'id': 'D', 'confidence': 75, 'correct': True},
    {'id': 'E', 'confidence': 65, 'correct': False},
    {'id': 'F', 'confidence': 55, 'correct': True},
    {'id': 'G', 'confidence': 40, 'correct': False},
    {'id': 'H', 'confidence': 20, 'correct': False},
]


def gate_html():
    """Render a useful 80% static example before progressive enhancement."""
    dots=''
    for i,row in enumerate(EXAMPLES):
        admitted=row['confidence']>=80
        x=435+i*55 if admitted else 80+(i%4)*75
        color=('#225d4e' if row['correct'] else '#833657') if admitted else '#294c72'
        dots+=(f'<circle cx="{x}" cy="{228-2*row["confidence"]}" r="8" fill="{color}"/>'
               f'<text x="{x}" y="{231-2*row["confidence"]}" text-anchor="middle" '
               f'font-size="9" style="fill:white">{row["id"]}</text>')
    return f'''<div class="action-gate" data-threshold="80">
<div class="gate-stages"><div><b>1 · LLM model</b><span>Supplies an answer + confidence</span></div><span class="gate-arrow" aria-hidden="true">→</span><div><b>2 · Action gate</b><span>You set the minimum confidence</span></div></div>
<div class="gate-plot"><svg viewBox="0 0 680 270" role="img" aria-label="Answers move from the model to a separate gate. Higher bubbles represent higher reported confidence. At an 80% threshold, answers A, B and C may proceed; the others are held.">
<text x="8" y="16" font-size="12">Reported confidence</text>
<text x="8" y="34" font-size="11">100%</text><text x="8" y="134" font-size="11">50%</text><text x="8" y="234" font-size="11">0%</text>
<path d="M50 28V228H650" stroke="#d8d3cb" fill="none"/>
<path d="M405 28V68" stroke="#7c9a8a" stroke-dasharray="3 4"/><path d="M405 68V228" stroke="#873c5e" stroke-width="4"/>
<path d="M50 68H650" stroke="#873c5e" stroke-dasharray="3 4"/><text x="415" y="61" font-size="12">80% gate</text>
{dots}<text x="440" y="43" font-size="12">May act</text><text x="440" y="250" font-size="12">Below threshold: hold</text></svg></div>
<div class="gate-controls" hidden><label for="action-gate-threshold">Minimum confidence to act <output for="action-gate-threshold">80%</output></label><div class="gate-inputs"><input id="action-gate-threshold" type="range" min="0" max="100" step="5" value="80" aria-describedby="gate-rule"><button type="button" class="gate-pause">Pause flow</button></div></div>
<p id="gate-rule" class="gate-rule">Allow an action when reported confidence is at least the threshold; otherwise hold it for review.</p>
<noscript><p class="gate-key">Static view: the gate is set to 80%.</p></noscript>
<div class="gate-result" aria-live="polite" aria-atomic="true"><b>3 of 8 example answers allowed</b><span>2 correct · 1 wrong · 5 held</span></div>
<div class="gate-answers" aria-label="Answers allowed by this threshold"><span class="gate-correct">Answer A · 95% <b>Correct</b></span><span class="gate-wrong">Answer B · 90% <b>Wrong</b></span><span class="gate-correct">Answer C · 85% <b>Correct</b></span></div>
<p class="gate-key">Colors reveal the example outcomes after the gate. The gate itself sees only reported confidence.</p>
<script type="application/json" class="gate-examples">{json.dumps(EXAMPLES)}</script>
</div>'''


CSS = '''
.action-gate { font: 13px/1.45 Inter,sans-serif; }
.gate-stages { display: grid; grid-template-columns: 1fr 30px 1fr; gap: 14px; padding: 20px 0 12px; }
.gate-stages b, .gate-stages span:not(.gate-arrow) { display: block; }
.gate-stages b { font-size: 15px; }
.gate-stages div span { color: var(--text-muted); margin-top: 4px; }
.gate-arrow { align-self: center; font-size: 23px; color: var(--text-muted); }
.gate-plot svg { display: block; width: 100%; height: 270px; overflow: visible; }
.gate-plot svg text { font-family: Inter,sans-serif; fill: var(--text-muted); }
.gate-controls[hidden] { display: none; }
.gate-controls label { display: flex; justify-content: space-between; gap: 12px; font-weight: 600; }
.gate-controls output { color: #873c5e; font-variant-numeric: tabular-nums; }
.gate-inputs { display: flex; gap: 18px; align-items: center; margin-top: 9px; }
.gate-inputs input { flex: 1; min-width: 0; accent-color: #873c5e; cursor: pointer; }
.gate-inputs button { border: 1px solid var(--rule); background: transparent; padding: 7px 10px; color: var(--text); font: 12px Inter,sans-serif; cursor: pointer; }
.gate-inputs :focus-visible { outline: 2px solid #873c5e; outline-offset: 4px; }
.gate-rule, .gate-key { font: 11px/1.5 Inter,sans-serif; color: var(--text-muted); margin: 10px 0 16px; }
.gate-result { display: flex; flex-wrap: wrap; gap: 6px 18px; border-top: 1px solid var(--rule); padding-top: 15px; }
.gate-result span { color: var(--text-muted); }
.gate-answers { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.gate-answers > span { padding: 8px 12px; border: 1px solid var(--rule); font-size: 12px; }
.gate-answers b { display: block; font-size: 11px; font-weight: 500; margin-top: 3px; }
.gate-correct { color: #225d4e; background: #edf3ef; }
.gate-wrong { color: #833657; background: #f5ecef; }
@media(max-width:600px) {
 .gate-stages { grid-template-columns: 1fr 18px 1fr; gap: 8px; }
 .gate-stages b { font-size: 13px; }
 .gate-stages div span { font-size: 11px; }
 .gate-inputs { gap: 10px; }
 .gate-inputs button { font-size: 11px; }
 .gate-answers > span { padding: 7px 9px; }
}
@media print { .gate-controls { display: none; } }
'''

JS = r'''
document.querySelectorAll('.action-gate').forEach(function(root) {
  const examples = JSON.parse(root.querySelector('.gate-examples').textContent);
  const svg = root.querySelector('svg'), slider = root.querySelector('input');
  const pause = root.querySelector('.gate-pause'), result = root.querySelector('.gate-result');
  const answers = root.querySelector('.gate-answers'), motion = matchMedia('(prefers-reduced-motion: reduce)');
  const ns = 'http://www.w3.org/2000/svg';
  let threshold = 80, width = 680, gate = 405, nodes = [], frame = 0, elapsed = 0, previous = 0;
  let paused = motion.matches, visible = false;
  function add(tag, attrs, text) {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v));
    if(text !== undefined) node.textContent = text;
    svg.appendChild(node); return node;
  }
  function y(c) { return 228 - 2*c; }
  function paint() {
    // In paused mode, every example is visible. Motion is illustrative only;
    // the summary always evaluates the same eight examples, not arrivals.
    nodes.forEach(function(node,i) {
      const row = examples[i], admitted = row.confidence >= threshold;
      let x, crossed;
      if(paused) {
        x = admitted ? gate + 23 + (i%3)*Math.max(10,(width-gate-45)/3) : 63+(i%4)*(gate-95)/4;
        crossed = admitted;
      } else {
        const phase = (elapsed/7800 + i/examples.length)%1;
        const desired = 60 + phase*(width-78);
        crossed = desired > gate;
        x = admitted ? desired : Math.min(desired,gate-13);
        node.setAttribute('opacity',!admitted && crossed ? Math.max(0,1-(desired-gate)/(width-gate)) : 1);
      }
      if(paused) node.setAttribute('opacity',1);
      node.setAttribute('transform',`translate(${x},${y(row.confidence)})`);
      node.firstChild.setAttribute('fill', admitted && crossed ? (row.correct?'#225d4e':'#833657') : '#294c72');
    });
  }
  function draw() {
    width = Math.max(290,root.querySelector('.gate-plot').clientWidth); gate = width*.61;
    svg.setAttribute('viewBox',`0 0 ${width} 270`); svg.replaceChildren(); nodes=[];
    add('text',{x:8,y:15,'font-size':11},'Reported confidence');
    [0,50,100].forEach(c=>{
      add('line',{x1:48,x2:width-12,y1:y(c),y2:y(c),stroke:'#ddd8d0','stroke-width':.6});
      add('text',{x:3,y:y(c)+4,'font-size':10},c+'%');
    });
    add('rect',{x:gate,y:28,width:width-gate-12,height:200-2*threshold,fill:'#edf3ef',opacity:.75});
    add('rect',{x:gate,y:y(threshold),width:width-gate-12,height:2*threshold,fill:'#f5ecef',opacity:.6});
    add('line',{x1:gate,x2:gate,y1:28,y2:y(threshold),stroke:'#7c9a8a','stroke-dasharray':'3 4'});
    add('line',{x1:gate,x2:gate,y1:y(threshold),y2:228,stroke:'#873c5e','stroke-width':4});
    add('line',{x1:48,x2:width-12,y1:y(threshold),y2:y(threshold),stroke:'#873c5e','stroke-dasharray':'3 4','stroke-width':.7});
    add('text',{x:gate+7,y:y(threshold)-7,'font-size':11},threshold+'% gate');
    add('text',{x:gate+7,y:249,'font-size':11},'Below gate: hold');
    examples.forEach(row=>{
      const node=add('g',{'aria-hidden':'true'});
      const circle=document.createElementNS(ns,'circle'); circle.setAttribute('r',8); node.appendChild(circle);
      const text=document.createElementNS(ns,'text');text.textContent=row.id;
      text.setAttribute('text-anchor','middle');text.setAttribute('y',3);text.setAttribute('font-size',9);text.style.fill='white';node.appendChild(text);
      nodes.push(node);
    });
    paint();
  }
  function update() {
    threshold=Number(slider.value);root.dataset.threshold=threshold;
    root.querySelector('output').value=threshold+'%';
    slider.setAttribute('aria-valuetext',threshold+' percent minimum confidence');
    const allowed=examples.filter(r=>r.confidence>=threshold), correct=allowed.filter(r=>r.correct).length;
    result.replaceChildren();
    const headline=document.createElement('b');headline.textContent=allowed.length+' of 8 example answers allowed';result.appendChild(headline);
    const detail=document.createElement('span');detail.textContent=correct+' correct · '+(allowed.length-correct)+' wrong · '+(8-allowed.length)+' held';result.appendChild(detail);
    answers.replaceChildren();
    allowed.forEach(row=>{
      const card=document.createElement('span');card.className=row.correct?'gate-correct':'gate-wrong';card.dataset.answer=row.id;
      card.append('Answer '+row.id+' · '+row.confidence+'%');
      const verdict=document.createElement('b');verdict.textContent=row.correct?'Correct':'Wrong';card.appendChild(verdict);answers.appendChild(card);
    });
    if(!allowed.length) answers.textContent='No actions allowed at this threshold.';
    svg.setAttribute('aria-label','Illustrative action gate at '+threshold+' percent. '+allowed.length+' of eight example answers may act, including '+(allowed.length-correct)+' wrong answers. The gate checks confidence only.');
    draw();
  }
  function tick(now) {
    frame=0;
    if(paused || !visible || document.hidden) { previous=0; return; }
    if(previous) elapsed+=Math.min(now-previous,100);
    previous=now;paint();frame=requestAnimationFrame(tick);
  }
  function sync() {
    cancelAnimationFrame(frame);frame=0;previous=0;
    pause.textContent=paused?'Play flow':'Pause flow';pause.setAttribute('aria-pressed',String(paused));
    paint();
    if(!paused && visible && !document.hidden) frame=requestAnimationFrame(tick);
  }
  slider.addEventListener('input',update);
  pause.addEventListener('click',()=>{paused=!paused;sync();});
  motion.addEventListener('change',()=>{paused=motion.matches;sync();});
  document.addEventListener('visibilitychange',sync);
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;sync();},{threshold:.1}).observe(root);
  new ResizeObserver(draw).observe(root.querySelector('.gate-plot'));
  root.querySelector('.gate-controls').hidden=false;
  update();sync();
});
'''
