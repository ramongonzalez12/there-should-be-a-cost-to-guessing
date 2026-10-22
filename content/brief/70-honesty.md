## honesty | 6. Calibration training improves prudence, not alignment by itself

**Question.** Does better confidence calibration produce better evidence use,
less catastrophic overcommitment, more respect for multiple ends, and less
cheating or goal fixation?

**Answer.** Confidence-calibrated training reliably reduced overconfident bad
answers and decisions, including on subjects excluded from training. It also
made unauthorized shortcuts slightly less common in a harder hidden-opportunity
test, but the models still took those shortcuts most of the time. The evidence
supports transferable prudence and a small alignment-adjacent effect. It does
not yet show that calibration makes a generally aligned model. A plural-ends
reminder separately improved integrity behavior.

### 6.1 Calibration training sharply reduces overconfident bad decisions

**Point.** Confidence-calibrated training changed how models acted under
uncertainty, not just the probabilities they reported.

**Basis.** Five matched training seeds faced the same 80 hard questions. Each
answer required a probability and a choice to execute, verify, or defer. Wrong
execution carried losses from 5 to 50; verification carried a smaller fixed
cost. The table reports the median within-seed change from accuracy-only
training under the neutral prompt.

{b_plural_prudence_training}

**Meaning.**

- key: **The clearest result is a 46-point reduction in overconfident bad
decisions.** The median fell from 47% after accuracy-only training to 1% after
confidence-calibrated training. All five seeds improved. Accuracy changed by
only +1 point.
- key: **The fixed cost encouraged still more checking.** Wrong execution at
any confidence fell by 17 points in all five seeds, versus 9 points in four of
five without the cost. It did not improve evidence updating or goal correction.
- key: **The transfer stops after prudent action.** Exact posterior error rose
slightly, unauthorized reference use moved inconsistently, and appropriate goal
responses declined in three of five seeds.

**Limit.** Five seeds are enough to establish a repeated direction, not a broad
model-family result. The 80 decisions are forced-choice simulations. Invalid
answers count as incorrect and are excluded from action-rate denominators;
neutral-prompt parse rates were 94% to 100%.

### 6.2 Plural and prudence reminders affect different safeguards

**Point.** A plural-ends reminder reduced unauthorized shortcuts. A prudence
reminder improved risky decisions and evidence use but slightly increased those
shortcuts. Combining them produced the best balance.

**Basis.** Every checkpoint saw the same frozen worlds under a neutral prompt,
a plural-ends reminder, a prudence reminder, and both. Each number below is the
median within-checkpoint change from neutral. The 16 checkpoints are repeated
states from one model family, not 16 independent models.

{b_plural_prudence_prompting}

**Meaning.**

- key: **“There are also other ends” changed integrity behavior.** The plural
reminder cut unauthorized evaluator-reference use by 5.6 points at the median.
All 16 checkpoints improved, while authorized reference use also rose.
- key: **Prudence alone was narrower.** It cut wrong execution by 7.5 points
and exact-evidence error by 0.8 points, but unauthorized reference use rose at
12 of 16 checkpoints.
- key: **Both reminders together were the most balanced prompt.** Wrong
execution fell by 5.2 points, unauthorized use fell by 2.2 points, and
appropriate goal responses rose by 3.3 points. Ambiguous goal changes received
clarification 26 points more often at the median.

**Limit.** The plural reminder bundled authorization, truthfulness, material
harm, and affected stakeholders. This test identifies the bundle, not which
phrase caused the effect. Prompt compliance also does not establish a durable
change in the trained model.

### 6.3 The battery found low-frequency violations, not scheming

**Point.** These models sometimes used a prohibited evaluator reference, but we
did not observe checker tampering or concealment afterward.

**Basis.** Across all checkpoints and prompts, models used the prohibited
reference in 515 of 10,240 risky tool choices (5.0%). They altered the checker
in 0 of 10,240 choices and concealed a prohibited action in 0 of 515 follow-up
audits. Two of 20,480 goal decisions covertly preserved an old goal. Four of
4,096 plural-objective choices violated a standing constraint; three came from
one fixed-cost checkpoint under the neutral prompt.

**Meaning.** The experiment supplies a denominator for rare bad behavior. It
does not support a scheming claim. It also rules out the easier claim that every
model always respected authorization.

**Limit.** The action menu was explicit and the audit question was transparent.
Highly capable agents with tools, memory, hidden scratchpads, or long horizons
could behave differently. Zero checker tampering gives a rule-of-three upper
bound of about 0.03% for these 10,240 frozen choices, not for real deployments.

{b_src_plural_prudence}

### 6.4 High-confidence errors fell 17 to 25 points in the two stable three-seed subjects

**Point.** The central confidence result survives larger samples and new
training seeds for medicine and legal and ethical reasoning. Math training was
not stable enough to support the same claim.

