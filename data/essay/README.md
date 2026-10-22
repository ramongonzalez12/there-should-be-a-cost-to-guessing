# Essay data

The data behind the Below Zero essay "There should be a cost to guessing", from
graded answers to every number and chart. Everything here comes from one
frozen source, `v638-lunajson-228f0788`: 77 models answering the same 800
questions (100 from each of eight benchmarks) under four prompts, graded with
GPT-5.6 Luna judging MATH-500 equivalence and exact or letter matching
everywhere else. No API key is needed to use or rebuild any of it.

## What each folder holds

| Folder | What it is | Rows or files |
|---|---|---|
| `figures/` | One CSV per exhibit on the page, named by its figure id: exactly the rows the chart or table draws. Columns are named as the chart's axes and series; percentages and points are on the page's 0 to 100 scale, to four decimals. | 25 files |
| `tables/` | The processed tables the essay is built from (cohort, per-cell, per-model, and per-benchmark summaries, reliability bins, bootstrap intervals, thresholds). | 29 files |
| `graded/responses.csv.gz` | One row per graded response: model, benchmark, item id, prompt, parsed answer, reference answer, stated confidence, verdict, judge, tokens, cost, latency, provider. No question text and no model output beyond the parsed answer. Columns are defined in `docs/data-dictionary.md`, "Essay graded rows". | 181,628 rows |
| `graded/receipts/` | The MATH-500 judge swap: each re-judged row's verdict and the verdict it replaced, and the swap's summary receipt with its acceptance tests. | 6,359 rows |
| `graded/behaviour/` | The two behavior benchmarks built for this study (see "Benchmarks we developed"): `shortcuts.csv.gz` and `pushback.csv.gz`, ids, model, condition, and grades only, and `source.json`, their provenance. | 34,560 and 11,686 rows |
| `inputs/` | What the exhibits read that is not a graded row: model names and listing dates, the 14 item skips, the source record, the frozen summaries of the training experiments (Part 3), and the labels and parameters some charts draw, as the essay page prints them. Each entry names its lab source and commit. | 4 files |
| `key-numbers.json` | The values the essay's sentences quote. | |
| `manifest.json` | The sha256 of every file the data step writes, and whether it was rebuilt or carried. | |

Figure CSV labels track the essay's current copy. A copy change to an
exhibit's label (a panel head, a column the page stops printing) is a change
to the data step's inputs: `inputs/figure-inputs.json` records the new label
with the page commit and the essay item that made it, and the step rewrites
the CSV. Labels are never edited by hand in a CSV. The roster's reason for
each model left out works the same way: `figure-inputs.json` records each
model's cause (the usability gate at the 10- or 50-question check, a provider
failure on its OpenRouter route, or collection unfinished) with the record it
came from, and the step words it beside the responses the model returned.

The two worked examples below show how a stranger checks a chart.

- `figures/fig-scissors.csv` is [1.B]: per benchmark, accuracy and stated confidence on the baseline prompt, easiest first. The Summary's copy of the chart draws the same file.
- `figures/fig-model-thresholds.csv` is the confidence-threshold exhibit: for each model and for all models with equal weights, the share of questions with an allowed answer and the wrong answers among them, ungated and at 80%, 90%, 95%, and 100%.

## Rebuilding every number

```bash
python scripts/essay_data_step.py --check        # graded rows -> tables -> figures -> key numbers; diffs against this folder
python scripts/essay_data_step.py --from-tables  # only figures, key numbers, and manifest, from the committed tables (seconds)
```

`--check` takes about seven minutes; two seeded bootstraps are most of it. It
exits nonzero on any difference. It uses the same analyzers the essay used
(`scripts/analyze_notation_artifact.py`, `scripts/export_warning_comparison.py`,
`scripts/export_battery_thresholds.py`) on Row records built from the graded
rows, and the bootstrap draws follow the file's row order, so the intervals
reproduce exactly.

Fifteen tables are rebuilt from the graded rows. Fourteen are carried: they
were derived from the lab's frozen analysis of inputs that are not graded
rows of this source, so they are not rebuildable from the public rows, and
`--check` compares them rather than rebuilding them:

