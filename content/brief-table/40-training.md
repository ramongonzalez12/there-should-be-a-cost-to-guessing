## training | 4. Training closed 81% of the pooled confidence gap

### Our matched controlled comparison

{tb_training}

{tb_training_reliability}

<div class="table-brief-reading"><b>Takeaway.</b> Accuracy-only training raises
accuracy and confidence together. Confidence-aware training eliminated about
70% of that gap in the first two-seed comparison while changing accuracy by
about two points.</div>

^ <span class="table-brief-source">{tb_src_training}</span>

### Who should decide whether an answer is safe enough to show?

We first held the trained checkpoint and question fixed. The only change was
whether the prompt made the model internalize the penalty, or asked for
confidence and left the final cutoff to code.

{tb_prompt_factorial}

<div class="table-brief-reading">
<span class="context-line"><b>The direct test supports the simpler prompt, but
not decisively.</b> Confidence prompting plus code produced
{tb_prompt_factorial_wrong_delta} fewer wrong answers and
{tb_prompt_factorial_value_delta} more decision-value points per 100 questions.
All three independent seeds moved in those directions, but the 95% intervals
still include no difference.</span>
<span class="context-line"><b>Nearly all of the gain came from simplifying the
prompt.</b> Removing the embedded penalty added {tb_prompt_only_value_delta}
decision-value points. Applying the 30% cutoff afterwards changed value by only
{tb_gate_value_delta} points because almost every answer was already above
30%.</span>
<span class="context-line"><b>Format failures were part of the burden.</b> At the
primary checkpoint, the penalty prompt produced {tb_prompt_embedded_invalid}
malformed responses out of 600; the simpler prompt produced
{tb_prompt_separated_invalid}. Among the 588 pairs where both outputs formatted
correctly, the simpler design still had {tb_prompt_formatted_wrong_delta} fewer
wrong answers and {tb_prompt_formatted_value_delta} more value points per 100.
That restricted comparison is a diagnostic, not the primary result.</span>
<span class="context-line"><b>Across training doses.</b> The separated design had
higher value in 10 of 15 seed-by-dose comparisons and fewer wrong answers in 9
of 15. Those are repeated checkpoints from three training runs, not 15
independent seeds.</span>
</div>

^ <span class="table-brief-source">{tb_src_prompt_threshold_factorial}</span>
^ All 62 malformed attempts across the full dose grid were counted as wrong and
^ forced through the external cutoff.

### Does confidence-only training supply the best probabilities for that code?

No. A broader test compared differently trained checkpoints on three held-out
benchmarks. It asks a separate question from the same-checkpoint prompt test.

{tb_policy_primary}

<div class="table-brief-reading">
<span class="context-line"><b>Confidence-only training did not win.</b> At 30%,
putting the threshold outside the confidence-only model produced
{tb_policy_wrong_delta} more wrong answers per 100 questions. At the same answer
rate, confidence-only training produced {tb_policy_matched_error_delta} more
errors per 100 answers than cost training.</span>
<span class="context-line"><b>External control still matters.</b> The model's
native answer rate cannot react when the cost of an error changes. Deterministic
gating sharply reduced wrong answers once errors became much more expensive.</span>
<span class="context-line"><b>Current recommendation.</b> Use a hybrid: preserve
the model's answer and probability, then let observable code apply the final
deployment threshold. Do not assume confidence-only training necessarily gives
that code the best risk ranking.</span>
</div>

{tb_policy_stakes}

<div class="table-brief-reading"><b>How to read decision value.</b> A correct
answer is worth one point, a withheld answer is worth zero, and a wrong answer
loses the cost shown in the second column. Values are totals per 100 questions.
At the 90% cutoff, even the selected answers did not break even against a
nine-to-one error cost. Raw confidence therefore needs held-out validation.</div>

^ <span class="table-brief-source">{tb_src_policy_architecture}</span> Five
^ confidence-only and five cost-trained checkpoints each covered 900 held-out
^ questions. One malformed attempted answer was conservatively treated as
^ 100%-confident and wrong.

<div class="literature-compare">
<div class="literature-compare-title"><i class="lit-tag direct">Direct precedent</i> Training models to express uncertainty</div>
<dl>
<div><dt>What prior work did</dt><dd><a href="https://arxiv.org/abs/2507.16806">RLCR</a> added a Brier-score term to correctness reward. <a href="https://arxiv.org/abs/2311.09677">R-Tuning</a> trained models to refuse questions outside their knowledge. Other work has used calibration-aware reinforcement learning across Llama and Mistral models.</dd></div>
<div><dt>What it found</dt><dd>Calibration can improve without sacrificing accuracy, including on some new domains. Learned refusal can also transfer. Recent work warns that poorly designed confidence rewards can be gamed and that the best accuracy-calibration tradeoff depends on the task.</dd></div>
<div><dt>What it called for</dt><dd>Tests across more model families and tasks, broader metacognitive skills, and reward functions that cannot be improved by deliberately giving worse answers.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A cleaner causal contrast.</b> The same starting checkpoint, items, and random seed receive either accuracy-only reward or a strictly proper confidence reward. A fixed answering cost is tested separately. This isolates the training objective more tightly than comparisons between unrelated models.</dd></div>
</dl>
</div>

