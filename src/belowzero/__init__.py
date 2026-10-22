"""below-zero — scoring rules that can go below zero, and the experiment that
tests whether telling a model the rule changes what it does.

Public surface:
    rules       the scoring rules (binary, linear, quadratic, quad+cost, log,
                threshold) with properness documented and tested
    contracts   the announced scoring contracts (the experimental treatments)
    prompts     the prompts and the response parser
    store       SQLite persistence; raw responses preserved verbatim
"""

__version__ = "0.1.0"

from . import checkers, contracts, datasets, prompts, rules, store  # noqa: F401
