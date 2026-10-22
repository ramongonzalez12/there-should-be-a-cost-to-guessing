## rule | 3. Score confidence, not just answers

**Recommendation.** Ask for an answer and the probability that the answer is
correct. Use a scoring rule under which honest probability reporting earns the
highest expected score.

**Why the quadratic rule.** A right answer earns more when confidence was high.
A wrong answer loses more when confidence was high. The model therefore does
best by reporting its actual belief rather than always claiming 100%.

**Separate question: should the answer reach the user?** The quadratic rule
measures confidence but still gives some expected value to any answer with a
chance of being right. Save the answer and probability, then let deterministic
code apply the deployment threshold. A 30% threshold corresponds to a quadratic
assertion cost of 0.09. The model can still receive cost-aware training, but the
final gate should remain observable and adjustable outside it.

**Limit.** The appropriate threshold is a policy choice. A film recommendation
and a drug-interaction answer should not necessarily use the same one. Our first
training experiment found no added calibration-score benefit from the fixed cost;
a direct same-checkpoint test found directionally fewer wrong answers with the
simpler confidence prompt, while a broader held-out test found better risk
ranking from cost training. The training reward, elicitation prompt, and
deployment gate are three separate choices.

:::details Why this rule elicits an honest probability
{b_fourways}

{b_worked}

{b_payoff}

The quadratic payoff is `2p &minus; p&sup2;` when right and
`&minus;p&sup2;` when wrong. A linear confidence rule does not work: it
rewards claims of 0% or 100%, not the model's actual belief.
:::

:::details How an answering cost sets the silence threshold
{b_costrow}

{b_cost}

The examples are illustrations. They are not estimates of the right cost for
those settings.
:::
