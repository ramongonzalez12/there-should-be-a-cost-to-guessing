"""reward.py — the scoring rules as RL reward functions, and as eval metrics.

One module used in three places, deliberately: the benchmark scorer, the RL
reward, and the persuasion demo all call the SAME functions. If the argument is
that scoring shapes behaviour, the code should not let the training signal and
the evaluation metric drift apart.

Drop-in compatible with TRL's GRPOTrainer, which expects
    reward_fn(prompts, completions, **kwargs) -> list[float]

Run `python reward.py` to execute the self-tests.
"""

from __future__ import annotations

import math
import re

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# One parser, imported, not copied. This module once carried its own regexes
# and they drifted from prompts.py: "I do not know" abstained under one and not
# the other, "pass" the reverse, and "0.85" was read as 0.85% here long after
# the analysis scripts had corrected it. A training reward and a benchmark
# grader that disagree about what an abstention is cannot support the claim
# that scoring shapes behaviour.
from .prompts import parse

# What the model is asked to produce. Note this asks for a PROBABILITY, not a
# "confidence" — the word matters. "Confidence" invites a vibe on a 0-100 scale;
# "probability that this exact answer is correct" is a question with a right
# answer, and it is the quantity every rule below actually needs.
RESPONSE_FORMAT = """Respond in exactly this format:
ANSWER: <your answer, or the exact string I DON'T KNOW>
PROBABILITY: <0-100, the probability that your ANSWER is correct>"""


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------
# Convention throughout: `correct` is a bool, `p` is the model's reported
# probability in [0,1], and abstention scores exactly 0.
#
# PROPERNESS is the property that decides whether any of this works. A rule is
# strictly proper if the model uniquely maximises expected score by reporting
# its true belief q. Under an improper rule the model's best play is to
# misreport, so every calibration number you then compute is measuring the
# misreport rather than the belief — you have built an instrument that destroys
# the thing it measures.

def binary(p, correct, **kw) -> float:
    """What essentially every benchmark does today. Abstention indistinguishable
    from a wrong answer, and there is no lower number than 0."""
    return 1.0 if correct else 0.0


def linear(p, correct, **kw) -> float:
    """+p if right, -p if wrong, 0 if silent. Intuitive, symmetric, [-1, 1].

    IMPROPER. EV(p) = q*p + (1-q)*(-p) = p*(2q-1), which is linear in p, so the
    optimum is always a corner: report p=1 whenever q > 0.5, else p=0. It cannot
    elicit an interior probability, because a linear payoff is a bet and the
    optimal bet under a linear payoff is all-in or nothing.

    Kept here because it is the natural first guess, it is worth showing people
    why it fails, and it IS the right rule if p is read as a stake rather than
    a belief."""
    return p if correct else -p


def quadratic(p, correct, **kw) -> float:
    """Selten's quadratic rule: +2p - p^2 if right, -p^2 if wrong.

    STRICTLY PROPER. EV(p) = 2qp - p^2, dEV/dp = 2(q - p) = 0 at p = q, and the
    second derivative is -2 < 0 so it is a maximum. Expected score at the honest
    report is exactly q^2.

    This is the linear rule with one squared term added, and that term is what
    turns a corner solution into an interior one. Range [-1, 1]; p=0 scores 0
    whatever happens, so 'report probability zero' and 'stay silent' coincide
    continuously. It is an affine transform of the Brier score, so it inherits
    Brier's decomposition into calibration + refinement."""
    return 2 * p - p * p if correct else -p * p


def quad_cost(p, correct, c: float = 0.09, **kw) -> float:
    """Quadratic, minus a fixed cost c for asserting anything at all.

    The problem quadratic alone has: expected score at the honest report is q^2,
    which is non-negative for every q, so answering with a tiny p always weakly
    beats silence. Elegant, but it gives you no lever — and in deployment a
    wrong assertion costs more than its score, because someone acts on it.

    Subtracting c from every non-abstention makes answering worthwhile only when
    q^2 > c, i.e. q > sqrt(c). Still strictly proper above the threshold (a
    constant does not change the argmax). One interpretable knob: c is the price
    of putting a claim into the world, and sqrt(c) is the abstention threshold.

    c = 0.09 -> abstain below q = 0.30
    c = 0.25 -> abstain below q = 0.50
    c = 0.56 -> abstain below q = 0.75"""
    # Abstention is handled by the caller before this function is invoked.
    # An asserted answer at p=0 is still an assertion and must pay c; otherwise
    # the model can emit any answer with zero probability and receive the same
    # reward as a genuine abstention while evaluation counts it as attempted.
    return (2 * p - p * p if correct else -p * p) - c


