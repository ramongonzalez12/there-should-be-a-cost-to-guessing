## training | Training on the rule works, and it transfers

<div class="novelty-line"><span class="novelty-dots" aria-label="novelty 2 of 3">&#9679;&#9679;&#9675;</span> <b>Sharper comparison.</b> Every component has a direct precedent; the same-rule prompt-versus-training contrast and the directional subject matrix are the additions.</div>

The training section makes the stronger claim: fine-tuning on the
penalized score calibrates models quickly, and the calibration carries into
subjects the training never touched. Calibration-aware training has direct
precedents. The comparison the write-up leans on, prompting against training
under one rule, is the part this review did not find elsewhere.

<div class="literature-compare">
<div class="literature-compare-title">Where the training result stands</div>
<dl>
<div><dt>Nearest prior work</dt><dd><b>LLM research, 2023 to 2026.</b> <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2507.16806">RLCR (2025 to 2026)</a> adds a Brier term to correctness reward and improves calibration in and out of domain without losing accuracy. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2510.05126">Steyvers et al. (2025 to 2026)</a> fine-tune two models on general knowledge, mathematics, and trivia, then test unseen medical, legal, and truthfulness benchmarks. Gains transfer, but less than within domain. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2311.09677">R-Tuning (2023)</a> shows refusal training can become an out-of-domain meta-skill. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2607.04332">Tan et al. (2026)</a> warn that badly designed confidence rewards can be gamed.</dd></div>
<div><dt>What it did not test</dt><dd>None of these compares an announced rule against training on that same rule inside one harness on frozen questions, so none can say how much of the effect requires changing the weights. And none reports a directional subject-by-subject transfer matrix from independently trained pairs.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>The prompt-versus-training contrast, and a transfer matrix.</b> Explaining the same strictly proper formula closed 16% of the confidence gap; training on it closed 81%. Matched training arms differ only in reward: same starting checkpoint, same items, same seed. Across seven independent Qwen pairs, the outside-subject reduction in high-confidence errors was 98% as large as the same-subject reduction, held on GPQA, which supplied no training data, and the pooled pattern repeated in GPT-OSS.</dd></div>
<div class="limit"><dt>What it still cannot show</dt><dd>Final outside-subject calibration stayed worse than same-subject calibration; the training transferred the size of the correction, not equal mastery. The directional matrix exists in one model family so far.</dd></div>
</dl>
</div>

The matched tables are in the [table brief](brief-table.html#training), with
seeds and health gates on the [replication page](replication.html).