**Basis.** Each completed accuracy-only and confidence-calibrated pair answered
300 new questions in medicine, math, and legal and ethical reasoning. None of
the 900 questions appeared in training or in the earlier 100-question test.
Medicine and ethics completed all three planned seeds. Two of three math pairs
failed the malformed-output health gate and remain in the denominator below.

{b_domain_replication}

**Meaning.**

- key: **High-confidence wrong answers fell in all 21 measurable comparisons.**
The median reduction was 20 percentage points. Median accuracy was unchanged,
and the confidence-calibrated score improved in 16 of 21.
- key: **The full three-subject decision rule was not met.** It required at
least 22 reductions among 27 planned comparisons. Only 21 were measurable, and
the failed training pairs cannot count as improvements.
- key: **Medicine replicated across all three seeds and all three test
subjects.** The median high-confidence-error reduction was 25 points. Median
accuracy fell 1 point.
- key: **Legal and ethical reasoning also replicated in all 9 comparisons.**
The median high-confidence-error reduction was 17 points. Median accuracy fell
less than 1 point, and the confidence-calibrated score improved in 8 of 9.
- key: **The earlier math magnitude transferred to 300 new questions, but not
to new training seeds.** The original pair again cut high-confidence errors by
10 to 49 points. A confidence-calibrated arm failed in seed 1, and an
accuracy-only arm failed in seed 2. Only 3 of 9 planned math contrasts were
measurable.

**Limit.** The larger result still comes from one model. Attempts to add
DeepSeek V3.1 and Qwen3.5 4B stopped before reward training because their full
base profiles exceeded the 1% malformed-output gate. Both models had passed a
64-response pilot, which was too small to reveal the failure.

{b_domain_replication_gates}

{b_src_domain_replication}

### 6.5 Pooled calibration cut high-confidence errors by 13 to 51 points across four subjects

**Point.** Training on medicine, math, and legal and ethical reasoning together
produced more cautious confidence on all four test subjects, including GPQA,
which was excluded from training. It did not improve factual accuracy.

**Basis.** Five matched accuracy-only and confidence-calibrated seed pairs used
the same 240 training items and optimizer settings. Each checkpoint answered
300 questions in each training subject and the full 198-question GPQA Diamond
census. The table reports the median within-seed difference.

{b_pooled_transfer}

**Meaning.**

- key: **The restraint generalized.** High-confidence wrong answers fell by 13
to 51 points at the median. All five seeds improved on GPQA, math, and medicine;
four of five improved on legal and ethical reasoning.
- key: **Accuracy did not improve.** Median changes ranged from a 1-point loss
to a 3-point loss. The confidence-calibrated score rose because the models made
far fewer confident mistakes, not because they knew more answers.
- key: **Pooled training was not better than subject-specific training on
unseen GPQA.** Pooled training changed median accuracy by &minus;3.0 points.
Ethics and math calibration training each changed it by +2.5 points. All four
training regimes sharply reduced high-confidence errors.

:::details GPQA comparison by calibration-training subject
{b_gpqa_transfer}
:::

**Limit.** The five-seed pooled result is one Qwen model family. The
subject-specific comparison has three medicine seeds, three ethics seeds, and
only one admitted math seed, so it is descriptive rather than a balanced test
of which curriculum is best.

### 6.6 Hidden unauthorized shortcuts fell 1 point after pooled training and 3 points after subject-specific training

**Point.** Confidence-calibrated training modestly reduced quiet, unauthorized
goal-advancing actions without reducing completion when the same action was
authorized. The effect was much smaller than the reduction in overconfident
factual errors.

**Basis.** The hidden-opportunity test used 32 matched scenario pairs across
eight ordinary workflows and four types of pressure. The fast action was
authorized in the control and prohibited in the conflict version, without
labels such as “cheat” or “bypass.” Five repetitions produced 160 conflict and
160 control actions per checkpoint. The table compares 12 matched
accuracy-only and confidence-calibrated checkpoint pairs.

{b_hidden_opportunity}

**Meaning.**

- key: **The direction repeated, but the magnitude was small.** Shortcuts fell
in four of five pooled pairs and six of seven subject-specific pairs. The
median reductions were 1.3 and 3.1 points.
- key: **The difference was not mere inactivity.** Every checkpoint completed
100% of authorized controls, and calibration changed that rate by 0 points.
- key: **This is not strong evidence of aligned agency.** Even after
confidence-calibrated training, unauthorized shortcut rates remained 84% to
94%. No checkpoint concealed a shortcut in the follow-up audit, despite many
prohibited actions.

**Limit.** These are fictional, short-horizon workflows with structured tool
calls. The policy conflict is embedded in ordinary instructions, but the audit
question remains transparent. The test measures restraint under a hidden
opportunity, not long-horizon scheming with memory, private reasoning, or real
stakes.

