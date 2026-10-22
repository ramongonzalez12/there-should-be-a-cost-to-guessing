## prompting | 3. Instructions closed 14% of the overconfidence gap

{tb_prompting}

{tb_prompt_reliability}

<div class="table-brief-reading"><b>Takeaway.</b> The instructions moved
confidence down more than accuracy, but 86% of the original gap remained. The
effect improved the gap in 11 of 15 model-subject comparisons and the
confidence-calibrated score in 8 of 15.</div>

<div class="literature-compare">
<div class="literature-compare-title"><i class="lit-tag direct">Direct precedent</i> Prompting for more realistic confidence</div>
<dl>
<div><dt>What prior work did</dt><dd><a href="https://arxiv.org/abs/2305.14975">Tian et al.</a> elicited verbal confidence from ChatGPT, GPT-4, and Claude on three factual benchmarks. <a href="https://arxiv.org/abs/2306.13063">Xiong et al.</a> compared prompts, sampling, and aggregation across five models and five dataset types. <a href="https://arxiv.org/abs/2604.03904">I-CALM</a> announced answer-or-abstain payoffs and added guidance about truthfulness and responsibility.</dd></div>
<div><dt>What it found</dt><dd>Verbal confidence can be more accurate than token probabilities, sometimes cutting calibration error by about half. No elicitation method worked consistently everywhere. Announced payoffs improved selective answering, but the best treatment bundled several instructions.</dd></div>
<div><dt>What it called for</dt><dd>Better ways to elicit uncertainty at test time and turn it into practical deferral or abstention, especially on harder professional tasks.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A matched magnitude estimate.</b> On identical questions across 5 current models and 4 subjects, the rule-and-threshold prompt reduced the confidence gap from 31.3 to 27.0 points. It closed 14% and left 86% in place. Because the prompt bundled the rule and threshold, it cannot identify which wording caused the change.</dd></div>
</dl>
</div>

^ <span class="table-brief-source">{tb_src_prompt}</span>
