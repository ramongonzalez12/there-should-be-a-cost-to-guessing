# Pre-registration — does announcing the scoring rule change model behaviour?

Written before any inference was run, deliberately. The point of fixing this in
advance is that the space of post-hoc slices here is enormous (6 contracts × 5
models × 3 benchmarks × any penalty value × any threshold), and with that much
freedom you can find a story in noise. Everything below is committed; anything
not listed is exploratory and must be labelled as such.

Status: **partially executed.** The text below is the original draft and has not
been revised. Execution is recorded in the dated addendum at the end of this file.

---

## 1. The claim being tested

Current benchmarks (a) give abstention the same score as a wrong answer, and
(b) never tell the model the rule. Models therefore always guess.

That decomposes into three separable hypotheses, and they can come apart:

- **H1 (announcement effect).** Stating *any* explicit scoring rule changes
  behaviour relative to stating none — even a rule that says "no penalty."
  Tested by `control` vs `guess`, which have identical incentives and differ
  only in whether the rule is spoken aloud. *Nobody has run this comparison.*
- **H2 (dose effect).** Abstention rate rises monotonically with the announced
  threshold t, and error rate falls. Tested by `guess` → `t50` → `t75` → `t90`.
- **H3 (form effect).** For constraint violations, a **gate** ("voids your
  result") suppresses violation more than an equivalently-sized **price**
  ("costs 25 points"). Calabresi & Melamed: a price is a permission.

H1 and H2 are independent. It is entirely possible that announcing a rule moves
behaviour a lot and the *value* of t barely matters — which would mean models
are responding to the salience of the abstention option, not to the arithmetic.
That result would be more interesting than the intended one, and it is the
outcome I would bet on.

---

## 2. Primary outcomes

| | outcome | why this one |
|---|---|---|
| H1, H2 | **abstention rate** (verdict = NOT_ATTEMPTED) | The behavioural variable. Accuracy is downstream and confounded by task difficulty |
| H2 | **error rate** (verdict = INCORRECT) | The thing we actually want to reduce. Accuracy can fall while error rate falls faster — that is a win, and only these two columns together show it |
| H3 | **violation rate** (deterministic checker) | Binary, judge-free |

Secondary: AUROC of stated confidence, Brier, calibration by decile, parse-failure
rate, points under the current `params`, cost per arm.

**Explicitly NOT a primary outcome: accuracy.** Under any confidence target,
accuracy mechanically falls as abstention rises. Reporting accuracy as the
headline would make every intervention look like a regression, which is the
same error the field already makes.

---

## 3. Design

Paired: **every contract sees the identical frozen item slice**, so item
difficulty cancels within a model. Analysis is McNemar on discordant pairs, not
a two-sample proportion test — see `analysis/power.py`. The slice is stratified
by SimpleQA topic × answer_type, deterministic, and cached to disk.

**Stage 1 — existence check.** 50 items × 6 contracts × 2 models = 600 calls,
~$3–8.
Question: does abstention move off zero at all, and do the models honour the
output format? Published control abstention is 0/1980, so at a true rate of 5%,
50 items give a 92% chance of seeing at least one abstention. Detecting movement
off zero is cheap; estimating the rate precisely is what costs.
**Stop rule: if abstention is < 2% in every contract including t90, stop.** The
hypothesis is dead and no amount of further spend rescues it.

**Stage 2 — estimation.** 200 items × 6 contracts × 4 models = 4,800 calls,
~$25–120. Fit abstention against t, estimate calibration, compute risk-coverage.

**Stage 3 — behaviour.** 33 items × 4 contracts × 4 models × **3 repetitions at
temperature 1** = 1,584 calls. Repetitions are not optional here: violation is a
rare near-binary event and single-draw variance would dominate the contrast that
the whole track exists to measure.

Temperature 0 for Stages 1–2 (we want the modal behaviour, not the distribution),
temperature 1 with 3 reps for Stage 3.

---

## 4. Decision rules, fixed in advance

- **H1 supported** if abstention rate under `guess` differs from `control` by
  ≥5 percentage points, in the same direction, in ≥3 of 4 models, McNemar
  p < 0.05 per model.
- **H2 supported** if abstention rate is monotone non-decreasing across
  guess → t50 → t75 → t90 in ≥3 of 4 models, AND error rate is monotone
  non-increasing over the same sequence.
- **H2 refuted** — and this is the outcome to watch for — if abstention jumps at
  t50 and then does **not** track t further. That means models read the rule as
  a mood ("be careful") rather than as arithmetic, and it makes the whole
  threshold formalism decorative. Diagnostic: regress abstention on the
  *break-even probability* t and check whether the slope differs from zero once
  the guess→t50 step is removed.
- **H3 supported** if violation rate under `b_gate` is lower than under
  `b_price` by ≥5 points in ≥3 of 4 models. If they are within 2 points,
  conclude models do not distinguish prices from prohibitions, and report that —
  it is the more consequential finding.

---

## 5. Threats to validity, and what is done about each

**Evaluation awareness — the big one.** A prompt opening "you are scored as
follows" is about as strong an eval cue as exists. Redwood measured Claude
Sonnet 4.5 verbalising eval-awareness on 80–100% of synthetic honeypots;
Anthropic measured Opus 4 blackmailing 55.1% when it believed deployment vs 6.5%
when it believed evaluation. The predicted failure mode of this entire design is
therefore **strategic abstention inside the eval and unchanged behaviour outside
it** — optimising the measurement, not the system.

Mitigations, both committed: (a) add a fifth arm `deploy` that states the
identical rule as an *operating instruction from the deployer* rather than as
grading language, and treat `deploy` vs `t75` as the eval-awareness contrast;
(b) log whether the response verbalises being tested, and report it as a
covariate rather than dropping it.

**Judge error.** Free-form grading uses an LM judge on OpenAI's SimpleQA rubric.
Mitigation: hand-grade a random 50 and report judge–human agreement. If below
90%, the taxonomy numbers are not usable and only the multiple-choice track
stands. NOT_ATTEMPTED is the class most likely to be mislabelled, and it is the
primary outcome, so this check is not optional.

**Checker bluntness.** Deterministic checkers are cheap and consistent but
crude. `test_checkers.py` validates all 33 against hand-written compliant and
violating responses (66/66 currently pass), and `arena.py check` prints flagged
rows for audit. Committed: audit ≥20 flagged rows before reporting any violation
rate. `hier_03` is flagged in-file as the loosest checker in the set.

**Parse failure masquerading as abstention.** On published GPQA runs, treating
unparseable output as "not attempted" lets an 18.7%-accuracy 1B model outscore a
51.5%-accuracy 70B model at t=0.9 purely by emitting garbage. Handled: `grade`
marks parse failures INCORRECT, never NOT_ATTEMPTED, and parse-failure rate is
reported as its own column. **If parse-failure rate exceeds 5% in any arm, that
arm is invalid** — the model was not playing the game we specified.

**Contamination.** SimpleQA and GPQA are both public and in training data. This
does not threaten the *within-model, between-contract* comparison, which is the
only comparison being made, because contamination is constant across arms. It
does invalidate any cross-model capability claim, and none will be made.

**Prompt-format confound.** All contracts share an identical ANSWER/CONFIDENCE
block, so the only text that varies between arms is the rule itself. Contract
prompts differ in length; if a length effect is suspected, the `guess` arm
(long, zero-penalty) versus `control` (short, zero-penalty) partly identifies it.

---

## 6. What would make me abandon the idea

Stated up front so it is not negotiable later:

1. Abstention stays under 2% at t90. The rule cannot be communicated.
2. Abstention moves, but AUROC of stated confidence stays near 0.5. The model
   abstains at random — it has nothing to abstain *on*, and the intervention is
   noise dressed as caution. Published HLE data says AUROC is ~0.68–0.71, so I
   expect this to survive, but it is the sharpest possible failure.
3. Error rate falls only because *everything* falls — i.e. accuracy-given-
   attempted does not improve. That means the model is abstaining on questions
   it would have got right, which is a pure capability tax with no honesty gain.
4. `b_gate` and `b_price` are indistinguishable AND both indistinguishable from
   `b_none`. Announced consequences do nothing for constraints, and the
   behaviour half of the thesis is dead.

---

## 7. Analysis order

Committed sequence, so the analysis cannot drift toward whatever looks best:

1. Parse-failure rate per arm. Invalidate arms above 5%.
2. Judge agreement on the hand-graded 50.
3. H1: control vs guess, McNemar per model.
4. H2: monotonicity across t; slope test with the guess→t50 step removed.
5. AUROC and Brier per arm. If AUROC ≈ 0.5, stop and report failure mode 2.
6. H3: gate vs price vs none, with repetition as a random effect.
7. Everything else is exploratory and will be labelled as such.

---

## 8. Reporting commitment

All arms reported, including failures and abandoned ones. Raw `arena.db`
published alongside any writeup, since the entire argument of this project is
that scoring choices should be inspectable rather than baked into a headline
number. Reporting a single scalar would be self-refuting.

---

## Addendum, 2026-08-17: status of execution

This section is appended, not merged into the text above. Nothing in sections 1
to 8 has been edited since it was written, apart from the status line in the
header, which now points here.

### What has run

**Environment validation (not a hypothesis test), 2026-08-16.** Six current
models over all 198 GPQA Diamond questions, each checked against its published
score under a criterion fixed before the runs. All six landed inside range.
Recorded in `data/processed/gpqa_parity_summary.csv` and on the site's validation
page. This establishes the standard arm, and tests nothing in section 1.

**Stage 1, the existence check, 2026-08-15.** 50 frozen SimpleQA items and 50
frozen items from each of MMLU-Pro, GPQA Diamond, MedMCQA and BoolQ, six current
models, all eight contracts. Recorded in `notes/2026-08-15-live-pilot.md`.

The abandon condition in section 6 item 1, abstention staying under 2% under the
strongest announced rule, was not met. Explicit abstention on SimpleQA rose by 34
points for DeepSeek V4 Pro and Mistral Small 4 and 14 points for Gemini 3.7 Flash
under `quad_both`, the arm that both describes the rule and gives the formula.
The existence check passed and the programme continues.

Two limits on what that establishes:

1. The reported paired contrast is `control` against `quad_both`, which differs
   both in *whether* a rule is announced and in *what* the rule says. That is
   not the H1 contrast of section 1, which is `control` against `guess`. All
   eight contracts were collected, so the H1 comparison remains available, but
   it has not been analysed and is deferred to Stage 2.
2. The abstention outcome is deterministic and judge-independent. The accuracy
   and error columns are not: they depend on an LM judge that has not yet been
   validated against hand labels. Under the section 7 analysis order, step 2
   precedes any inference on those columns, so they remain provisional and are
   not published on the site.

**Fine-tuning final test, 2026-08-16.** Recorded in
`notes/2026-08-16-finetune-final-result.md`, under its own protocol in
`notes/2026-08-16-finetune-final-protocol.md`. This tests whether reward training
on the rule changes a model's calibrated beliefs. It is a separate pre-registered
document, not an outcome in section 2 of this one. Verdict PASS: +0.105 on the
paired quadratic score, 95% interval +0.036 to +0.175.

### What has not run

- `judgecheck` against hand labels. Section 7, step 2. Until it clears the
  agreement threshold, the `NOT_ATTEMPTED` taxonomy columns from free-form
  benchmarks are unusable.
- Stage 2, the estimation run. H1, H2 and H3 and the behaviour track are all
  untested.
- The behaviour track (`b_gate` versus `b_price`). No constraint-temptation item
  has been run.

### Deviations from the design above

- Section 3 anticipated four models; the pilot used six, chosen by a live
  output-contract doctor rather than in advance. The decision rules in section 4
  are written as "≥3 of 4 models" and will be read as the same fraction of
  whatever cohort Stage 2 fixes. That cohort will be frozen before Stage 2 runs.
- Reasoning was disabled where the provider allowed it, to control cost.
  Gemini 3.7 Flash rejects reasoning-off requests and ran at its minimum
  accepted setting. This is a known confound, listed in section 5, and Stage 4
  of the programme re-runs a subset with reasoning on.

## Addendum, 2026-09-02: programme pivot, hypothesis disposition, and a regrade

Appended, not merged. Nothing above this line has been edited.

### What changed between 2026-08-17 and now

The programme's reported outcome moved from the abstention rate of section 2
to three calibration outcomes: the overconfidence gap (mean stated
confidence minus accuracy among answered questions), the pure quadratic score
on a 0-to-100 scale, and the rate of wrong answers stated at 90%+ confidence.
Section 2 lists calibration as secondary; the essay (`site/below-zero/
essay-v2.html`) reports it as primary. The reason is recorded here so the
switch is not silent: Stage 1 showed that the announced rule moves explicit
abstention on free-form SimpleQA, but the eight-benchmark multiple-choice
battery run on 2026-08-26 and 2026-08-27 showed that explaining the rule
barely changes stated confidence or accuracy, and the fine-tuning programme
(not part of this document; see `notes/2026-08-2*`) produced the larger and
replicated effect on calibration. Abstention rates are now reported alongside
the calibration outcomes rather than instead of them.

### Disposition of the three hypotheses in section 1

- **H1 (announcing any rule, `control` versus `guess`).** Analysed on
  2026-09-02 from the Stage 1 tables retained in `results/tables.json` (the
  pilot database itself is not retained, so these cells could not be
  regraded; see below). Across 26 benchmark-model cells the abstention
  difference between `guess` and `control` is within 6 points in 24. The two
  exceptions move in opposite directions (DeepSeek on GPQA fell 28 points
  under `guess`; Mistral on SimpleQA rose 28). There is no consistent
  announcement effect. What moved SimpleQA abstention in Stage 1 was the
  content of the quadratic rule, not the act of announcing a rule. H1 is not
  supported.
- **H2 (monotone response to the threshold dose).** The `t50`, `t75` and `t90`
  arms were never run. Untested, and no longer planned: the programme found
  that the prompt-level lever is weak regardless of dose.
- **H3 (gate versus price on the behaviour track).** Never run. The behaviour
  question was pursued instead through the trained-checkpoint decision
  batteries, which are a different design and are reported in the essay as
  such.

### A grading defect, and what was regraded

On 2026-09-02 a review found that the grader, when an item was missing from
its rebuilt index, substituted a choice-less stand-in that made "A" the
abstention letter. In the 2026-08-27 re-run this affected BBQ and GPQA: 1,090
answers of "A" were recorded as abstentions and the true abstention letter as
a wrong answer. Two further defects were found in the same pass: the answer
letter class stopped at J, so MMLU-Pro's abstention letter K could never
grade as an abstention, and the parser read "PROBABILITY: 0.85" as 0.85% (the
notation artifact already corrected in analysis on 2026-08-27, now fixed at
the source). Every retained run database was re-parsed and re-graded from its
immutable raw text (by the re-grading script; ledger in `runs/`), and every
processed table built on those databases was regenerated. No model was
re-queried. The Stage 1 pilot database of 2026-08-15 is not retained, so its
tables could not be regraded; its multiple-choice abstention cells are
therefore carried with that caveat.

### The recovered control

The 2026-08-26 prompt-study databases were believed lost on 2026-08-27 and a
paid re-run was commissioned to replace them. They were found intact in a
sibling worktree on 2026-09-02, verified by sha256 against the study's
manifest, and restored (`runs/RECOVERY.md`). The warning-prompt comparison is
now computed from those responses against its pre-specified control.
