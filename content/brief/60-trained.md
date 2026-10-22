## trained | 5. Training adds 0.105 to confidence-calibrated score but trails accuracy by 2 points

**Point.** Accuracy-only training produced the highest accuracy. Training on the
confidence-calibrated score produced the best confidence calibration. Adding a
fixed answering cost did not improve that score further.

**Basis.** One model family was trained under each reward with the other choices
held fixed. The table below compares the weights under the ordinary test prompt,
so the training reward is the main difference.

{b_train_summary}

**Takeaway.**

- key: **Performance winner: accuracy-only training.** It reached 65.2% overall
accuracy, compared with 63.2% for confidence-calibrated training.
- key: **Calibration winner: confidence-aware training.** Both confidence-aware
rewards reached a 0.443 confidence-calibrated score, 0.105 above accuracy-only
training.
- key: **The fixed cost added no calibration gain.** It tied the quadratic reward
at 0.443 under the ordinary prompt. When the rule was announced at test time,
its score fell to 0.405, below the 0.428 quadratic-only result.

**Meaning.** The reward changed the model's weights, but the objective mattered.
Optimizing accuracy improved benchmark performance and worsened calibration.
Optimizing the confidence-calibrated score improved calibration but did not
produce the highest accuracy.

**Limit.** This is causal evidence within one training setup, not evidence that
the result generalizes to every model family. Effects varied by seed and
benchmark.

### Should the model decide when to answer, or should code decide?

We first held the trained checkpoint and question fixed. The only change was
whether the prompt made the model internalize the penalty, or asked for
confidence and left the final cutoff to code.

{b_prompt_factorial}

**Takeaway.** Confidence prompting plus code produced
{b_prompt_factorial_wrong_delta} fewer wrong answers and
{b_prompt_factorial_value_delta} more decision-value points per 100 questions.
All three independent seeds moved in those directions, but the paired 95%
intervals still include no difference. Across the full dose grid, the separated
design had higher value in 10 of 15 seed-by-dose comparisons and fewer wrong
answers in 9 of 15.

Nearly all of the gain came from simplifying the prompt, not from the cutoff.
Removing the embedded penalty added {b_prompt_only_value_delta} decision-value
points. Applying the 30% cutoff afterwards changed value by only
{b_gate_value_delta} points because almost every answer was already above 30%.

Format adherence explains part, but not all, of the difference. At the primary
checkpoint, the penalty prompt produced {b_prompt_embedded_invalid} malformed
responses out of 600; the simpler prompt produced {b_prompt_separated_invalid}.
Among the 588 pairs where both outputs formatted correctly, the simpler design
still had {b_prompt_formatted_wrong_delta} fewer wrong answers and
{b_prompt_formatted_value_delta} more value points per 100. That restricted
comparison is a post-result mechanism diagnostic, not the primary test.

^ {b_src_prompt_threshold_factorial} Two training objectives were tested. All
^ 62 malformed attempts across the full dose grid were counted as wrong and
^ forced through the external cutoff.

#### Which training produces the best probabilities for that code?

A broader 9,000-response test compared confidence-only and cost-trained
checkpoints across three held-out benchmarks. This changes the training reward,
so it answers a separate question from the same-checkpoint prompt test. The
wrong-answer cost is shown relative to the value of a correct answer. Decision
value credits a correct answer, subtracts that stated cost for a wrong answer,
and gives zero to a withheld answer.

{b_policy_primary}

**Takeaway.** Confidence-only training did not win at the trained 30% threshold.
It showed {b_policy_wrong_delta} more wrong answers per 100 questions. At the
same answer rate, confidence-only training also produced
{b_policy_matched_error_delta} more errors per 100 answers than cost training.

External control still mattered as the stakes rose. The embedded model continued
to answer at the same rate regardless of the cost of being wrong. A deterministic
gate sharply reduced the wrong answers that reached the user.

{b_policy_stakes}

**Recommendation.** Use a hybrid. Train the model to produce useful
confidence and restraint, save its probability, and let deterministic code apply
the final threshold. This test does not support assuming that confidence-only
training supplies the best probabilities for that gate.

**Limit.** This is a frozen secondary analysis of one model family. The underlying
benchmark results had already been reported, although this policy comparison had
not been run. At a 90% threshold, selected answers still failed to break even
against a nine-to-one wrong-answer cost. Thresholds therefore need their own
held-out validation; a model saying 90% is not a safety guarantee.

^ {b_src_policy_architecture} Five confidence-only and five cost-trained
^ checkpoints each covered 900 held-out questions. One malformed attempted
^ answer was conservatively counted as a 100%-confident wrong answer.

:::details Full training-by-test-prompt comparison
The first two columns distinguish what reward changed the model's weights from
what instruction it received during testing. Confidence and calibration gaps
are calculated among answered questions. Overall accuracy and the
confidence-calibrated score include every question.

{b_train_matrix}

^ {b_src_finetune} Both training seeds averaged. All five pre-registered health
^ gates passed.{b_fn_seeds} Every confidence-calibrated-score column uses the
^ same plain quadratic rule, including rows trained with a fixed answering
^ cost. The training reward differs; the evaluation measure does not.
:::

:::details Results by benchmark and training seed
{b_train_bench}

{b_train_seeds}

The benchmark effect is not uniform. It is largest on GPQA and reverses on ARC
and BoolQ. Reported confidence also differs substantially between the two
training seeds.
:::