def log_score(p, correct, eps: float = 1e-3, **kw) -> float:
    """1 + log2(p) if right, 1 + log2(1-p) if wrong.

    STRICTLY PROPER, and the unique LOCAL proper rule — it depends only on the
    probability assigned to what actually happened. Punishes confident-and-wrong
    brutally, which is the behaviour we care most about, but is unbounded below
    without the eps clip, so one catastrophic item can dominate an average.
    Good as a diagnostic, dangerous as an RL reward."""
    p = min(max(p, eps), 1 - eps)
    return 1 + math.log2(p if correct else 1 - p)


def spherical(p, correct, **kw) -> float:
    """p/||r|| if right, (1-p)/||r|| if wrong, where ||r|| = sqrt(p^2 + (1-p)^2).

    STRICTLY PROPER, and the reason it earns a place next to quadratic and log is
    that it is *not* an affine transform of either. Quadratic is affine to Brier,
    so a model that improved its Brier score necessarily improved its quadratic
    score; the two cannot disagree, and agreement between them is therefore no
    evidence of anything. Spherical can disagree. That makes it the useful
    held-out rule for asking whether a policy trained against the quadratic
    reward learned calibration or learned the quadratic specifically.

    Score the probability the model assigned to the outcome that HAPPENED,
    normalised by the norm of the reported distribution. Both branches are
    positive; writing the wrong branch as negative is the tempting symmetry and
    it breaks properness outright.

    One consequence to keep in mind when comparing arms. The answered range is
    [1/sqrt(2), 1], so against this module's convention that abstention scores 0,
    every assertion beats silence under spherical, more starkly than under
    quadratic. That is a property of the raw rule, not a bug to normalise away,
    and it is the same gap quad_cost exists to close. It does not affect the
    trained-checkpoint comparison, where observed coverage was 100%.
    """
    norm = math.sqrt(p * p + (1 - p) * (1 - p))
    return (p if correct else (1 - p)) / norm


def threshold(p, correct, t: float = 0.75, **kw) -> float:
    """Kalai et al.: abstain unless p > t; +1 right, -t/(1-t) wrong.

    Proper as a DECISION rule — it elicits the right answer/abstain choice at
    threshold t — but it deliberately does not elicit a probability. Everything
    above t scores the same, so the reported number carries no information
    beyond which side of t it falls on. That is a feature for a benchmark
    retrofit and a limitation for a training signal."""
    if p is None or p <= t:
        return 0.0
    return 1.0 if correct else -t / (1 - t)


RULES = {"binary": binary, "linear": linear, "quadratic": quadratic,
         "quad_cost": quad_cost, "log": log_score, "spherical": spherical,
         "threshold": threshold}

# The rules the reinforcement arms were actually trained against. Anything not in
# this set is available as a held-out scorer: if an arm's advantage only shows up
# under the rule it was trained on, that is a reward-specific policy rather than
# the calibration improvement it is being reported as.
TRAINED_RULES = frozenset({"binary", "quadratic", "quad_cost"})
HELD_OUT_PROPER_RULES = ("log", "spherical")


# ---------------------------------------------------------------------------
# RL reward wrapper
# ---------------------------------------------------------------------------

def make_reward_fn(rule: str = "quad_cost", grade=None, missing_prob: float = 0.5,
                   parse_failure: float = -1.0, **rule_kwargs):
    """Build a TRL-compatible reward function.

    Args:
      rule:          key into RULES
      grade:         callable(completion_answer, reference) -> bool. For short
                     factual QA, normalised string match is enough; for anything
                     open-ended you need a judge, and its errors become training
                     signal, so validate it first.
      missing_prob:  probability assumed when the model omits the field. 0.5 is
                     the least-informative choice; do NOT use 1.0, which would
                     reward omitting the number whenever the model is confident.
      parse_failure: reward for output that cannot be parsed at all. MUST be
                     negative and at least as bad as a confident wrong answer.
                     If unparseable scores 0 it is treated as an abstention, and
                     the model learns that silence-by-incoherence is free — the
                     single most likely way this whole scheme gets gamed. On
                     published GPQA runs, that mistake lets an 18.7%-accuracy 1B
                     model outscore a 51.5%-accuracy 70B model.
    """
    # A reward with no grader scores every asserted answer wrong, so the policy
    # learns that silence is the only non-negative move. That is a plausible-
    # looking training run optimising for "always abstain". Refuse it.
    if grade is None:
        raise ValueError("make_reward_fn needs a grader; a reward that cannot "
                         "tell right from wrong trains the model to abstain")
    fn = RULES[rule]
    # The parse-failure reward must be at least as bad as the worst asserted
    # outcome under THIS rule. With quad_cost(c=0.09) a confident wrong answer
    # scores -1.09, so a flat -1.0 would make garbage strictly better than
    # answering wrong at p >= 0.955, and an RL policy searches for exactly
    # that band. Derive the floor from the rule instead of trusting a constant.
    worst_assertion = min(fn(1.0, False, **rule_kwargs), fn(0.0, False, **rule_kwargs))
    parse_failure = min(parse_failure, worst_assertion)

    def reward_fn(prompts=None, completions=None, reference=None, **kwargs):
        refs = reference if reference is not None else kwargs.get("answer")
        out = []
        for i, completion in enumerate(completions or []):
            text = completion if isinstance(completion, str) else \
                completion[-1].get("content", "")
            answer, p, abstained, formatted = parse(text)
            if not answer or not formatted:
                out.append(parse_failure)
                continue
            if abstained:
                out.append(0.0)
                continue
            if p is None:
                p = missing_prob
            ref = refs[i] if refs is not None else None
            correct = bool(grade(answer, ref)) if grade else False
            out.append(float(fn(p, correct, **rule_kwargs)))
        return out

    return reward_fn


