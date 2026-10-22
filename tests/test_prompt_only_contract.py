"""The prompt-only arm must isolate the scoring explanation."""

from belowzero.contracts import ANSWER_FORMAT, CONTRACTS, PROMPT_ONLY_CONTRACTS


def test_prompt_only_contract_changes_only_the_scoring_explanation():
    control = CONTRACTS["control"]
    treatment = PROMPT_ONLY_CONTRACTS["quad_score_only"]

    assert control["t"] == treatment["t"] == 0.0
    assert treatment["rule"] == "quadratic"
    assert treatment["c"] == 0.0
    assert treatment["prompt"].endswith(ANSWER_FORMAT)

    lowered = treatment["prompt"].lower()
    assert "2p - p^2" in lowered
    assert "no confidence threshold" in lowered
    assert "no fixed cost" in lowered
    assert "below 30%" not in lowered
    assert "deployment" not in lowered
    assert "flat 0.09" not in lowered


def test_control_and_prompt_only_arm_request_the_same_output_shape():
    assert CONTRACTS["control"]["prompt"].endswith(ANSWER_FORMAT)
    assert PROMPT_ONLY_CONTRACTS["quad_score_only"]["prompt"].endswith(ANSWER_FORMAT)


def test_prompt_only_contract_does_not_change_the_historical_default_matrix():
    assert "quad_score_only" not in CONTRACTS