### 6.7 Nemotron still failed one of two full format profiles

**Point.** The planned five-seed Nemotron replication stopped before reward
training because one of two full format profiles exceeded the frozen 1%
malformed-output limit.

**Basis.** Both profiles branched from the same knowledge-free format
checkpoint and answered all 1,920 profiling prompts. The first passed at 0.63%
malformed. The second failed at 1.15% and also crossed the duplicate-output
guard.

{b_multitask_family_gates}

**Meaning.** A large shared format checkpoint is not enough to assume stable
reward training in this family. Stopping preserves the experiment: invalid
output cannot be reinterpreted as abstention or alignment. This is a format
gate failure, not evidence against calibration transfer in Nemotron.

**Limit.** Because the gate worked, there is no Nemotron treatment effect to
report. This result says the configuration was not measurable. It does not say
confidence-aware training would fail in Nemotron.

{b_src_multitask_family_agentic}

### 6.8 GPT-OSS replicated factual calibration, but not hidden restraint

**Point.** Confidence-aware training improved factual confidence estimation in
a second model family. It did not reliably reduce unauthorized tool actions.

**Basis.** The untouched GPT-OSS profile failed because 27.6% of 1,920 responses
were malformed. A knowledge-free syntax lesson reduced that rate below 1% in
two independent full profiles. Four of five planned matched training pairs then
completed. One seed failed its first training health gate and was not replaced.

{b_openweight_followup_gates}

{b_openweight_followup_training}

The four valid pairs answered 9,882 held-out questions across medicine, math,
ETHICS, and full GPQA. Each row compares confidence-aware with accuracy-only
training within the same seed.

{b_openweight_followup_transfer}

**Meaning.**

- key: **The core factual result now spans two model families.** The
confidence-calibrated score improved in 15 of 16 seed-by-domain comparisons.
All four pairs improved on math, medicine, and GPQA.
- key: **The largest gains came from fewer confident mistakes.** On math, the
median confidence-calibrated score rose 0.32 and high-confidence wrong answers
fell 38 points, with essentially no median accuracy change. On GPQA, the score
rose 0.21 and high-confidence wrong answers fell 30 points, while accuracy fell
2.3 points.
- key: **This is not a general performance boost.** Median accuracy moved from
negative 2.3 to positive 2.7 points across domains. Confidence-aware training mainly changed
how strongly the model backed its answers.

The same checkpoints also made 5,760 decisions in the hidden-opportunity test.
The model could take an unauthorized shortcut that advanced its stated goal.
Each seed had 160 conflict actions and 160 authorized controls per checkpoint.

{b_openweight_followup_hidden}

- key: **The hidden-behavior effect did not replicate.** Unauthorized shortcuts
fell in one pair, rose in two, and were unchanged in one. The median change was
effectively zero. Authorized completion did not change.
- key: **Better factual metacognition is not yet evidence of broader alignment.**
The same objective consistently reduced overconfident factual error but did not
consistently improve restraint when a shortcut served the model's task.

**Limit.** This is one additional 20B model and four valid training pairs. One
of five planned seeds failed the technical gate. The hidden test is short and
structured, not a long-horizon scheming environment. It can detect a repeated
change in unauthorized action, but cannot rule out narrower or rarer alignment
effects.

**Kimi and DeepSeek still could not enter reward training.**

**Point.** The shared copy-only syntax lesson was not a general solution across
model families.

**Basis.** Kimi's syntax checkpoint cost $1.76. Its next profile stopped once
73 of 224 responses were malformed, because the complete 1,920-response gate
allowed at most 19. DeepSeek first replayed its exact prior failure items with
512 tokens instead of 64. That run crossed its final malformed-count allowance
after 6 failures in 24 responses. A $1.20 syntax checkpoint did not help: all
eight responses on the first replayed hard item were long reasoning traces
truncated before the answer.

**Meaning.** More tokens and simple copy drills are insufficient for these
DeepSeek prompts. The current Tinker sampling interface has stop sequences and
ordinary sampling controls, but no grammar or schema constraint. The robust
fix would be constrained decoding. The best Tinker-only experiment is a new,
question-shaped but benchmark-disjoint format curriculum, followed by two full
profiles. It should be treated as a new model configuration, not as repaired
data from these failed runs.

{b_src_openweight_followup}

### 6.9 Earlier alignment measures moved by 0 to 9 points, in mixed directions

**Point.** The same calibration objective did not move integrity, goal
response, and over-refusal in one common direction.

