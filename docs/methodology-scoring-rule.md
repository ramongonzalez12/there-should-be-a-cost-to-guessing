# The scoring rule: why the linear version fails, and the one-term fix

> **A design note from early in the project.** It was written while the rule
> was being worked out, as a reply to a first proposal (a linear rule, number 4
> in that proposal's list), and it keeps that second-person voice as a record
> of the reasoning. The argument for readers is
> `site/below-zero/why-linear-fails.html` and the overview's scoring section
> (`site/below-zero/index.html#rule`); the canonical definitions are in the
> site's glossary. Where this note and the site differ, the site is current.

The proposed rule (4): each answer carries a probability p. Correct → **+p**. Wrong → **−p**. No answer → **0**. Range [−1, +1].

The instinct is right and the shape is right. **But as written it can't elicit an honest probability, and that matters because eliciting one is the entire point.**

---

## Why it degenerates

If the model truly believes its answer is correct with probability q, and reports p:

$$\mathbb{E}[\text{score}] = q \cdot p + (1-q)(-p) = p\,(2q - 1)$$

That's **linear in p**. A linear objective on a bounded interval has its optimum at a corner. So the model's best play is:

- q > 0.5 → report **p = 1**
- q < 0.5 → report **p = 0**, or abstain

It never reports anything in between. Verified numerically in `rules.py`:

```
 true q  linear (yours)       quadratic             log
   0.05            0.00            0.05            0.05
   0.35            0.00            0.35            0.35
   0.55            1.00            0.55            0.55
   0.95            1.00            0.95            0.95
```

Max |p* − q| under your rule: **0.4975**. Under quadratic and log: **0.0000**.

You'd have built an elaborate probability-elicitation apparatus that collapses to a yes/no decision at threshold 0.5 — i.e. Kalai's rule at t = 0.5, with extra steps and a misleading number attached. And then every calibration statistic you computed downstream would be measuring the misreport rather than the belief. **An improper rule destroys the quantity it's trying to measure.**

The finance framing, since it's the intuition that makes this stick: a linear payoff in p is a **bet**, and p is a stake, not a belief. The optimal stake under a linear payoff is all-in or nothing — that's why Kelly betting needs a *concave* utility to produce an interior fraction. Same mathematics, same reason.

---

## The fix is one squared term

**Selten's quadratic rule.** Correct → **2p − p²**. Wrong → **−p²**. No answer → **0**.

$$\mathbb{E}[\text{score}] = q(2p - p^2) + (1-q)(-p^2) = 2qp - p^2, \qquad \frac{d}{dp} = 2(q-p) = 0 \;\Rightarrow\; p = q$$

Second derivative −2 < 0, so it's a maximum, and it's unique. **Strictly proper.** Expected score at the honest report is exactly q².

It keeps everything you wanted:

| your requirement | quadratic rule |
|---|---|
| range −1 to +1 | ✓ p=1 correct → +1; p=1 wrong → −1 |
| no answer = 0 | ✓ and p=0 scores 0 either way, so "probability zero" and "silence" coincide *continuously* |
| probability-weighted, signed | ✓ |
| honest reporting is optimal | ✓ — this is the part your version doesn't have |

It's also an affine transform of the Brier score, so it inherits Brier's decomposition into **calibration + refinement** — meaning you can tell people exactly how much of a model's score comes from being well-calibrated versus from actually knowing things. That decomposition is a persuasion asset in itself.

The whole difference is the −p² term. That's the sentence to lead with: *"your rule and the correct rule differ by one squared term, and that term is the entire difference between eliciting a belief and eliciting a bet."*

---

## The refinement that makes it deployable

Pure quadratic has one gap: expected score at the honest report is q², which is **≥ 0 for every q**. So answering with a tiny p always weakly beats silence. Elegant — abstention becomes the p→0 limit rather than a special case — but it gives you no lever, and in deployment a wrong assertion costs more than its score, because someone acts on it.

**Quadratic minus an assertion cost c.** Subtract a fixed c from any non-abstention. Answering is now worth it only when q² > c:

$$\text{answer iff } q > \sqrt{c}$$

Still strictly proper above the threshold — a constant doesn't move the argmax. Verified:

```
c=0.0900  predicted sqrt(c)=0.300  observed=0.302
c=0.2500  predicted sqrt(c)=0.500  observed=0.502
c=0.5625  predicted sqrt(c)=0.750  observed=0.752
```

**One interpretable knob.** c is the price of putting a claim into the world; √c is the abstention threshold. A medical triage deployment sets c high; a brainstorming assistant sets it near zero. That single parameter is the thing your "always many goals" argument says should be *visible and contestable* rather than baked silently into the metric — and under binary grading it is silently set to zero, forever, for everyone.

---

## The full ladder, and when to use each

| rule | correct | wrong | proper? | use it for |
|---|---|---|---|---|
| **binary** | +1 | 0 | n/a | what every benchmark does now. The thing you're arguing against |
| **linear** (yours) | +p | −p | ✗ | nothing — but show it, because it's the natural first guess and the failure is instructive |
| **threshold** (Kalai) | +1 | −t/(1−t) | ✓ as a *decision* | retrofitting existing benchmarks. Elicits the answer/abstain choice, not a probability |
| **quadratic** (Selten) | 2p − p² | −p² | ✓ | the default. Honest probabilities, bounded, abstention continuous |
| **quadratic + cost c** | 2p − p² − c | −p² − c | ✓ | deployment and RL. Adds a tunable, interpretable abstention threshold √c |
| **log** | 1 + log₂p | 1 + log₂(1−p) | ✓ | diagnostics only. The unique *local* proper rule, brutal on confident-and-wrong, but unbounded below — one catastrophic item dominates an average, which makes it dangerous as an RL reward |

Kalai's threshold rule and the quadratic rule are answering different questions, and it's worth being explicit about which you're arguing for:

- **Threshold** asks *"should you answer?"* It's the right tool for retrofitting SWE-bench and GPQA, because it needs no new output channel — just an instruction and a grading change.
- **Quadratic** asks *"how sure are you?"* It's the right tool for training and for anything downstream that consumes the number.

Your idea (4) is reaching for the second. It's the more ambitious and more useful one, and it's the one the published proposal doesn't make.

---

## The one non-negotiable implementation detail

**Unparseable output must score strictly worse than an abstention.**

If output that ignores the format scores 0, it's treated as honesty, and the model learns that silence-by-incoherence is free. This is not hypothetical: on published GPQA runs, scoring parse failures as abstentions lets an 18.7%-accuracy 1B model outscore a 51.5%-accuracy 70B model at t = 0.9, purely by emitting garbage.

In `reward.py` this is `parse_failure = −1.0`, and `parse()` returns a separate `followed_format` flag precisely so the two can never be conflated. A model that never emitted an ANSWER field did not abstain — it ignored the contract.

---

## Files

- `rules.py` — every rule, plus a numerical properness check and the abstention-threshold verification. `python rules.py`
- `reward.py` — the same rules as TRL-compatible RL reward functions, with parsing and self-tests. `python reward.py`

Deliberately one module for both: if the argument is that scoring shapes behaviour, the training signal and the evaluation metric must not be allowed to drift apart in the codebase making the argument.
