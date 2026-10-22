## worth | 4. The intended prompt lowers confidence error by {b_prompt_gap_reduction} points; accuracy changes {b_prompt_accuracy_delta} points

### Expanded five-model test

**Point.** Across {b_prompt_comparisons} matched model-benchmark comparisons,
the intended formula, explanation, and 30% threshold reduced the median absolute
confidence gap by {b_prompt_gap_reduction} percentage points. Median accuracy changed
by {b_prompt_accuracy_delta} points and the median confidence-calibrated score
changed by {b_prompt_score_delta}. The score improved in {b_prompt_score_wins} of
{b_prompt_comparisons} comparisons.

**Basis.** Five current models from four developers answered the same frozen
MMLU-Pro, GPQA Diamond, and MedMCQA questions under eight prompts. Every
condition contains 120 to 198 items, for {b_prompt_responses} deterministically
graded responses. The extra prompts test the formula, its explanation, the
answer threshold, the cost level, and deployment framing.

{b_pilot_summary}

**Takeaway.** The proposed prompt produced a modest, inconsistent calibration
gain and no performance gain. A simpler accuracy-only instruction did better:
its confidence-calibrated score rose in 13 of 15 comparisons. The evidence does
not isolate the proposed rule as the cause.

**Limit.** This covers five models from four developers and three multiple-choice knowledge
benchmarks, with one temperature-zero response per item. Gemini required low
reasoning; the other four models ran with reasoning off. The eight prompts
separate several mechanisms, but they are not a complete factorial test of every
wording and incentive. SimpleQA was excluded, so no headline result depends on
the unvalidated judge. {b_src_pilot}

:::details Model-by-model primary comparison
{b_pilot_levels}
:::

:::details Why calibration matters: published models can change rank
**Point.** Accuracy and confidence calibration can rank the same models
differently.

Humanity's Last Exam asks for confidence on every item. Rescoring those stored
responses shows that every scorable model claimed substantially more confidence
than it delivered. GPT-5 was slightly more accurate than GPT-5.2, but GPT-5.2
earned the higher confidence-calibrated score. Models from the same company are
ordered newest first.

{b_hle}

This table explains why calibration is worth measuring. It does not test whether
a prompt changes behavior because these stored responses were not generated
under the proposed rule.
:::

:::details Answering-cost rescoring and sparsely reported confidence
{b_hle_cost}

This is counterfactual rescoring of stored answers. It does not predict how a
model would respond if told the rule.

{b_hle_low}

Runs that rarely state confidence cannot be fairly rescored because those
responses are a selected subset.
:::

:::details Harness reproduction check
Before testing the new prompts, the harness reproduced the published GPQA
Diamond scores of six current models.

{b_parity}

{b_src_parity} Each band is the 95% range expected from a fresh 198-question
sample if the published rate is correct. All six results fall inside their
expected bands.
:::
