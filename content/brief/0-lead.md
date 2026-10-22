This brief makes one recommendation: benchmarks should ask models how likely
their answers are to be correct, then score those probabilities. If a benchmark
also wants models to decline low-confidence questions, it should provide an
explicit &ldquo;I don't know&rdquo; option.

### The findings

- key: **Models almost always answer.** They declined only {b_closed_clean} of
closed-form questions in more than one million published responses.
- key: **Current scoring rewards that behavior.** Nearly every benchmark we
reviewed gives a wrong answer and no answer the same score.
- key: **Confidence can be changed.** In the expanded prompt test, the intended
rule reduced the median absolute confidence gap by {b_prompt_gap_reduction} points
across five models from four developers. Training on the rule produced a larger
gain in one model family.
- key: **Calibration improved prudence much more than alignment behavior.**
Pooled training cut high-confidence errors by 13 to 51 points across four
subjects. Hidden unauthorized shortcuts fell by only 1 to 3 points at the
median and still occurred in 84% to 94% of conflict trials. Other alignment
indicators remained mixed.

Each section below states the point, the evidence for it, what the evidence
means, and the main limit. Technical derivations and row-level results are
available in the expandable details and appendix.