def normalised_match(answer: str, reference: str) -> bool:
    """Cheap grader for short factual answers: case/punctuation-insensitive
    containment. Adequate for SimpleQA-style items with a single short target,
    inadequate for anything else — check agreement against hand labels before
    training on it, because grader error becomes the thing the model learns."""
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()
    a, r = norm(answer), norm(reference)
    return bool(r) and r in a


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

def _test():
    GRID = [i / 400 for i in range(401)]

    def argmax_report(fn, q, **kw):
        ev = lambda p: q * fn(p, True, **kw) + (1 - q) * fn(p, False, **kw)
        return max(GRID, key=lambda p: (round(ev(p), 12), -abs(p - q)))

    print("properness check — max |p* - q| over q in (0,1)")
    expected = {"binary": False, "linear": False, "quadratic": True,
                "quad_cost": True, "log": True, "spherical": True,
                "threshold": True}
    for name, fn in RULES.items():
        if name == "threshold":
            # proper as a decision rule, not a probability rule; check the
            # decision instead: answer iff q > t.
            bad = [q for q in GRID if (fn(q, True, t=0.75) != 0) != (q > 0.75)]
            print(f"  {name:10s} decision correct at every q: {not bad}")
            assert not bad
            continue
        if name == "quad_cost":
            # only meaningful above the assertion threshold sqrt(c)
            worst = max(abs(argmax_report(fn, q) - q) for q in GRID if q > 0.31)
        elif name == "binary":
            worst = float("nan")
            print(f"  {name:10s} not a probability rule (ignores p)")
            continue
        else:
            worst = max(abs(argmax_report(fn, q) - q) for q in GRID[1:-1])
        proper = worst < 0.01
        print(f"  {name:10s} {worst:.4f}  {'PROPER' if proper else 'IMPROPER'}")
        assert proper == expected[name], f"{name} propriety changed!"

    print("\nabstention thresholds for quad_cost")
    for c in (0.09, 0.25, 0.5625):
        thr = next(q for q in GRID
                   if max(q * quad_cost(p, True, c=c) + (1 - q) * quad_cost(p, False, c=c)
                          for p in GRID) > 0)
        print(f"  c={c:.4f}  predicted sqrt(c)={math.sqrt(c):.3f}  observed={thr:.3f}")
        assert abs(thr - math.sqrt(c)) < 0.02

    print("\nparsing")
    cases = [
        ("ANSWER: Paris\nPROBABILITY: 90", ("Paris", 0.90, False, True)),
        ("ANSWER: I DON'T KNOW\nPROBABILITY: 5", ("I DON'T KNOW", 0.05, True, True)),
        ("ANSWER: a multi-line\nanswer here\nPROBABILITY: 40",
         ("a multi-line\nanswer here", 0.40, False, True)),
        ("ANSWER: Paris", ("Paris", None, False, True)),
        ("", ("", None, False, False)),
        ("Paris, probably.", ("Paris, probably.", None, False, False)),
    ]
    for text, want in cases:
        got = parse(text)
        assert got == want, f"parse({text!r}) -> {got!r}, wanted {want!r}"
        print(f"  ok  {text.splitlines()[0] if text else '<empty>':32s} -> {got}")

    print("\nreward function end-to-end")
    fn = make_reward_fn("quad_cost", grade=normalised_match, c=0.09)
    comps = ["ANSWER: Paris\nPROBABILITY: 90",
             "ANSWER: Lyon\nPROBABILITY: 90",
             "ANSWER: I DON'T KNOW\nPROBABILITY: 10",
             "!!!"]
    refs = ["Paris", "Paris", "Paris", "Paris"]
    got = fn(completions=comps, reference=refs)
    want = [round(2 * .9 - .81 - .09, 4), round(-.81 - .09, 4), 0.0, -1.0]
    assert [round(g, 4) for g in got] == want, (got, want)
    for c, g in zip(comps, got):
        print(f"  {c.splitlines()[0]:34s} -> {g:+.3f}")
    print("\nall tests pass")


if __name__ == "__main__":
    _test()
