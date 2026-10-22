"""Properness is the property the whole project rests on: under an improper
rule the model's best play is to misreport, so every calibration number
computed downstream measures the misreport rather than the belief. These tests
fail loudly if a rule's propriety ever changes."""
import math

import pytest

from belowzero.rules import (
    HELD_OUT_PROPER_RULES,
    RULES,
    TRAINED_RULES,
    linear,
    log_score,
    quad_cost,
    quadratic,
    spherical,
    threshold,
)

GRID = [i / 400 for i in range(401)]


def argmax_report(fn, q, **kw):
    ev = lambda p: q * fn(p, True, **kw) + (1 - q) * fn(p, False, **kw)
    return max(GRID, key=lambda p: (round(ev(p), 12), -abs(p - q)))


@pytest.mark.parametrize("fn", [quadratic, log_score, spherical])
def test_strictly_proper(fn):
    worst = max(abs(argmax_report(fn, q) - q) for q in GRID[1:-1])
    assert worst < 0.01, f"{fn.__name__} is no longer proper (worst {worst:.3f})"


def test_spherical_is_not_an_affine_transform_of_quadratic():
    """The property that makes spherical a *useful* held-out rule.

    Quadratic is affine to Brier, so a Brier improvement is a quadratic
    improvement by construction and the two can never disagree. If spherical were
    also affine to quadratic, rescoring under it would be arithmetic dressed up as
    a robustness check: the arm ranking could not possibly change. This test
    fails if someone 'simplifies' spherical into something that collapses back
    onto quadratic.

    Fit the best affine map a*quadratic + b over a grid of (p, outcome) cells by
    least squares and assert the residual is large.
    """
    cells = [(p / 50, outcome) for p in range(51) for outcome in (True, False)]
    xs = [quadratic(p, outcome) for p, outcome in cells]
    ys = [spherical(p, outcome) for p, outcome in cells]
    n = len(cells)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = sum((x - mean_x) ** 2 for x in xs)
    slope = covariance / variance
    intercept = mean_y - slope * mean_x
    worst = max(abs(y - (slope * x + intercept)) for x, y in zip(xs, ys))
    assert worst > 0.05, (
        "spherical collapsed onto an affine image of quadratic "
        f"(worst residual {worst:.4f}); it is no longer an independent rule"
    )


def test_held_out_rules_were_not_trained_against():
    """A held-out scorer stops being held out the moment an arm trains on it."""
    assert TRAINED_RULES.isdisjoint(HELD_OUT_PROPER_RULES)
    for name in (*TRAINED_RULES, *HELD_OUT_PROPER_RULES):
        assert name in RULES, f"{name} is named as a rule but missing from RULES"


def test_linear_is_improper_and_that_is_the_point():
    # EV(p) = p*(2q-1) is linear in p, so the optimum is always a corner.
    assert argmax_report(linear, 0.60) == 1.0
    assert argmax_report(linear, 0.40) == 0.0
    assert max(abs(argmax_report(linear, q) - q) for q in GRID[1:-1]) > 0.4


@pytest.mark.parametrize("k", [1, 2, 3, 9])
def test_asymmetric_linear_still_degenerates(k):
    """The natural fix -- make the wrong-answer penalty bigger -- only moves the
    break-even to q = k/(1+k). It never creates an interior optimum."""
    fn = lambda p, ok, k=k: p if ok else -k * p
    breakeven = k / (1 + k)
    for q in (0.2, 0.5, 0.7, 0.9):
        if abs(q - breakeven) < 1e-9:
            continue                    # knife-edge: see the next test
        assert argmax_report(fn, q) in (0.0, 1.0), (k, q)


@pytest.mark.parametrize("k", [1, 2, 3, 9])
def test_asymmetric_linear_is_totally_uninformative_at_breakeven(k):
    """Exactly at q = k/(1+k) the expected score is 0 for EVERY report, so the
    model is indifferent across the whole interval. A rule that pays the same
    for p = 0.01 and p = 0.99 is not eliciting anything -- which is the linear
    family's failure in its purest form."""
    fn = lambda p, ok, k=k: p if ok else -k * p
    q = k / (1 + k)
    evs = [q * fn(p, True) + (1 - q) * fn(p, False) for p in GRID]
    assert max(evs) - min(evs) < 1e-9


def test_quad_cost_proper_above_threshold():
    worst = max(abs(argmax_report(quad_cost, q) - q) for q in GRID if q > 0.31)
    assert worst < 0.01


def test_quad_cost_charges_zero_probability_assertions():
    """p=0 is not an abstention when the model still emitted an answer."""
    assert quad_cost(0.0, True, c=0.09) == pytest.approx(-0.09)
    assert quad_cost(0.0, False, c=0.09) == pytest.approx(-0.09)


@pytest.mark.parametrize("c", [0.09, 0.25, 0.5625])
def test_abstention_threshold_is_sqrt_c(c):
    thr = next(q for q in GRID
               if max(q * quad_cost(p, True, c=c) + (1 - q) * quad_cost(p, False, c=c)
                      for p in GRID) > 0)
    assert abs(thr - math.sqrt(c)) < 0.02


def test_threshold_rule_makes_the_right_decision():
    assert all((threshold(q, True, t=0.75) != 0) == (q > 0.75) for q in GRID)