- the training experiments of Part 3: `common_training_pooled_levels.csv`, `common_training_reliability_bins.csv`, `common_training_thresholds.csv`, `common_training_trajectories.csv`, `confidence_only_training_accuracy_cells.csv`, `confidence_only_training_accuracy_scope_summary.csv`, `confidence_only_training_manifest.json`, and `confidence_only_untouched_base_prompts.csv`;
- the confidence-gate design profiles: `design/gate-model-distributions.json`, `design/gate-observed-distributions.json`, and `design/v623-baseline-extension.json`;
- `models_catalog.csv` (the OpenRouter model list the essay read), `essay_cohort_manifest.json`, and `battery_confidence_thresholds_manifest.json` (build records; their file hashes refer to the lab's copies).

Two rebuilt tables keep rows from earlier studies as they are:
`notation_artifact_cells.csv` and `notation_artifact_summary.json` recompute
every row and block of this battery and carry the others. The Part 3 figure
CSVs are computed from the frozen summaries in `inputs/figure-inputs.json`.
Three exhibits are mathematical illustrations ([2.B], [2.C], and the
calculation table under [2.C]); their files hold the plotted values, computed
from the formula in the caption (`src/belowzero/rules.py`, `quadratic`).

## Benchmarks we developed

Two of the essay's behavior measures use benchmarks built for this study.
Each has a reader's doc covering what it measures, the items, the prompt the
model saw, the grading, how the essay uses it, and its limits:

- Unauthorized shortcuts, `docs/benchmarks/shortcuts.md`: in 64 fictional
  workplace scenarios, the share of choices that take a forbidden shortcut.
- Pushback, `docs/benchmarks/pushback.md`: over 150 held-out questions, the
  share of conversations in which the model gives in when the user names a
  wrong option. [3.F] draws it.

Their graded records are in `graded/behaviour/`, with no question text, no
scenario text, and no model output. `python scripts/essay_data_step.py
--behaviour` rebuilds the essay's behavior levels, the [3.F] column, and the
pushback-by-confidence figures from them and compares each to 1e-9 (seconds);
`--check` runs the same comparison.

## The census figures

The essay's census counted 1,089,024 published responses on 36 benchmarks, of
which 0.69% contain an uncertainty or decline phrase. [1.A] compares the 22
benchmarks with one checkable answer and no feedback to the model: 1,023,437
responses, 0.45% (the page rounds to 0.4%). The 14 left out are rubric-graded
or not closed-form (5) and agentic tasks where the model can see an action
fail (9); `scripts/census_exclusions.py` lists them and prints both figures.

## Benchmarks: terms and what ships

| Benchmark | License | What ships here |
|---|---|---|
| MMLU-Pro | MIT (Hugging Face); Apache 2.0 (GitHub) | ids, parsed answers, reference letters |
| GPQA Diamond (`gpqa_parity`) | CC BY 4.0 (data); MIT (code) | opaque hashed ids, parsed and reference letters; the authors ask that examples not be revealed in plain text, and none are |
| MedMCQA | Apache 2.0 (Hugging Face); MIT (GitHub) | ids, parsed answers, reference letters |
| MATH-500 | No license on the dataset card; AoPS claims the problems and solutions | ids, parsed answers, and verdicts; reference answers are withheld |
| BoolQ | CC BY-SA 3.0 | ids, parsed answers, yes or no references |
| TruthfulQA (multiple choice) | Apache 2.0 | ids, parsed answers, reference letters |
| ETHICS (hard test) | MIT | ids, parsed answers, references |
| BBQ | CC BY 4.0 | ids, parsed answers, references |
| Census source (EvalEval datastore) | MIT; records stay under their sources' terms | counts and rates only |

No benchmark question text is in this repository; see each benchmark's own
terms before joining these ids to its questions.

A model can copy question text into its answer, so `parsed_answer` ships only
when it cannot carry any. On the five multiple-choice benchmarks (MMLU-Pro,
GPQA, MedMCQA, TruthfulQA, BBQ) it ships only as option letters ("B", "B, C",
"D and I"). On the others it ships only when it is at most 60 characters long
and has no run of three plain words (LaTeX commands such as `\frac` do not
count). Any other parsed answer is blank; its verdict, grade, and confidence
are unchanged, so no table or figure moves. 45 of 181,628 rows are blanked
this way (40 MATH-500, 2 GPQA, 2 MMLU-Pro, 1 BBQ). The rule is
`answer_cell_ok` in `scripts/export_public_release.py`, and the release
export fails if any shipped cell breaks it.

## Canary

Every graded file carries the BIG-bench canary string on its first line (the
judge swap's summary receipt and the behavior records' `source.json` carry
it as a `canary` field), so training-corpus filters
that honor it drop these files. Read the CSVs from line 2, for example
`pandas.read_csv(path, skiprows=1)`.

## Using the graded rows

- This is evaluation data, not a calibration training set. Training a model on
  other models' stated confidences teaches it to imitate their confidence, not
  to know when it is right.
- The rows record outputs of models served through OpenRouter, under each
  provider's terms (the `provider` column names the serving provider). Some
  model licenses attach duties to models trained on their outputs: Llama
  (name the model with a "Llama" prefix and show "Built with Llama"), Qwen 2.5
  ("Built with Qwen" or "Improved using Qwen"), and Gemma 2 and 3 (the Gemma
  terms and prohibited-use policy follow the trained model). DeepSeek's terms
  ask that AI-generated content be disclosed as such.

## License

The files in this folder are released under CC BY 4.0 (`LICENSE-DATA` at the
repository root), except where a benchmark's own terms, listed above, govern
its ids and reference answers.
