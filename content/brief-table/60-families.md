## families | 6. Format gates limit which model families can answer the question

{tb_format}

<div class="table-brief-reading"><b>Takeaway.</b> Qwen3 8B and GPT-OSS support
matched causal comparisons. The other rows are measurement failures, not
negative findings about calibration training.</div>

<div class="literature-compare">
<div class="literature-compare-title"><i class="lit-tag close">Close precedent</i> Evaluation setup and output-format reliability</div>
<dl>
<div><dt>What prior work did</dt><dd><a href="https://arxiv.org/abs/2211.09110">HELM</a> evaluated 30 models on 42 standardized scenarios and published raw prompts and completions. <a href="https://arxiv.org/abs/2402.01781">Alzahrani et al.</a> perturbed answer order and scoring. <a href="https://arxiv.org/abs/2501.10868">JSONSchemaBench</a> tested six constrained-generation systems on 10,000 schemas.</dd></div>
<div><dt>What it found</dt><dd>Evaluation details can change results materially: small benchmark perturbations moved rankings by as many as eight places. Format compliance, schema coverage, speed, and answer quality are distinct properties.</dd></div>
<div><dt>What it called for</dt><dd>Standardized conditions, published prompts and completions, robust scoring, and explicit measurement of structured-output reliability.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A prospective admission rule for causal training evidence.</b> A family enters paid reward training only after passing two complete 1,920-response format profiles. A failure means the training effect was not measured. It is never counted as evidence that calibration training failed.</dd></div>
</dl>
</div>

^ <span class="table-brief-source">{tb_src_formats}</span>
