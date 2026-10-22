## prompting | Telling the model about the rule barely works

<div class="novelty-line"><span class="novelty-dots" aria-label="novelty 2 of 3">&#9679;&#9679;&#9675;</span> <b>Sharper estimate.</b> Announced-payoff prompting has direct precedents; the matched share-of-gap magnitude is the addition.</div>

The write-up's prompting section reports that explaining the scoring formula
changes behavior only a little. Prompting for confidence has a real
literature, and one strand comes close to this exact experiment. None of it,
including the Kalai et al. proposal that benchmarks announce confidence
targets, measures how much of an existing overconfidence gap an announced
rule closes.

<div class="literature-compare">
<div class="literature-compare-title">Where the prompting result stands</div>
<dl>
<div><dt>Nearest prior work</dt><dd><b>LLM research, 2023 to 2026.</b> <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2305.14975">Tian et al. (2023)</a> test ChatGPT, GPT-4, and Claude on three benchmarks; verbalized confidence often cuts calibration error by 50% relative to token probabilities. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2306.13063">Xiong et al. (2023 to 2024)</a> test five LLMs across five dataset types and find no elicitation method works consistently. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2604.03904">I-CALM (2026)</a> announces answer-or-abstain payoffs and improves selective answering. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2511.11500">Honesty over Accuracy (2025)</a> finds severe prompt penalties alone produce little abstention.</dd></div>
<div><dt>What it did not test</dt><dd>Kalai et al. propose announcing targets but run no experiment on whether the announcement works. The elicitation papers measure calibration under different phrasings; they do not announce a strictly proper scoring contract and then quantify the share of a measured gap it closes.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A matched magnitude estimate, and it is small.</b> On identical frozen questions across five current models and three hard benchmarks, explaining the scoring formula without an answering threshold closed 16% of the confidence gap and left 84% in place. The comparison contains 4,536 matched responses. It isolates the formula explanation from the separate threshold question.</dd></div>
</dl>
</div>

The experiment is in the [table brief](brief-table.html#prompting).
