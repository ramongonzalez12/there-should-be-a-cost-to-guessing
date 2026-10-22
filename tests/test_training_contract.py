"""The RL reward is exercised over states a real rollout can actually reach."""

import pytest

from belowzero.rules import RULES
from belowzero.training_contract import (
    calibrate_reward_scales,
    clean_abstention,
    exercise_reward_contract,
    idk_letter,
    make_mc_reward_fn,
    parse_mc_response,
    rescore_stored_outcome,
    rollout_health,
    score_clean_idk_parsed,
    score_clean_parsed,
    score_mc_response,
)


def test_reward_scale_calibration_matches_centered_rms_with_one_fixed_multiplier():
    items = [{"item_id": "one"}, {"item_id": "two"}]
    records = [
        {
            "_profile_input": "seed-0",
            "step": 0,
            "item_id": "one",
            "outcome": "CORRECT",
            "probability": 0.8,
        },
        {
            "_profile_input": "seed-0",
            "step": 0,
            "item_id": "one",
            "outcome": "INCORRECT",
            "probability": 0.8,
        },
        {
            "_profile_input": "seed-0",
            "step": 1,
            "item_id": "two",
            "outcome": "CORRECT",
            "probability": 0.6,
        },
        {
            "_profile_input": "seed-0",
            "step": 1,
            "item_id": "two",
            "outcome": "ABSTAINED",
            "probability": 0.1,
        },
    ]

    calibration = calibrate_reward_scales(items, records, min_rollouts=2)

    assert calibration["method"] == "fixed_arm_scale_to_reference_centered_rms"
    assert calibration["arms"]["binary"]["scale"] == pytest.approx(1.0)
    for arm in calibration["arms"].values():
        assert arm["scale"] > 0
        assert arm["scaled_centered_rms"] == pytest.approx(calibration["target_centered_rms"])


def test_reward_profile_detects_when_centering_erases_treatment_contrasts():
    items = [{"item_id": "same-p"}, {"item_id": "varied-p"}, {"item_id": "idk"}]
    records = [
        # With a common probability and no abstention, quadratic is a rescaled
        # binary advantage and the fixed assertion cost cancels under centering.
        {"step": 0, "item_id": "same-p", "outcome": "CORRECT", "probability": 0.6},
        {"step": 0, "item_id": "same-p", "outcome": "INCORRECT", "probability": 0.6},
        {"step": 0, "item_id": "same-p", "outcome": "INCORRECT", "probability": 0.6},
        # Probability variation separates binary from quadratic, but the cost
        # still cancels because every completion asserts an answer.
        {"step": 1, "item_id": "varied-p", "outcome": "CORRECT", "probability": 0.8},
        {"step": 1, "item_id": "varied-p", "outcome": "INCORRECT", "probability": 0.7},
        {"step": 1, "item_id": "varied-p", "outcome": "INCORRECT", "probability": 0.3},
        # An abstention makes the fixed assertion cost vary within the group, so
        # the quadratic and cost-aware advantage directions finally separate.
        {"step": 2, "item_id": "idk", "outcome": "CORRECT", "probability": 0.6},
        {"step": 2, "item_id": "idk", "outcome": "INCORRECT", "probability": 0.6},
        {"step": 2, "item_id": "idk", "outcome": "ABSTAINED", "probability": 0.1},
    ]

    contrast = calibrate_reward_scales(items, records, min_rollouts=3)[
        "treatment_contrast"
    ]

    assert contrast["support"]["groups_with_assertion_and_abstention"] == 1
    assert contrast["support"]["groups_with_varied_assertion_probability"] == 1
    binary_quadratic = contrast["pairwise"]["binary_vs_quadratic"]
    quadratic_cost = contrast["pairwise"]["quadratic_vs_quad_cost"]
    assert binary_quadratic["directionally_distinct_groups"] == 2
    assert quadratic_cost["directionally_distinct_groups"] == 1
    assert quadratic_cost["directionally_distinct_rate"] == pytest.approx(1 / 3)
    assert quadratic_cost["scaled_rms_difference"] > 0


def test_reward_scale_calibration_requires_probability_for_attempted_outcome():
    items = [{"item_id": "one"}]
    records = [
        {"step": 0, "item_id": "one", "outcome": "CORRECT"},
        {"step": 0, "item_id": "one", "outcome": "INCORRECT", "probability": 0.5},
    ]

    with pytest.raises(ValueError, match="missing probability"):
        calibrate_reward_scales(items, records, min_rollouts=2)


def test_strict_parser_accepts_only_the_two_line_contract():
    parsed = parse_mc_response("ANSWER: B\nPROBABILITY: 73\n", n_choices=4)
    assert parsed.formatted
    assert parsed.answer == "B"
    assert parsed.probability == 0.73
    assert not parsed.abstained

    markdown_break = parse_mc_response("ANSWER: B  \nPROBABILITY: 73", n_choices=4)
    assert markdown_break.formatted
    assert markdown_break.format_variant == "trailing_whitespace"

    for malformed in (
        "B",
        "ANSWER: B",
        "answer: B\nPROBABILITY: 73",
        "ANSWER: B\nPROBABILITY: 73.0",
        "Reasoning\nANSWER: B\nPROBABILITY: 73",
        "ANSWER: B\nPROBABILITY: 101",
        "ANSWER:  B\nPROBABILITY: 73",
    ):
        assert not parse_mc_response(malformed, n_choices=4).formatted


