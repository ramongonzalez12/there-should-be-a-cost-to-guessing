# Data dictionary

Everything in `data/processed/` is committed and is the sole source for the
published page. `data/raw/` and `data/cache/` are gitignored and regenerable.

## Denominators: read this before any column named accuracy, confidence or gap

The same word names different quantities in different files, and the
2026-09-02 review found the wrong pair subtracted in three places. Every
column below is defined once here; a producer that departs from these
definitions must name its column differently.

| column family | denominator | abstentions | malformed responses |
|---|---|---|---|
| `accuracy`, `overall_accuracy`, `mean_accuracy` | every scheduled response | count as wrong (0) | count as wrong (0) |
| `accuracy_among_answers`, `acc_attempted`, `corrected_accuracy` (notation tables) | attempted responses with a usable probability | excluded | excluded |
| `confidence`, `mean_confidence_among_answers`, `mean_p_attempted` | the same attempted-with-probability set as the row above | excluded | excluded |
| `confidence_gap`, `overconfidence`, `signed_gap` | `confidence` minus `accuracy_among_answers`, both on the attempted set | excluded from both terms | excluded from both terms |
| `calibrated_score`, `confidence_adjusted_accuracy`, `quad_score` | every scheduled response; item score is `y − (p − y)²` | score 0 | score −1 (a confident error) |
| `high_confidence_error_90_rate`, `tail` | every scheduled response; counts wrong attempted answers at p ≥ 0.9 | not counted | not counted |
| `usable_confidence_rate`, `coverage` | every scheduled response; share that is attempted, well formed, with p in [0, 1] | not usable | not usable |
| `answer_rate` | every scheduled response; share not abstaining | not answered | counted as answered only if the answer line parsed |

Two consequences worth stating. `confidence − accuracy` (all-question accuracy)
is not the overconfidence gap; it exceeds the gap by roughly the abstention
plus malformed rate, which is largest in the confidence-trained arms. And the
identity `calibrated_score = overall_accuracy − mean Brier` holds only under the
conventions in the table (abstention as p = 0 on a wrong answer, malformed as
p = 1 on a wrong answer); files that publish a `brier_loss` column as the
residual `overall_accuracy − calibrated_score` are using that convention.

Probability tokens: an integer is a percentage ("85" is 0.85), a token written
with a decimal point whose value is at most 1.0 is a fraction ("0.85" is 0.85).
Before 2026-09-02 the runtime parser divided every token by 100, so "0.85" was
stored as 0.0085; every retained run database was re-parsed and re-graded
from raw text on that date (by the re-grading script; ledger in `runs/`).

## Private confidence-only accounting v2

These definitions are versioned separately from the historical tables above.
`joint-resolved-metrics-v2` consumes `native-extraction-assessment-v2`. Both hosted
and checkpoint exporters use the same implementation. It preserves stored
extraction and correctness judgments; it does not reparse or semantically label
responses. **A and J mean native extraction validity only.** Semantic answer
validity and semantic joint validity remain unresolved (NA).

| Field | Numerator / denominator or population |
| --- | --- |
| `planned_n` (N) | Exact frozen item identities per entity, domain and arm |
| `returned_unique_n` (R) | One successful canonical response per planned identity |
| `native_answer_valid_n` (A) | Returned rows with a true native extraction flag |
| `confidence_valid_n` (C) | Returned rows with requested, strictly valid finite p in [0,1] |
| `native_joint_valid_n` (J) | Both native extraction and requested confidence valid |
| `calibration_eligible_n` (K) | J rows with resolved boolean correctness |
| `native_answer_per_planned` | A/N, achieved coverage when execution is incomplete |
| `confidence_per_planned` | C/N, achieved coverage when execution is incomplete |
| `native_joint_per_answer` | J/A |
| `native_joint_per_planned` | J/N |
| `native_answer_per_returned`, `confidence_per_returned` | A/R and C/R |
| `all_question_accuracy` | Native correct/N, only with complete execution and all grades resolved |
| `native_answer_accuracy` | Native correct among A / A, only when all A grades resolve |
| `mean_confidence_joint_resolved`, `accuracy_joint_resolved` | Mean p and mean y on exactly K |
| `confidence_gap_joint_resolved`, `brier_joint_resolved` | Mean (p-y) and mean (p-y)² on exactly K |
| `quadratic_all_lower`, `quadratic_all_upper` | Sum native 2py-p² / N, with missing-p bounds [0,1] for y=1 and [-1,0] for y=0 |

