# There should be a cost to guessing

**Benchmarks score a wrong answer the same as no answer. So models guess.**

This repository holds the data behind the essay at
[ramongonzalez.com/cost-to-guessing](https://ramongonzalez.com/cost-to-guessing/),
with the scoring code and a check that rebuilds every number in the essay from
the graded rows without an API key. The code that called, evaluated, and
trained the models is not included.

```bash
pip install -e ".[dev]"
python scripts/essay_data_step.py --check   # graded rows to every table, chart, and number; about 7 minutes
pytest                                      # the test suite; no key, no network
python scripts/build_site.py                # rebuild the published pages from the committed CSVs
```

## The measurement

Every per-question model output in the public
[`evaleval/EEE_datastore`](https://huggingface.co/datasets/evaleval/EEE_datastore),
scanned for any of about 18 ways of declining to answer. The scan is
deliberately over-broad and covers the whole generation, reasoning traces
included.

| | |
|---|---|
| responses scanned | **1,089,024** |
| models | 104 |
| benchmarks | 36 |
| contain any decline phrase | **0.69%** |
| state a numeric probability | **0.25%** |

On GPQA, of the 188 responses that explicitly say they cannot determine the
answer, **184 (97.9%) commit to a letter anyway.** The uncertainty is already
in the text, and nothing in the pipeline has anywhere to put it.

`python scripts/census.py` reproduces the whole count in about twenty minutes.
It reads the public archive and queries no model.

## The rule

```
correct  ->  2p - p² - c
wrong    ->     -p² - c
abstain  ->  0
```

The rule is strictly proper: a model's expected score is highest when it
reports the probability it actually believes. The assertion cost `c` prices the
act of answering; under binary grading `c` is zero for everyone.
`scripts/properness.py` checks the math numerically, and
`site/below-zero/why-linear-fails.html` gives the argument, including why the
obvious linear rule cannot work (`docs/methodology-scoring-rule.md` is the
original design note behind it). The scoring rules themselves are in
`src/belowzero/rules.py`, and the metrics are computed in SQL
(`src/belowzero/metrics.sql`).

## The essay's data

Every chart and table in the essay has its numbers here, and every number
rebuilds from graded answers:

```bash
python scripts/essay_data_step.py --check   # graded rows -> tables -> figure CSVs -> key numbers; diffs against data/essay
```

| path | what it is |
|---|---|
| `data/essay/figures/` | one CSV per exhibit, named by its figure id: exactly the rows the chart or table draws |
| `data/essay/tables/` | the processed tables the essay is built from |
| `data/essay/graded/` | 181,628 graded responses (77 models, 800 questions, four prompts): parsed answer, stated confidence, verdict, judge, tokens, cost, and provider, with no question text and no raw output |
| `data/essay/graded/receipts/` | the MATH-500 judge swap: each re-judged row and the swap's acceptance tests |
| `data/essay/README.md` | what each file holds, each benchmark's terms and what ships for it, the canary, and the census figures |

Every model call behind these rows, and every call to the MATH-500 judge, went
through OpenRouter to paid endpoints. At the time of writing the account
disallows endpoints that train on request data, and no call used a free
endpoint; providers may retain requests under their own policies. Training,
and the evaluation of trained checkpoints, ran on Tinker (Thinking Machines).
The census read a public archive.

## What's here

| path | what it is |
|---|---|
| `data/essay/` | the essay's figure CSVs, tables, graded rows, and judge receipts (CC BY 4.0, `LICENSE-DATA`) |
| `data/processed/` | the committed CSVs behind the earlier findings pages, with provenance manifests |
| `data/slices/` | frozen item-ID lists (IDs only, no benchmark text) |
| `data/behaviour_items.json` | the self-authored prompts of an earlier behavior battery (canary included) |
| `src/belowzero/` | the scoring rules, the prompts and response parser, the announced scoring contracts, the benchmark registry, and `metrics.sql`; standard library only |
| `scripts/` | the essay data step, the census, the scoring math, the analyzers that wrote the processed tables, and the site generators |
| `content/` and `site/below-zero/` | the earlier findings pages' prose and the generated pages ("Below Zero" was the project's working name); CI proves the pages rebuild byte for byte from the CSVs |
| `docs/` | the scoring-rule and census methods, the data dictionary, and `docs/benchmarks/`, the two behavior benchmarks we developed |
| `tests/` | the test suite; it runs with no key and no network |
| `REPRODUCING.md` | what you can rebuild here, and what you can only audit |

Hypotheses, primary outcomes, and stop rules were fixed in advance:
[PREREGISTRATION.md](PREREGISTRATION.md) and
[PLURAL_PRUDENCE_PREREGISTRATION.md](PLURAL_PRUDENCE_PREREGISTRATION.md).

## What's not here

This repository is a curated snapshot of a private research repository. Not
included:

- **The code that called, evaluated, and trained the models**: the runner that
  sent the prompts, the judge grading, the evaluation batteries, and the
  training recipe. The graded rows it produced are
  here, and every number in the essay rebuilds from them.
- **The research notebook.** Provenance manifests in `data/processed/` cite
  its dated notes by filename; every released input is also pinned by sha256
  and row count in the manifests themselves.
- **Raw responses.** They can quote benchmark questions, so the graded rows
  ship instead, with every field but the text.
- **Benchmark question banks.** They are downloaded from their original
  sources under their own terms (`src/belowzero/datasets.py` names each one).
  No question text is committed here; the frozen slices are opaque item IDs.
- **Working pages**: the change log, the report draft, the plan, and the
  design lab. Two earlier briefs and the first essay revision
  (`site/below-zero/essay.html`, v2.7, August 2026) ship for comparison and
  say so in a banner; the essay itself is the published page linked above.

## Citing

See [CITATION.cff](CITATION.cff). License: MIT for the code; CC BY 4.0 for
the data (`LICENSE-DATA`); third-party terms in `NOTICE`.

Claude was used substantially for writing the analysis code, the scoring-rule
derivations, and drafting the page. The research questions, the scoring-rule
design, and every claim are the author's.
