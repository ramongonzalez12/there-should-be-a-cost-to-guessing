import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "export_domain_replication.py"
SPEC = importlib.util.spec_from_file_location("export_domain_replication", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_summary_retains_failed_pairs_in_planned_denominator():
    contrasts = [
        {
            "training_domain": "medicine",
            "high_confidence_wrong_change": -0.2,
            "accuracy_change": 0.0,
            "confidence_calibrated_score_change": 0.1,
        }
        for _ in range(6)
    ] + [
        {
            "training_domain": "math",
            "high_confidence_wrong_change": -0.1,
            "accuracy_change": -0.01,
            "confidence_calibrated_score_change": 0.05,
        }
        for _ in range(3)
    ] + [
        {
            "training_domain": "ethics",
            "high_confidence_wrong_change": -0.3,
            "accuracy_change": 0.01,
            "confidence_calibrated_score_change": 0.2,
        }
        for _ in range(6)
    ]
    census = [
        {"training_domain": domain, "matched_pair_admitted": admitted}
        for domain, admitted in (
            ("medicine", True), ("medicine", True), ("medicine", False),
            ("math", True), ("math", False), ("math", False),
            ("ethics", True), ("ethics", True), ("ethics", False),
        )
    ]

    overall = MODULE.summarize(contrasts, census)[-1]

    assert overall["observed_contrasts"] == 15
    assert overall["planned_contrasts"] == 27
    assert overall["risk_reductions_observed"] == 15
    assert overall["risk_reductions_planned_denominator"] == 15


def test_failed_dispatch_caps_match_conservative_components():
    caps = MODULE.FAILED_DISPATCH_CAPS_USD

    assert caps["qwen_math_binary_seed2"] == pytest.approx(0.49)
    assert caps["qwen_math_quadratic_seed1"] == pytest.approx(0.49)
    assert caps["deepseek_math_base_profile"] == pytest.approx(1.30)
    qwen35_caps = sum(
        value for key, value in caps.items() if key.startswith("qwen35_")
    )
    assert qwen35_caps == pytest.approx(0.81)