### How much of subject-specific calibration carries into other subjects?

{tb_generalization}

<div class="table-brief-reading">
<span class="context-line"><b>Answer.</b> Most of the calibration correction
carried over. In the subject used for training, confidence training reduced
high-confidence errors by 25.1 points. Outside that subject, it reduced them by
24.7 points, or 98% as much. The confidence gap improved by about 26 points in
both settings.</span>
<span class="context-line"><b>Important context.</b> The outside tests started
harder. After training, the models were about 2 points underconfident on their
training subject but remained 11 points overconfident outside it. Training
transferred the size of the correction, not identical final calibration.</span>
<span class="context-line"><b>Replication.</b> High-confidence errors fell both
inside and outside the training subject for all seven independently trained
pairs. The outside-subject confidence-calibrated score improved for the average
of all three outside tests in all seven pairs.</span>
</div>

<div class="literature-compare">
<div class="literature-compare-title"><i class="lit-tag direct">Direct precedent</i> Does calibration transfer across subjects?</div>
<dl>
<div><dt>What prior work did</dt><dd><a href="https://arxiv.org/abs/2510.05126">Steyvers et al.</a> fine-tuned two models on general knowledge, math, and open-ended trivia, then tested medical, legal, and truthfulness questions. RLCR also included out-of-domain evaluation.</dd></div>
<div><dt>What it found</dt><dd>Uncertainty communication transfers, but usually less than it improves within the training domain. Transfer between different metacognitive formats is weaker. Multitask training gives broader gains.</dd></div>
<div><dt>What it called for</dt><dd>More model families, more metacognitive tasks, and designs that distinguish broad uncertainty skills from learning one subject or response format.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>An explicit same-subject versus outside-subject comparison.</b> Seven independent Qwen pairs were trained on one subject and tested on that subject plus three others. The outside-subject reduction in highly confident errors was 98% as large as the same-subject reduction. Final outside-subject calibration was still worse, so the result shows transfer of the correction, not equal mastery.</dd></div>
</dl>
</div>

### The result extends to a subject that supplied no training data

{tb_generalization_scope}

<div class="table-brief-reading"><b>Takeaway.</b> Transfer was not limited to
moving among medicine, math, and legal or ethical reasoning. On GPQA, which
supplied no training questions, high-confidence errors fell by 32.0 points and
the confidence-calibrated score rose by 0.152.</div>

### Route-level examples

{tb_subject_transfer}

<div class="table-brief-reading">
<span class="context-line"><b>Clearest example.</b> The medicine-trained models
never received math calibration training. Across three matched pairs, they cut
wrong answers given at 80%+ confidence from 44.2% to 5.9% on math while math
accuracy stayed near 38%.</span>
<span class="context-line"><b>Limit.</b> Subject-by-subject transfer has only
been tested in Qwen3 8B. Medicine and legal or ethical reasoning each have three
training pairs. Math has one because two planned math pairs failed their
training health gates. The summary includes that usable math pair and the route
table shows only routes with three replications.</span>
</div>

^ <span class="table-brief-source">{tb_src_transfer}</span>

### Does broader, pooled calibration repeat in another model family?

{tb_cross_family}

<div class="table-brief-reading"><b>Takeaway.</b> Across Qwen and GPT-OSS,
accuracy stayed at about 50% while the confidence gap fell from 27.2 to 5.2
points. The largest change was fewer highly confident wrong answers, including
on GPQA, which was excluded from training. This supports broader transfer in a
second family, but pooled medicine, math, and legal or ethical training cannot
show which source subject supplied the transferable skill.</div>

<div class="literature-compare compact">
<div class="literature-compare-title"><i class="lit-tag close">Close precedent</i> Replication across model families</div>
<dl>
<div><dt>What prior work did</dt><dd>RLCR and <a href="https://arxiv.org/abs/2410.09724">reward-calibrated RLHF</a> each trained more than one model family.</dd></div>
<div><dt>What it found</dt><dd>Calibration-aware rewards can improve uncertainty behavior in more than one architecture.</dd></div>
<div><dt>What it called for</dt><dd>Broader family coverage and replication under matched training designs.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A pooled replication in GPT-OSS.</b> It repeats the broad transfer pattern seen in Qwen. It does not yet repeat the directional subject-to-subject experiment, so the strongest transfer claim still rests on one family.</dd></div>
</dl>
</div>

^ <span class="table-brief-source">{tb_src_transfer}</span>