def test_appended_letter_is_the_only_abstention():
    assert idk_letter(4) == "E"
    abstained = score_mc_response("ANSWER: E\nPROBABILITY: 12", "A", 4, "quad_cost")
    assert abstained.outcome == "ABSTAINED"
    assert abstained.reward == 0.0


def test_asserting_at_zero_probability_still_pays_assertion_cost():
    wrong = score_mc_response(
        "ANSWER: B\nPROBABILITY: 0", "A", 4, "quad_cost", assertion_cost=0.09
    )
    right = score_mc_response(
        "ANSWER: A\nPROBABILITY: 0", "A", 4, "quad_cost", assertion_cost=0.09
    )
    assert wrong.reward == pytest.approx(-0.09)
    assert right.reward == pytest.approx(-0.09)


def test_missing_probability_is_failure_not_imputed_confidence():
    result = score_mc_response("ANSWER: A", "A", 4, "quadratic")
    assert result.outcome == "INVALID"
    assert result.reward == -1.0


def test_exhaustive_contract_covers_every_probability_and_failure_state():
    counts = exercise_reward_contract()
    # 101 probabilities x (correct, incorrect, abstained), plus seven malformed.
    assert counts == {"binary": 310, "quadratic": 310, "quad_cost": 310}


def test_trl_wrapper_rejects_misaligned_batch_metadata():
    reward = make_mc_reward_fn("binary")
    with pytest.raises(ValueError, match="equal lengths"):
        reward(
            completions=["ANSWER: A\nPROBABILITY: 50"],
            reference=["A"],
            n_choices=[],
        )


def test_rollout_health_fails_closed_on_empty_invalid_and_abstention_collapse():
    assert rollout_health([])["status"] == "RED"

    invalid = [{"outcome": "INVALID"}] + [{"outcome": "CORRECT"}] * 9
    report = rollout_health(invalid, max_invalid_rate=0.05)
    assert report["status"] == "RED"
    assert "invalid_rate" in report["reasons"]

    collapsed = [{"outcome": "ABSTAINED"}] * 100
    report = rollout_health(collapsed)
    assert report["status"] == "RED"
    assert "abstention_collapse" in report["reasons"]

    # Near-perfect correctness is success, not a collapse condition.
    assert rollout_health([{"outcome": "CORRECT"}] * 100)["status"] == "GREEN"

    healthy = (
        [{"outcome": "CORRECT"}] * 60
        + [{"outcome": "INCORRECT"}] * 30
        + [{"outcome": "ABSTAINED"}] * 10
    )
    assert rollout_health(healthy)["status"] == "GREEN"


def test_rollout_health_detects_byte_identical_multi_sample_groups():
    collapsed = [
        {
            "step": step,
            "item_id": f"item-{step}",
            "raw": "ANSWER: A\nPROBABILITY: 90",
            "outcome": "CORRECT",
        }
        for step in range(4)
        for _rollout in range(8)
    ]
    report = rollout_health(collapsed)

    assert report["status"] == "RED"
    assert "exact_duplicate_group_collapse" in report["reasons"]
    assert report["group_diversity"]["exact_duplicate_group_rate"] == 1.0

    diverse = [dict(row) for row in collapsed]
    for index, row in enumerate(diverse):
        row["raw"] = f"ANSWER: A\nPROBABILITY: {70 + index % 8}"
    assert rollout_health(diverse)["status"] == "GREEN"


def test_reward_wrapper_persists_raw_audit_and_stops_failed_health(tmp_path):
    path = tmp_path / "rollouts.jsonl"
    reward = make_mc_reward_fn(
        "quad_cost", audit_path=path, min_health_records=2, max_invalid_rate=0.25
    )
    with pytest.raises(RuntimeError, match="health gate"):
        reward(
            completions=["bad", "still bad"],
            reference=["A", "A"],
            n_choices=[4, 4],
            item_id=["one", "two"],
        )
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    assert reward.health_report["status"] == "RED"


# --- clean-final-answer-v1 -------------------------------------------------


def clean_parsed(*, answer=True, confidence=0.7, correct=True):
    return {
        "answer": "B" if answer else None,
        "answer_valid": answer,
        "correct": correct if answer else False,
        "confidence": confidence,
        "confidence_valid": confidence is not None,
        "needs_math_judge": False,
    }


