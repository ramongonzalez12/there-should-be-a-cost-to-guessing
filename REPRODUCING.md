# Reproducing this work

This repository holds the study's data, with the scoring code and a check that
rebuilds every number in the essay from the graded rows without an API key.
The code that called, evaluated, and trained the models is available on
request.

What is published falls into two groups: what you can rebuild here, for free
and with no key, and what you can only audit. Every claim of the form "script
X wrote table Y" is checked mechanically: the page's appendix registry, the
provenance manifests in `data/processed/`, and CI's rebuild-and-diff job all
come from the same committed files.

## Rebuild: graded rows to every number in the essay, in about seven minutes

The essay's numbers come from one frozen set of graded answers,
`data/essay/graded/responses.csv.gz`. One script rebuilds every table, every
chart's CSV, and every key number from those rows, with the same analyzers the
essay used, and diffs them against `data/essay/`:

```bash
python scripts/essay_data_step.py --check
```

It needs no key and no network. Fifteen tables, the 25 figure CSVs, and the
key numbers are rebuilt; fourteen tables derived from inputs that are not
graded rows (the training experiments, the gate design profiles, and the model
catalog) are compared, and `data/essay/README.md` lists them. CI runs the same
check on every push.

The rest takes about 30 minutes:

```bash
pip install -e ".[dev]"
pytest                                # the test suite, no network
python scripts/properness.py          # the scoring rule does what it claims
python scripts/power.py               # the sample-size arithmetic
python scripts/census.py              # the 1,089,024-response census (about 20 minutes)
python scripts/census_exclusions.py   # both census figures: all 36 benchmarks, and the 22 the essay compares
python scripts/build_site.py          # rebuild the pages; git diff shows nothing
python scripts/build_essay_page.py    # rebuild essay.html, the v2.7 revision of August 2026 (superseded by the published essay)
```

The census streams the public `evaleval/EEE_datastore` from Hugging Face; no
model is queried.

## Audit only

Two kinds of published numbers cannot be regenerated from this repository,
because the code that produced their inputs is not included:

- The model calls themselves. The graded rows record what each model answered,
  how it was graded, and what the call cost; rerunning the calls needs the
  runner, which is available on request.
- The training experiments. Their CSVs in `data/processed/` and the frozen
  summaries in `data/essay/inputs/figure-inputs.json` derive from training and
  evaluation runs whose files are not in this repository (they may contain
  full model generations).

What you can do is (a) verify every published number against the committed
CSVs, (b) confirm each CSV's inputs by sha256 and row count in its
`*_manifest.json`, and (c) run the same analyzers over runs of your own and
compare. The manifests name the dated note in the private research notebook
that authorized each run.

## Licensing notes

- Model-output excerpts in `data/processed/census_decline_samples.csv` come
  from the openly licensed EEE datastore. They are model outputs, not
  benchmark questions.
- `census_decline_samples.csv` carries no Humanity's Last Exam excerpts: HLE's
  terms forbid redistributing the dataset, and its responses can quote it.
- Every evaluation data file (`data/essay/graded/`, `data/behaviour_items.json`)
  carries the BIG-bench canary string so training-corpus filters drop it.
- No benchmark question or answer text is redistributed anywhere in this
  repository. `data/slices/` holds opaque item IDs; the question banks are
  downloaded from their original sources under their own terms.
- `matplotlib` is needed only by `scripts/chart_prompt_only_calibration.py`;
  everything else is standard library (plus `pytest` and `ruff` for
  development).
