# The million-response abstention sweep

Every per-sample file in the EvalEval "Every Eval Ever" datastore, streamed and
scanned. No inference, no API key, no cost.

**1,088,601 graded responses · 104 models · 36 benchmarks.**

These counts are from the first pull of the datastore, on August 15, 2026. The
census of record is a re-pull on September 3, 2026 (1,320 of 1,320 files, zero
read failures): 1,089,024 responses, 0.69% with a decline phrase and 0.25% with
a stated probability (`data/processed/census_summary.csv`). The README, the
published essay, and the current site pages quote the re-pull; the figures
below, and the superseded drafts kept for comparison, are the first pull's.

Method: for each response, search the *entire* generation — including reasoning
traces, not just the final answer — for any of ~18 decline phrases ("I don't
know", "cannot determine", "insufficient information", "no way to know",
"unanswerable", "I'm not sure", …). Deliberately over-broad: the aim was to try
as hard as possible to *find* abstention. Game-playing arenas (wordle, fibble)
were excluded as having no notion of an answer to decline. `scripts/census.py`
reproduces it in about 20 minutes.

---

## The headline

| | count | share |
|---|---:|---:|
| responses scanned | 1,088,601 | |
| contain **any** decline phrase, anywhere | 7,434 | **0.68%** |
| state a numeric confidence | 2,766 | **0.25%** |
| empty generation | 1,215 | 0.11% |

Two thirds of one percent. And that is the *generous* count — a phrase appearing
anywhere in a 4,000-token reasoning trace counts as a hit.

The 0.25% confidence figure is worth pausing on separately: **essentially the
only place in a million responses where a model states how sure it is, is HLE
(43.8%), because HLE's prompt explicitly asks for it.** Everywhere else the
information exists inside the model and is never emitted, because nothing asks.

---

## By benchmark

| benchmark | n | accuracy | decline % | states confidence % |
|---|---:|---:|---:|---:|
| math-mc | 353,808 | 0.886 | 0.52% | 0.0% |
| MMLU-Pro | 168,432 | 0.725 | **0.02%** | 0.0% |
| hellaswag | 140,588 | 0.886 | **0.00%** | 0.0% |
| reward-bench-2 | 95,148 | 0.738 | 1.43% | 0.0% |
| gsm-mc | 93,649 | 0.939 | 0.31% | 0.0% |
| judgebench | 18,900 | 0.756 | 3.67% | 0.0% |
| piqa | 18,380 | 0.918 | 0.01% | 0.0% |
| healthbench | 15,299 | — | 5.33% | 0.0% |
| gpqa-diamond | 13,662 | 0.654 | 2.59% | 0.0% |
| commonsense_qa | 13,431 | 0.838 | **0.00%** | 0.0% |
| gsm8k | 14,509 | 0.939 | **0.00%** | 0.0% |
| big_bench_hard | 3,750 | 0.820 | **0.00%** | 0.0% |
| swebenchpro | 7,580 | 0.667 | 11.29% | 0.0% |
| hle | 6,306 | 0.423 | 3.52% | **43.8%** |
| terminalbench | 6,262 | 0.660 | 3.03% | 0.1% |
| GAIA | 286 | 0.045 | 6.29% | 0.0% |
| cybench | 360 | 0.092 | 3.89% | 0.0% |

**Zero declines in 140,588 hellaswag responses. Zero in 13,431 commonsense_qa.
Zero in 14,509 gsm8k. Two hundredths of a percent across 168,432 MMLU-Pro
responses.**

The pattern in the exceptions is the informative part. Decline language is
concentrated in the *agentic* benchmarks — swebenchpro 11.3%, GAIA 6.3%,
terminalbench 3.0%, cybench 3.9% — where the model has to report on work it
actually attempted and can observe itself failing. On closed-form question
answering it is essentially absent. **Models decline when the environment shows
them they failed, not when their own uncertainty should tell them to.**

Note also cybench at 9.2% accuracy with a 3.9% decline rate, and GAIA at 4.5%
accuracy with 6.3%. Being wrong 95% of the time produces almost no admission of
not knowing.

---

## The sharper finding: they say it, then answer anyway

On GPQA Diamond (13,662 responses, 69 model runs), separating responses that
contain an explicit statement of not knowing by what the model then did:

| | count |
|---|---:|
| stated it could not determine something **and still committed to an answer** | **184** |
| stated it could not determine something and produced no answer | **4** |

**97.9% of the time a model says it cannot determine the answer, it answers
anyway.**

Verbatim, google/gemma-2-27b-it, which the harness scored as having answered C:

> *"**Important Note:** Without performing the numerical calculations, it's
> impossible to determine the exact percentage. Answer: I cannot answer without
> performing the calculations."*

And CohereLabs/c4ai-command-r7b, scored as answering D:

> *"...without the specific details of the final structure, we cannot determine
> the exact number of chemically distinct hydrogen atoms. ### Step 7: Analyze
> the Options ... We can infer..."*

**Honest caveat.** The gemma case is partly an *extraction* artifact — the model
did decline, and the multiple-choice parser pulled a letter out of the option
list anyway. That cuts both ways and both ways are damaging: either the model
hedges and commits, or the harness converts a refusal into a guess before
anything is scored. The second is arguably worse, because the model behaved
correctly and the instrument overwrote it.

This is the tightest available statement of the thesis. It is not that models
lack the internal signal — the uncertainty is right there in the text. It is that
nothing in the pipeline, from the prompt to the parser to the metric, has any
place to put it.

---

## What this does and does not license

**Does:** the claim that current evaluation never sees abstention is not an
impression, it is 1.09 million observations. Any writeup can state it with a
number and a reproduction script.

**Does not:** attribute it solely to benchmark scoring. Three causes are
entangled and this sweep cannot separate them — accuracy-only grading, post-
training that degrades calibration ("the post-training hurts calibration
significantly", GPT-4 tech report), and reasoning fine-tuning that degrades
abstention ~24% independent of any benchmark (AbstentionBench). Separating them
is what the `arena` experiment is for: `control` vs `guess` holds the model
fixed and varies only whether the rule is spoken.

**Also does not:** claim the `unextracted` column measures refusal. For most
benchmarks it reads 100% simply because that schema version does not populate
`answer_attribution`. Only `gpqa-diamond`, `math-mc`, `gsm-mc`, `judgebench`,
`reward-bench-2` and `lingoly` have real extraction data; the GPQA figure (3.3%)
is genuine and, as documented in `../rescore/README.md`, is parse failure rather
than honesty.

---

## Reproduce

```bash
python scripts/census.py        # ~20 min, streams and discards, writes the CSVs below
```
