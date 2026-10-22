## ask | Recommendation for benchmark maintainers

### 1. Ask for a probability and score it

Use a score that makes an honest probability the model's best strategy. The
quadratic rule used here is one option. Report the confidence-calibrated score
beside accuracy rather than replacing accuracy.

**Basis.** Current scoring elicits guesses. Prompting and training both made
confidence track correctness better once confidence was rewarded.

### 2. Provide an explicit way to decline

Append &ldquo;I don't know&rdquo; to closed-form answer choices and score it as
zero. This makes silence an observable decision rather than an unparseable
response.

**Basis.** A wrong-answer penalty alone cannot change rankings when every item
must still be answered.

### 3. Treat any answering cost as a separate policy choice

If answers below a chosen confidence threshold should be discouraged, publish
the fixed cost and show results with and without it.

**Basis.** The threshold depends on the use case, and the fixed cost did not
improve training beyond the quadratic rule in this experiment.

:::details Supporting analyses
{b_next}
:::