Unreturned requests and transport failures stay pending, not wrong or abstaining.
Invalid returned native answers retain their native grades; missing confidence
cannot erase a correct answer. Duplicate successful responses are quarantined,
never selected by score or arrival order. Unknown extraction and unresolved grades
remain separate from known-invalid extraction and incorrect grades. Zero
denominators and confidence not requested are NA (JSON null, CSV blank).

Four native states partition classified returned responses; unresolved extraction
has its own count. Completed, extraction-resolved confidence arms reconcile to N.
Paired 4-by-4 matrices use identical frozen item identities and show missing and
unclassified pairs separately. Standard-to-confidence comparisons have answer
validity gains/losses and NA confidence transitions. Intersection calibration is
a selected-population sensitivity, not a full treatment estimate. Reliability
bins use K with ten fixed width-0.1 bins; p=1 is included in the last bin.

Aggregates pool items within each model/checkpoint, not across entities. Complete
hosted arms have equal benchmark counts. Checkpoint domain counts differ; no
equal-domain or cohort-wide headline is introduced by this implementation.
The original confidence-valid-population calculations remain in explicitly named
`historical-v1` exports. All semantic claims remain provisional.

## Regenerating data/processed

In the lab, `make processed` runs every producer script in dependency order
(a lab-only target: the public Makefile has none, because the producers read
run databases that do not ship). Producers
read only `runs/` (gitignored raw artifacts) and `data/cache/`, so a clone
without those directories cannot regenerate the tables; `runs/RECOVERY.md`
and each `*_manifest.json` record which raw file, by sha256, each table came
from.

## census_summary.csv

Headline totals for the census. One row per metric so the page and the data
cannot drift apart.

| metric | meaning |
|---|---|
| `responses_scanned` | graded responses examined (excludes ungraded rows and game arenas) |
| `models`, `benchmarks` | distinct counts |
| `decline_phrase_count`, `decline_rate` | responses containing any of ~18 decline phrases anywhere in the generation |
| `stated_confidence_count`, `stated_confidence_rate` | responses containing a `confidence: N%` pattern |
| `empty_generations` | responses with no text at all |

## census_by_benchmark.csv

One row per benchmark. `accuracy` is 0 where the source does not carry a binary
correctness flag (e.g. HealthBench, IFEval) — read those rows as missing, not
as zero accuracy.

`n_unextracted` equals `n_responses` for most benchmarks simply because that
schema version does not populate `answer_attribution`. Only `gpqa-diamond`,
`math-mc`, `gsm-mc`, `judgebench`, `reward-bench-2` and `lingoly` carry real
extraction data. **Do not read this column as a refusal rate.**

## census_by_model.csv

One row per model with at least 50 graded responses. Cross-model comparison here
is not meaningful — different models appear on different benchmark mixes.

## census_sensitivity.csv

How the headline decline rate moves under the two judgement calls that could
plausibly change it: how broad the phrase list is, and how much of the response
is searched. Computed on the GPQA Diamond subset (13,662 responses, 69 model
runs) where the full generations are available locally.

| column | meaning |
|---|---|
| `search_scope` | whole generation, or only the last 300 / 100 characters |
| `phrase_list` | narrow (3 unambiguous phrases), moderate (7), or broad (~18, the one used) |
| `n_declines`, `decline_rate` | responses matching under that combination |

The headline uses the most generous combination available and still finds under
1%. Under the strictest — final 100 characters, narrow list — the rate is
**0 of 13,662**. Tightening the definition strengthens the finding.

## hle_quadratic.csv