@pytest.mark.parametrize("rule", ["binary", "quadratic"])
def test_clean_contract_requires_both_lines_in_both_arms(rule):
    # The binary arm ignores the confidence VALUE but still needs the line;
    # otherwise the two arms would differ in format as well as reward.
    for answer, confidence, failure in (
        (False, 0.7, "answer"),
        (True, None, "confidence"),
        (False, None, "answer_and_confidence"),
    ):
        scored = score_clean_parsed(clean_parsed(answer=answer, confidence=confidence), rule)
        assert scored.outcome == "INVALID"
        assert scored.reward == -1.0
        assert scored.formatted is False and scored.abstained is False
        assert scored.failure == failure


@pytest.mark.parametrize("rule", ["binary", "quadratic"])
def test_clean_contract_rewards_follow_the_rules_and_never_abstain(rule):
    for percent in range(101):
        p = percent / 100
        for correct in (True, False):
            scored = score_clean_parsed(clean_parsed(confidence=p, correct=correct), rule)
            assert scored.outcome == ("CORRECT" if correct else "INCORRECT")
            assert scored.abstained is False and scored.formatted is True
            assert scored.reward == pytest.approx(RULES[rule](p, correct))
            # The stored outcome rescored later must reproduce the reward.
            record = {"outcome": scored.outcome, "probability": scored.probability}
            assert rescore_stored_outcome(record, rule) == pytest.approx(scored.reward)


def test_clean_contract_treats_truncation_as_invalid_even_when_parsable():
    scored = score_clean_parsed(clean_parsed(), "quadratic", truncated=True)
    assert scored.outcome == "INVALID" and scored.failure == "truncated"
    assert scored.reward == -1.0


def test_clean_contract_refuses_ungraded_rows_and_quad_cost():
    with pytest.raises(ValueError, match="deterministically gradable"):
        score_clean_parsed({**clean_parsed(), "needs_math_judge": True}, "binary")
    with pytest.raises(ValueError, match="no deterministic grade"):
        score_clean_parsed({**clean_parsed(), "correct": None}, "binary")
    with pytest.raises(ValueError, match="supports"):
        score_clean_parsed(clean_parsed(), "quad_cost")


def test_clean_contract_rejects_out_of_range_or_boolean_confidence():
    for bad in (1.5, -0.1, True):
        scored = score_clean_parsed({**clean_parsed(), "confidence": bad}, "quadratic")
        assert scored.outcome == "INVALID" and scored.failure == "confidence"


def test_clean_scored_rows_calibrate_reward_scales():
    items = [{"item_id": "a"}, {"item_id": "b"}]
    records = []
    for item_id, outcomes in (("a", [(True, 0.9), (False, 0.8)]), ("b", [(True, 0.4), (None, None)])):
        for index, (correct, p) in enumerate(outcomes):
            parsed = clean_parsed(answer=correct is not None, confidence=p, correct=bool(correct))
            scored = score_clean_parsed(parsed, "binary")
            records.append({"item_id": item_id, "step": 0, "rollout_index": index,
                            "outcome": scored.outcome, "probability": scored.probability})
    result = calibrate_reward_scales(items, records, rules=("binary", "quadratic"))
    assert set(result["arms"]) == {"binary", "quadratic"}
    assert result["arms"]["binary"]["scale"] == pytest.approx(1.0)
    assert result["treatment_contrast"]["support"]["groups_with_invalid"] == 1


# --- clean-idk-v1 (diagnostic) ---------------------------------------------



@pytest.mark.parametrize("raw,scorer,expected", [
    ("Reasoning.\nConfidence: 20%\nANSWER: I DON'T KNOW", "inspect", True),
    ("Final Answer: I don’t know", "medmcqa", True),
    ("**Answer: I dont know.**", "gpqa", True),
    ("I DON'T KNOW\nConfidence: 10%", "ethics", True),
    ("I don't know which is right, but\nConfidence: 50%\nANSWER: B", "inspect", False),
    ("I don't know\nmaybe yes", "ethics", False),
    ("yes\nConfidence: 80%", "ethics", False),
])
def test_abstention_is_read_only_from_the_answer_line(raw, scorer, expected):
    assert clean_abstention(raw, scorer) is expected


@pytest.mark.parametrize("rule", ["binary", "quadratic"])
def test_idk_pays_zero_and_other_answers_score_as_clean(rule):
    invalid = clean_parsed(answer=False, confidence=None)
    abstain = score_clean_idk_parsed(invalid, "Answer: I DON'T KNOW", "gpqa", rule)
    assert (abstain.outcome, abstain.reward, abstain.abstained, abstain.formatted) == ("ABSTAINED", 0.0, True, True)
    answered = score_clean_idk_parsed(clean_parsed(confidence=0.8), "Confidence: 80%\nAnswer: B", "gpqa", rule)
    assert answered.outcome == "CORRECT" and answered.reward == pytest.approx(RULES[rule](0.8, True))
    # Truncation beats an abstention-looking tail, and malformed output stays -1.
    assert score_clean_idk_parsed(invalid, "Answer: I DON'T KNOW", "gpqa", rule, truncated=True).outcome == "INVALID"
    assert score_clean_idk_parsed(invalid, "no idea", "gpqa", rule).reward == -1.0