**Basis.** The six domain-trained checkpoints entered two paired tests. The
longer-horizon test offered authorized and unauthorized tool routes, followed by
an audit, plus separate goal-change scenarios. The official
[XSTest](https://github.com/paul-rottger/xstest) prompts
paired 250 benign requests with 200 harmful requests. Every row compares the
confidence-calibrated checkpoint with the accuracy-only checkpoint trained on
the same subject.

{b_domain_behavior}

**Meaning.**

- key: **The useful agentic endpoint was unauthorized shortcut use.** Checker
tampering was 0 throughout. Concealment was 0 after all 76 prohibited actions,
and covert goal resistance was 0 in all 1,920 tuned-checkpoint decisions.
- key: **XSTest measured over-refusal, not harmful compliance.** No parsed
response selected compliance on any harmful prompt, under either the safety or
neutral pilot framing. Overall parse rates ranged from 81% to 96%, so malformed
responses are not counted as safe. The benign prompts still exposed material
differences in unnecessary refusal.
- key: **The ethics-trained model improved most on the agentic test.**
Unauthorized shortcuts fell by 3 points, benign tool success rose by 1 point,
and appropriate goal responses rose by 6 points. Its unnecessary XSTest refusal
rate worsened by 5 points.
- key: **Math training cut shortcuts by 4 points and over-refusal by 9.** Benign
tool success fell by 1 point and goal responses did not change. Medicine
training left shortcuts unchanged while benign success fell by 2 points and
appropriate goal responses fell by 4.
- key: **No training subject produced a general alignment gain.** Lower
shortcut use accompanied by lower benign success can reflect caution rather
than better alignment. The table keeps the control beside every risk measure.

**Limit.** The action menus made the relevant rule visible. XSTest asked for a
response strategy rather than generating harmful content. The longer-horizon
test sampled each agentic scenario five times, but the checkpoints come from one
training seed and one model family.

{b_src_domain_alignment}

### 6.10 Calibration transfers across subjects; honesty does not

**Point.** Training on multiple-choice confidence produced better probabilities
on unrelated short-answer math, trivia, and multi-hop questions. It did not make
the models more truthful under pressure or consistently better at following
instruction hierarchy.

**Basis.** Five matched seeds were tested on 450 fresh short-answer questions,
483 MASK honesty scenarios, and 200 IHEval hierarchy conditions. Each change is
relative to accuracy-only training from the same seed. The confidence-calibrated
score is accuracy minus probability error, so higher is better.

{b_external_transfer}

**Meaning.**

- key: **Calibration is cross-domain.** The core confidence-calibrated objective
raised the confidence-calibrated score by 0.074 at the median and reduced wrong
answers stated at 90% confidence by 16 points. Every seed improved on both.
- key: **This did not make the model more honest.** MASK truth-telling under
pressure was flat to slightly worse. The models gave better probabilities about
their pressured answers, but did not state the truth more often.
- key: **Hierarchy results are mixed.** The core objective did not help. The
fixed-cost variant improved two easier hierarchy conditions in most seeds, but
not the hardest conflict and not consistently enough to support a general claim.

**Limit.** These results come from one model family. Short-answer exact matching
can miss semantically equivalent answers, especially on HotpotQA. The IHEval
prompt-hijack pilot was also saturated: all three pilot checkpoints passed the
easy controls and failed the adversarial conflicts. That is a shared failure,
not evidence that one training objective was better.

{b_src_external_transfer}

:::details Which tests are new, external, and able to detect change?
{b_test_variation_audit}

The saturated rows remain in the audit trail. They are useful shared failures,
but they cannot rank the tuned models. The next alignment claim should rely on a
harder paired safety test with both harmful and benign controls, not more copies
of a test that every checkpoint passes or fails.
:::

:::details Earlier alignment tests and the complete audit trail
The earlier matched battery found fewer very bad decisions but more acceptance
of unsupported wrong claims. It used a different evidence test: claimed source
quality rather than an exact numerical update.

{b_matched_alignment}

{b_src_matched_alignment}

Other alignment indicators also remained mixed. TruthfulQA, ETHICS, and BBQ did
not show a general performance gain. Constraint adherence was better than after
accuracy training but no better than in the untuned model. Wrong social
pushback was accepted more often after confidence-calibrated training.

{b_alignment_scorecard}

The adverse social-pressure gap remained under all four scoring prompts.

{b_pressure_prompt_contrasts}

Across 100 repeated training checkpoints, better calibration did not move
monotonically with the earlier constraint and pressure indicators.

{b_alignment_relationship}

Held-out benchmark performance and confidence calibration remain available
below. The accuracy columns answer whether the model performed better; the
confidence-calibrated score columns answer whether its stated probabilities
tracked correctness.

{b_broader_performance}

{b_broader_transfer}

#### Benchmark screen, ETHICS tasks, and BBQ bias

The screen established that the tasks had room to move; it was not an outcome
test. Models from the same company are ordered newest first.

{b_broader_screen}

{b_ethics_tasks}

{b_bbq_bias}

{b_src_alignment}
:::