Humanity's Last Exam runs rescored under the quadratic rule, using the
probabilities the models themselves stated (HLE's prompt asks for one).

| column | meaning |
|---|---|
| `acc` | fraction correct among responses with a parseable probability |
| `quad` | mean score under `2p − p²` / `−p²`, no assertion cost |
| `c09`, `c25` | the same with assertion cost 0.09 and 0.25 |
| `brier` | mean squared error of the stated probability |
| `reliability` | Murphy reliability — **pure miscalibration**, recoverable by rescaling the numbers alone. Lower is better |
| `resolution` | how much the stated probability actually discriminates. Higher is better; has to be earned |
| `uncertainty` | `base_rate × (1 − base_rate)`. A property of the task, not the model |
| `recal` | `quad` after out-of-sample isotonic recalibration (5-fold cross-fit) |
| `gain` | `recal − quad`. Points available from calibration alone |

`brier = reliability − resolution + uncertainty`.

The Claude row has n = 108 of 1,798 responses because the agentic HLE runs
rarely emitted a parseable probability. Treat it as indicative, not comparable.

## The response database

`belowzero.db` is gitignored — it is large and regenerable. Schema in
`src/belowzero/store.py`; one row per (model, contract, item, repetition) with
the raw generation preserved verbatim, so any scoring rule can be applied later
without re-running inference.

## Files the essay reads, one line each

Producer, raw input, and the unit of analysis for every processed family the
essay quotes. In the lab, which holds the run databases, the essay's generator,
and its number verifier, they regenerate with
`make regrade && make processed && make essay` (lab-only targets). The essay's own tables, figure
CSVs, and key numbers rebuild from graded rows anywhere with
`python scripts/essay_data_step.py --check` (see `data/essay/README.md`).

| file family | producer | raw input | unit |
|---|---|---|---|
| `census_summary.csv`, `census_by_benchmark.csv`, `census_by_model.csv` | `scripts/census.py` then `scripts/census_tables.py --promote` | the EvalEval datastore stream (`sweep.json`, promoted 2026-09-03; the by-model table floors at 50 responses) | one published response |
| `census_matrix.csv`, `census_matrix_summary.json` | `scripts/census_tables.py` | `sweep.json` | one model x benchmark cell |
| `notation_artifact_cells.csv`, `notation_artifact_summary.json`, `notation_rerun_*.csv` | `scripts/analyze_notation_artifact.py` | `runs/notation_rerun_20260827.db`, `runs/prompt_arm_ident_main_*.db`, `runs/base_model_prompt_main_20260827.db` (all regraded 2026-09-02) | one model x benchmark cell (80 per arm); `abstention_rate` and `malformed_rate` are on the all-scheduled denominator |
| `warning_comparison_levels.csv`, `warning_comparison_band_bridge.csv` | `scripts/export_warning_comparison.py` | the recovered `runs/prompt_only_main_*_20260826.db` and the Aug 27 identification DBs | one response, bootstrapped over models x benchmarks x items |
| `prompt_only_calibration_*`, `prompt_arm_identification_*` | `scripts/analyze_prompt_only_calibration.py`, `scripts/analyze_prompt_arm_identification.py` | the same databases | one model x benchmark cell |
| `training_common_battery_*.csv` | `scripts/export_training_common_battery.py` | `runs/evaluations/training_common_battery_*` and `runs/matched_prompt_interventions_8b20b_20260831.db` | one family x seed on the shared 800 questions |
| `pooled_training_levels.csv`, `calibration_reliability_bins.csv` | `scripts/export_calibration_context.py` | the two families' final evaluation `responses.jsonl` | one family x battery x objective; `untuned` rows are one evaluation per family, `matched_seed_pairs` 0 |
| `seed_dense_knowledge.csv` | `scripts/export_seed_dense_knowledge.py` (carry-forward now opt-in) | ten dense-evaluation `responses.jsonl` | one run x checkpoint on 100 held-out items |
| `confidence_oscillation.csv`, `confidence_oscillation_seeds.csv` | `scripts/analyze_confidence_oscillation.py` | the same dense files (seed 0; every seed) | one arm x checkpoint |
| `multitask_transfer_*.csv`, `multitask_generalization_pairs.csv`, `hidden_opportunity_contrasts.csv` | `scripts/export_multitask_family_agentic.py` | `runs/finetune/multitask_family_agentic_v1/` | one matched training pair (levels pool responses within a pair) |
| `gptoss_subject_transfer_pairs.csv` | `scripts/export_gptoss_transfer.py` | `runs/finetune/gptoss_domain_replication*/` | one admitted matched pair |
| `untuned_transfer_levels.csv` | `scripts/export_untuned_transfer_levels.py` | the untuned rows of the two transfer evaluations above | one family x battery, evaluated once |
| `openweight_plural_prudence_*`, `openweight_external_transfer_*`, `openweight_alignment_*` | `scripts/export_cross_family_completion.py` | `runs/finetune/cross_family_completion_v1/` | one checkpoint x framing; contrasts are matched seeds |
| `plural_prudence_contrasts.csv`, `external_transfer_*`, `matched_alignment_battery_*` | `scripts/export_plural_prudence.py`, `export_external_transfer.py`, `export_alignment_battery.py` | the Qwen batteries under `runs/finetune/` | one matched seed pair x framing |

`battery_cohort.csv`: in `data/essay/tables/`, `max_tokens` and `reasoning` are the October 2026 run's request settings, read from the graded rows (`data/essay/graded/`): the output limit each model's confidence-prompt requests carried, and `default` where the request left reasoning to the provider. The three lab path columns (`control_db`, `rule_db`, `warning_db`) are dropped there. The copies carried in each essay layer's `processed/` keep the earlier battery's settings, from the frozen historical cohort table; those do not describe the October run.

## Essay graded rows (`data/essay/graded/`)

The essay's tier 3 data: one row per graded response behind every empirical
number in Parts 1 and 2 of the essay (source `v638-lunajson-228f0788`, 77
models, 800 items on eight benchmarks, four prompts). 181,628 rows. Line 1 of
each file is the BIG-bench canary string, so training-corpus filters drop the
file (the string is kept out of this document on purpose); read the CSV from line 2 (`pandas.read_csv(path, skiprows=1)`). Rows keep the frozen
source's order, which the data step's seeded bootstrap draws depend on.

What is not here, by design: question text, the model's raw output, the request
and response JSON, provider response ids, and system fingerprints. MATH-500
reference answers are withheld (the problems and answers are AoPS competition
material); its verdicts ship. Booleans are `1`/`0`; an empty cell is missing.

| column | meaning |
|---|---|
| `benchmark`, `item_id` | benchmark key and the item's id (GPQA ids are opaque hashes; no id joins to text in this repository) |
| `model` | OpenRouter model id requested |
| `contract` | the prompt: `standard` (answer only), `confidence` (answer plus confidence; the essay's baseline), `rule` (the scoring rule explained), `warning` (a warning about overconfidence) |
| `rep` | repetition within (model, item, contract); every row is 1 in this source |
| `excluded_from_analysis` | 1 for the 14 user-directed (model, item) skips, which leave every statistic for that model |
| `parsed_answer`, `reference_answer` | the extracted final answer (blank where it could carry question text; see data/essay/README.md), and the benchmark's answer (empty for MATH-500) |
| `confidence` | the stated probability as extracted, in [0, 1]; may be present on a row whose confidence is not usable |
| `answer_status` | `explicit_answer`, `explicit_abstention`, `empty`, `unresolved`, or `pending_semantic_review` |
| `confidence_status`, `confidence_referent` | whether a confidence was stated (`explicit`, `missing`, `unresolved`) and what it refers to (`selected_answer`, `earlier_answer`, `unknown`) |
| `grade_status`, `pending`, `technical_errors` | `RESOLVED` or `PENDING`; interpretation still open; a technical error in the response |
| `correct` | the grader's verdict on the extracted answer (empty when there is no graded answer) |
| `abstained` | an explicit decline (`answer_status` = `explicit_abstention`) |
| `parse_failure` | attempted but not usable: no explicit answer, or (outside `standard`) no usable confidence on the selected answer. Rule 1: these are INCORRECT, never NOT_ATTEMPTED |
| `verdict` | the essay's scoring verdict: `CORRECT` (a resolved correct, usable answer), `INCORRECT`, `NOT_ATTEMPTED`, or `PENDING` |
| `judge` | `luna` (GPT-5.6 Luna judged MATH-500 equivalence) or `deterministic` (letter or exact match, or a rule for empty, unresolved, and declined responses); empty while pending |
| `in_tokens`, `out_tokens`, `reasoning_tokens` | token counts the provider reported |
| `cost_usd`, `latency_s` | the call's charged cost, and wall-clock seconds from request to completion |
| `provider`, `upstream_model` | the serving provider and the upstream model version OpenRouter selected |
| `finish_reason` | the provider's finish reason (`stop`, `length`, ...) |
| `max_tokens`, `temperature`, `reasoning` | the request's output limit, its temperature (empty when not sent), and its reasoning setting (`default` when the request left it to the provider) |

The verdict rules are the essay's (`lab/essay_v628/adapt.py`, `load_rows`):
a correct answer without a usable confidence counts as incorrect in the
confidence, rule, and warning contracts, which is why `verdict` and `correct`
differ on some rows.

`graded/receipts/math500-judge-replacement.csv.gz` lists the 6,359 MATH-500 rows
whose judge of record changed from GPT-4.1 mini to GPT-5.6 Luna: the new verdict,
the verdict it replaced, and where the verdict came from (`reused_receipt`,
`fresh_call`, `fresh_retest_override`). Luna's written reasons are not shipped,
because they paraphrase the question. `math500-luna-receipt.json` is the swap's
summary receipt (judge-of-record counts, the acceptance tests, and the addendum).

`data/essay/inputs/figure-inputs.json` holds what the essay's exhibits read
that is not a graded row: the 12 frozen JSON summaries of the training
experiments (Part 3), the hypothetical students of [2.A], and, as the essay
page prints them, [1.F]'s open-weight flags, the benchmark and census names,
and [2.C]'s belief and reports. Each entry records its lab source path, the
commit that last changed it, and (for files) its sha256. `inputs/models.csv`
names each model as the page does.
