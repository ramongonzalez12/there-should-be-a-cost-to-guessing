"""Strict, deterministic contracts for the reinforcement-learning experiment.

The fine-tuning claim is only credible if a model cannot earn an abstention
reward by producing malformed text.  The broader benchmark runner accepts a
few disclosed output variants for compatibility with published evaluations;
training intentionally uses a much smaller language: exactly two lines, one
answer letter and one integer probability.

This module has no model or training-framework dependency.  The same functions
can therefore run in unit tests, a local mock rollout, TRL, or a hosted trainer.
"""

from __future__ import annotations

import collections
import itertools
import json
import math
import pathlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

from .rules import RULES

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# The two training contracts. The legacy one is the two-line ANSWER/PROBABILITY
# grammar with an appended I DON'T KNOW letter that every historical checkpoint
# was trained on. The clean one trains on the hosted battery's own confidence
# prompt (native benchmark wording plus one confidence sentence) and grades with
# the same frozen extractor the evaluation uses, so a trained checkpoint is
# evaluated on exactly the response format it was rewarded for.
LEGACY_CONTRACT = "two-line-idk-v1"
CLEAN_CONTRACT = "clean-final-answer-v1"
# Diagnostic only (never a clean-baseline candidate): the clean contract plus
# an I DON'T KNOW answer, to separate the historical contract's abstention
# option from its missing reasoning. Items keep the clean extraction protocol;
# the abstention is recognized on top of it.
CLEAN_IDK_CONTRACT = "clean-idk-v1"
CONTRACTS = (LEGACY_CONTRACT, CLEAN_CONTRACT, CLEAN_IDK_CONTRACT)
# The extraction protocol each contract's items carry (References.parse keys on it).
ITEM_PROTOCOL = {LEGACY_CONTRACT: LEGACY_CONTRACT, CLEAN_CONTRACT: CLEAN_CONTRACT,
                 CLEAN_IDK_CONTRACT: CLEAN_CONTRACT}
# quad_cost exists only under the legacy contract: its cost term prices an
# assertion against a declared abstention, and the clean contract has none.
CLEAN_REWARD_RULES = ("binary", "quadratic")
STRICT_RESPONSE_FORMAT = (
    "Respond with exactly two lines:\n"
    "ANSWER: <one allowed letter>\n"
    "PROBABILITY: <an integer from 0 to 100>\n"
    "Do not add spaces after the answer letter or probability number."
)

_STRICT_RESPONSE_RE = re.compile(r"\AANSWER: ([A-Z])\nPROBABILITY: (0|[1-9][0-9]?|100)\Z")


@dataclass(frozen=True)
class ParsedMCResponse:
    """The complete state needed to grade one constrained completion."""

    answer: str | None
    probability: float | None
    abstained: bool
    formatted: bool
    failure: str | None = None
    format_variant: str | None = None


@dataclass(frozen=True)
class ScoredMCResponse:
    """A parsed completion plus its deterministic outcome and reward."""

    answer: str | None
    probability: float | None
    abstained: bool
    formatted: bool
    correct: bool
    reward: float
    outcome: str
    failure: str | None = None
    format_variant: str | None = None


def allowed_letters(n_choices: int) -> str:
    """Return answer letters followed by the one explicit abstention letter."""
    if not 2 <= n_choices < len(LETTERS):
        raise ValueError("multiple-choice items need 2 to 25 answer choices")
    return LETTERS[: n_choices + 1]


def idk_letter(n_choices: int) -> str:
    """Return the appended abstention letter for an item."""
    return allowed_letters(n_choices)[-1]


def parse_mc_response(raw: str, n_choices: int) -> ParsedMCResponse:
    """Parse the two-line grammar without repairing semantic content.

    A final line ending is tolerated because generation APIs commonly include
    the stop newline in decoded text. ASCII spaces and tabs at line endings are
    also normalized because chat models commonly emit Markdown hard breaks.
    The raw response remains in the audit record and the normalization is
    labeled. No other leading, trailing, or embedded material is accepted.
    """
    text = (raw or "").rstrip("\r\n")
    canonical = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    format_variant = "trailing_whitespace" if canonical != text else None
    match = _STRICT_RESPONSE_RE.fullmatch(canonical)
    if not match:
        return ParsedMCResponse(None, None, False, False, "format")

    answer = match.group(1)
    if answer not in allowed_letters(n_choices):
        return ParsedMCResponse(answer, None, False, False, "answer_letter")

    probability = int(match.group(2)) / 100.0
    return ParsedMCResponse(
        answer=answer,
        probability=probability,
        abstained=answer == idk_letter(n_choices),
        formatted=True,
        format_variant=format_variant,
    )


def score_mc_response(
    raw: str,
    reference: str,
    n_choices: int,
    rule: str,
    *,
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
) -> ScoredMCResponse:
    """Grade one completion with no semantic judge and no missing-value imputation."""
    if rule not in RULES:
        raise ValueError(f"unknown scoring rule: {rule}")
    if reference not in LETTERS[:n_choices]:
        raise ValueError("reference must name one of the substantive answer choices")
    if parse_failure >= 0:
        raise ValueError("parse_failure must be negative so incoherence is not free")
    # ...and at least as bad as the worst asserted outcome under THIS rule.
    # quad_cost(c=0.09) pays -1.09 for a confident wrong answer; a flat -1.0
    # floor would make malformed output strictly better than answering wrong
    # at p >= 0.955, a band an RL policy will find. Pure quadratic and binary
    # are unchanged (worst assertion is -1.0 and 0.0 respectively).
    worst_assertion = RULES[rule](1.0, False, c=assertion_cost)
    parse_failure = min(parse_failure, worst_assertion)

    parsed = parse_mc_response(raw, n_choices)
    if not parsed.formatted:
        return ScoredMCResponse(
            **asdict(parsed), correct=False, reward=parse_failure, outcome="INVALID"
        )
    if parsed.abstained:
        return ScoredMCResponse(
            **asdict(parsed), correct=False, reward=0.0, outcome="ABSTAINED"
        )

    correct = parsed.answer == reference
    kwargs = {"c": assertion_cost} if rule == "quad_cost" else {}
    reward = float(RULES[rule](parsed.probability, correct, **kwargs))
    return ScoredMCResponse(
        **asdict(parsed),
        correct=correct,
        reward=reward,
        outcome="CORRECT" if correct else "INCORRECT",
    )


def score_clean_parsed(
    parsed: Mapping[str, object],
    rule: str,
    *,
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
    truncated: bool = False,
) -> ScoredMCResponse:
    """Reward one completion already graded by the clean-final-answer-v1 extractor.

    ``parsed`` is the dict ``References.parse`` returns for an item whose
    ``assessment_protocol`` is ``clean-final-answer-v1`` (the output of
    ``experiments/confidence_only/clean_assessment.assess``). This module never
    imports that extractor: ``src/`` must not depend on ``experiments/``, and the
    caller already holds the exact extractor the evaluation runs.

    Both reward arms require the answer line AND the confidence line. The binary
    arm ignores the confidence value but not its presence; otherwise the binary
    policy would be free to drop the line the evaluation needs, and the two arms
    would differ in format as well as in reward. There is no abstention option in
    this contract, so ``abstained`` is always False. A truncated completion is
    INVALID even if an answer line happens to parse: the model did not finish.

    The return shape equals ``score_mc_response``'s so ``rollout_health``,
    ``rescore_stored_outcome`` and ``calibrate_reward_scales`` work unchanged.
    """
    if rule not in CLEAN_REWARD_RULES:
        raise ValueError(f"the clean contract supports {CLEAN_REWARD_RULES}, not {rule}")
    if parse_failure >= 0:
        raise ValueError("parse_failure must be negative so incoherence is not free")
    if parsed.get("needs_math_judge"):
        # Free-form math needs a judge; the training pool has none, and a
        # judge-free default here would silently grade them one way or the other.
        raise ValueError("clean training items must be deterministically gradable")
    worst_assertion = RULES[rule](1.0, False, c=assertion_cost)
    parse_failure = min(parse_failure, worst_assertion)

    answer_valid = parsed.get("answer_valid") is True
    confidence = parsed.get("confidence")
    confidence_valid = (
        parsed.get("confidence_valid") is True
        and isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 0.0 <= float(confidence) <= 1.0
    )
    answer = parsed.get("answer")
    answer_text = None if answer is None else str(answer)
    probability = float(confidence) if confidence_valid else None
    failure = None
    if truncated:
        failure = "truncated"
    elif not answer_valid and not confidence_valid:
        failure = "answer_and_confidence"
    elif not answer_valid:
        failure = "answer"
    elif not confidence_valid:
        failure = "confidence"
    if failure is not None:
        return ScoredMCResponse(
            answer=answer_text,
            probability=probability,
            abstained=False,
            formatted=False,
            correct=False,
            reward=parse_failure,
            outcome="INVALID",
            failure=failure,
        )

    correct = parsed.get("correct")
    if correct not in (True, False):
        raise ValueError(f"formatted clean response has no deterministic grade: {correct!r}")
    reward = float(RULES[rule](probability, bool(correct)))
    return ScoredMCResponse(
        answer=answer_text,
        probability=probability,
        abstained=False,
        formatted=True,
        correct=bool(correct),
        reward=reward,
        outcome="CORRECT" if correct else "INCORRECT",
    )


_IDK = r"i\s*don'?\u2019?t\s*know"


def clean_abstention(raw: str, scorer: str) -> bool:
    """Whether a clean-idk-v1 response abstained, read from its answer line.

    Mirrors clean_assessment's line handling (strip Markdown bold and
    backticks, ignore the Confidence line): the final non-confidence line for
    multiple choice ("Answer: I DON'T KNOW" / "Final Answer: I DON'T KNOW"),
    the single label line for ETHICS. Prose that merely mentions not knowing
    is not an abstention.
    """
    lines = [line.strip().replace("**", "").strip("`").strip() for line in (raw or "").splitlines() if line.strip()]
    lines = [line for line in lines if not re.match(r"(?i)^confidence\s*:", line)]
    if not lines:
        return False
    if scorer == "ethics":
        return len(lines) == 1 and re.fullmatch(r"(?i)(?:answer\s*:\s*)?" + _IDK + r"[.!]?", lines[0]) is not None
    return re.fullmatch(r"(?i)(?:final\s+)?answer\s*:\s*" + _IDK + r"[.!]?", lines[-1]) is not None


def score_clean_idk_parsed(
    parsed: Mapping[str, object],
    raw: str,
    scorer: str,
    rule: str,
    *,
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
    truncated: bool = False,
) -> ScoredMCResponse:
    """clean-idk-v1: an abstention pays 0 in both arms, as in the historical
    contract; any other response is scored exactly as clean-final-answer-v1."""
    if not truncated and clean_abstention(raw, scorer):
        if rule not in CLEAN_REWARD_RULES:
            raise ValueError(f"the clean contracts support {CLEAN_REWARD_RULES}, not {rule}")
        return ScoredMCResponse(answer=None, probability=None, abstained=True, formatted=True,
                                correct=False, reward=0.0, outcome="ABSTAINED")
    return score_clean_parsed(parsed, rule, assertion_cost=assertion_cost,
                              parse_failure=parse_failure, truncated=truncated)


def exercise_clean_contract(
    parse,
    items: Iterable[Mapping[str, object]],
    rules: Iterable[str] = CLEAN_REWARD_RULES,
    *,
    parse_failure: float = -1.0,
) -> dict[str, int]:
    """Exhaustively check the clean contract through the REAL extractor.

    ``parse(item, raw)`` must be the extractor the trainer uses. For each item it
    writes a correct and a wrong response at all 101 confidences plus the three
    malformed shapes (answer only, confidence only, neither), and checks each
    outcome and reward. Passing the extractor in keeps ``src/`` independent of
    ``experiments/`` while still exercising the bytes that will grade training.
    """
    checked: collections.Counter[str] = collections.Counter()
    for item in items:
        target = str(item["target"])
        wrong = str(item["wrong"])
        answer_line = str(item["answer_line"])
        # Label tasks (ETHICS) allow no prose besides the two lines, so their
        # fixtures pass an empty reasoning preamble.
        reasoning = str(item.get("reasoning", "Some reasoning.\n"))
        for rule in rules:
            for percent in range(101):
                for answer, expected in ((target, "CORRECT"), (wrong, "INCORRECT")):
                    raw = f"{reasoning}Confidence: {percent}%\n{answer_line.format(answer)}"
                    result = score_clean_parsed(
                        parse(item, raw), rule, parse_failure=parse_failure
                    )
                    if result.outcome != expected:
                        raise AssertionError(f"{rule} misgraded {raw!r}: {result.outcome}")
                    reference = float(RULES[rule](percent / 100, expected == "CORRECT"))
                    if not math.isclose(result.reward, reference, abs_tol=1e-12):
                        raise AssertionError(f"{rule} paid {result.reward} for {raw!r}")
                    checked[rule] += 1
            for raw in (
                answer_line.format(target),
                "Confidence: 90%",
                "I am not sure.",
                "Confidence: 90\n" + answer_line.format(target),
                "Confidence: 101%\n" + answer_line.format(target),
            ):
                result = score_clean_parsed(parse(item, raw), rule, parse_failure=parse_failure)
                floor = min(parse_failure, RULES[rule](1.0, False))
                if result.outcome != "INVALID" or result.reward != floor:
                    raise AssertionError(f"{rule} made malformed output free: {raw!r}")
                checked[rule] += 1
    return dict(checked)


def rescore_stored_outcome(
    record: Mapping[str, object],
    rule: str,
    *,
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
) -> float:
    """Rescore one stored outcome under any rule, without relying on answer letters.

    ``(outcome, probability)`` are the sufficient statistics for every rule in
    RULES, so a response saved once can be scored under a rule chosen later. Two
    separate things depend on that.

    Reward-scale calibration uses it because the selector rebalances answer
    positions after profiling, which makes the original answer letter unsafe to
    grade against the final training item.

    Held-out rescoring uses it to ask whether a trained arm's advantage is
    calibration or is specific to the rule it was trained against. That question
    is only answerable if the held-out score is computed the same way the
    training score was, including the treatment of invalid and abstained cells.
    Sharing this function is what guarantees that; a second implementation that
    scored INVALID as 0 would quietly hand the comparison a different answer.
    """
    outcome = str(record.get("outcome"))
    if outcome == "INVALID":
        # Unparseable output is not silence. Scoring it at 0 here would reintroduce
        # the exact conflation the project exists to argue against.
        return parse_failure
    if outcome == "ABSTAINED":
        return 0.0
    if outcome not in {"CORRECT", "INCORRECT"}:
        raise ValueError(f"record contains unknown outcome {outcome}")

    probability = record.get("probability")
    if probability is None:
        raise ValueError("attempted response is missing probability")
    p = float(probability)
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"probability is outside [0, 1]: {p}")
    kwargs = {"c": assertion_cost} if rule == "quad_cost" else {}
    return float(RULES[rule](p, outcome == "CORRECT", **kwargs))


def _profile_reward(
    record: Mapping[str, object],
    rule: str,
    *,
    assertion_cost: float,
    parse_failure: float,
) -> float:
    """Backwards-compatible alias used by reward-scale calibration."""
    return rescore_stored_outcome(
        record, rule, assertion_cost=assertion_cost, parse_failure=parse_failure
    )


def calibrate_reward_scales(
    items: Iterable[Mapping[str, object]],
    records: Iterable[Mapping[str, object]],
    *,
    rules: Iterable[str] = ("binary", "quadratic", "quad_cost"),
    reference_rule: str = "binary",
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
    min_rollouts: int = 2,
) -> dict[str, object]:
    """Match initial centered-advantage RMS using fixed per-arm multipliers.

    One multiplier is calculated from unchanged-base rollouts and then held
    fixed for the whole run. This preserves each scoring rule's relative reward
    differences across questions, unlike standardizing every group separately.
    """
    selected_ids = {str(item["item_id"]) for item in items}
    if not selected_ids:
        raise ValueError("reward-scale calibration needs at least one selected item")
    if min_rollouts < 2:
        raise ValueError("reward-scale calibration needs at least two rollouts per group")

    selected_rules = tuple(rules)
    if reference_rule not in selected_rules:
        raise ValueError("reference reward rule must be one of the calibrated rules")
    unknown = [rule for rule in selected_rules if rule not in RULES]
    if unknown:
        raise ValueError(f"unknown reward rules: {unknown}")

    groups: dict[tuple[str, object, str], list[Mapping[str, object]]] = collections.defaultdict(
        list
    )
    profile_inputs = set()
    for record in records:
        item_id = str(record.get("item_id"))
        if item_id not in selected_ids:
            continue
        profile_input = str(record.get("_profile_input", "profile-0"))
        profile_inputs.add(profile_input)
        # Profile files should use integer steps, but stringify here so a
        # malformed or legacy ``null`` step produces a clear group rather than
        # making deterministic sorting fail with an unrelated TypeError.
        key = (profile_input, str(record.get("step")), item_id)
        groups[key].append(record)

    if not groups:
        raise ValueError("no selected items have base-profile rollouts")
    expected_groups = {
        (profile_input, item_id) for profile_input in profile_inputs for item_id in selected_ids
    }
    observed_groups = {(profile_input, item_id) for profile_input, _step, item_id in groups}
    missing = sorted(expected_groups - observed_groups)
    if missing:
        raise ValueError(f"base profile is missing {len(missing)} selected item groups")

    by_rule = {
        rule: {
            "sum_squared_centered": 0.0,
            "sum_absolute_centered": 0.0,
            "rollouts": 0,
            "groups": 0,
            "active_groups": 0,
            "reward_min": math.inf,
            "reward_max": -math.inf,
        }
        for rule in selected_rules
    }
    # A reward formula can look different on paper but become identical after
    # the group mean is subtracted.  Keep the exact centered vectors so the
    # profile can verify that the treatment contrast reaches the optimizer.
    centered_by_rule: dict[str, list[float]] = {
        rule: [] for rule in selected_rules
    }
    pairwise_group_stats = {
        (left, right): {
            "comparable_groups": 0,
            "directionally_distinct_groups": 0,
            "cosine_sum": 0.0,
        }
        for left, right in itertools.combinations(selected_rules, 2)
    }
    support = {
        "groups": 0,
        "groups_with_invalid": 0,
        "groups_with_assertion_and_abstention": 0,
        "groups_with_varied_assertion_probability": 0,
    }
    for key, group in sorted(groups.items()):
        if len(group) < min_rollouts:
            raise ValueError(
                f"profile group {key} has {len(group)} rollouts; {min_rollouts} required"
            )
        outcomes = [str(record.get("outcome")) for record in group]
        asserted = [
            record for record, outcome in zip(group, outcomes)
            if outcome in {"CORRECT", "INCORRECT"}
        ]
        assertion_probabilities = {
            float(record["probability"])
            for record in asserted
            if record.get("probability") is not None
        }
        support["groups"] += 1
        support["groups_with_invalid"] += int("INVALID" in outcomes)
        support["groups_with_assertion_and_abstention"] += int(
            bool(asserted) and "ABSTAINED" in outcomes
        )
        support["groups_with_varied_assertion_probability"] += int(
            len(assertion_probabilities) > 1
        )

        group_centered: dict[str, list[float]] = {}
        for rule in selected_rules:
            rewards = [
                _profile_reward(
                    record,
                    rule,
                    assertion_cost=assertion_cost,
                    parse_failure=parse_failure,
                )
                for record in group
            ]
            mean_reward = sum(rewards) / len(rewards)
            centered = [reward - mean_reward for reward in rewards]
            group_centered[rule] = centered
            centered_by_rule[rule].extend(centered)
            stats = by_rule[rule]
            stats["sum_squared_centered"] += sum(value * value for value in centered)
            stats["sum_absolute_centered"] += sum(abs(value) for value in centered)
            stats["rollouts"] += len(centered)
            stats["groups"] += 1
            stats["active_groups"] += int(any(value != 0.0 for value in centered))
            stats["reward_min"] = min(stats["reward_min"], *rewards)
            stats["reward_max"] = max(stats["reward_max"], *rewards)

        for pair, stats in pairwise_group_stats.items():
            left, right = pair
            left_vector = group_centered[left]
            right_vector = group_centered[right]
            left_norm = math.sqrt(sum(value * value for value in left_vector))
            right_norm = math.sqrt(sum(value * value for value in right_vector))
            if left_norm == 0.0 or right_norm == 0.0:
                continue
            cosine = sum(
                left_value * right_value
                for left_value, right_value in zip(left_vector, right_vector)
            ) / (left_norm * right_norm)
            # Floating-point roundoff can move a mathematically exact cosine a
            # few ulps outside [-1, 1].  Clamp before using it as a diagnostic.
            cosine = max(-1.0, min(1.0, cosine))
            stats["comparable_groups"] += 1
            stats["directionally_distinct_groups"] += int(cosine < 1.0 - 1e-9)
            stats["cosine_sum"] += cosine

    arms = {}
    for rule, stats in by_rule.items():
        count = int(stats["rollouts"])
        rms = math.sqrt(float(stats["sum_squared_centered"]) / count)
        if not math.isfinite(rms) or rms <= 0.0:
            raise ValueError(f"{rule} has no finite nonzero advantage spread")
        arms[rule] = {
            "raw_centered_rms": rms,
            "raw_centered_mean_absolute": float(stats["sum_absolute_centered"]) / count,
            "reward_min": float(stats["reward_min"]),
            "reward_max": float(stats["reward_max"]),
            "groups": int(stats["groups"]),
            "active_groups": int(stats["active_groups"]),
            "rollouts": count,
        }

    target_rms = float(arms[reference_rule]["raw_centered_rms"])
    for rule in selected_rules:
        scale = target_rms / float(arms[rule]["raw_centered_rms"])
        arms[rule]["scale"] = scale
        arms[rule]["scaled_centered_rms"] = float(arms[rule]["raw_centered_rms"]) * scale

    pairwise = {}
    for pair, stats in pairwise_group_stats.items():
        left, right = pair
        left_vector = centered_by_rule[left]
        right_vector = centered_by_rule[right]
        dot = sum(
            left_value * right_value
            for left_value, right_value in zip(left_vector, right_vector)
        )
        left_norm = math.sqrt(sum(value * value for value in left_vector))
        right_norm = math.sqrt(sum(value * value for value in right_vector))
        global_cosine = max(-1.0, min(1.0, dot / (left_norm * right_norm)))
        left_scale = float(arms[left]["scale"])
        right_scale = float(arms[right]["scale"])
        scaled_rms_difference = math.sqrt(
            sum(
                (left_value * left_scale - right_value * right_scale) ** 2
                for left_value, right_value in zip(left_vector, right_vector)
            )
            / len(left_vector)
        )
        comparable = int(stats["comparable_groups"])
        distinct = int(stats["directionally_distinct_groups"])
        pairwise[f"{left}_vs_{right}"] = {
            "comparable_groups": comparable,
            "directionally_distinct_groups": distinct,
            "directionally_distinct_rate": distinct / comparable if comparable else 0.0,
            "mean_group_cosine_similarity": (
                float(stats["cosine_sum"]) / comparable if comparable else None
            ),
            "global_cosine_similarity": global_cosine,
            "scaled_rms_difference": scaled_rms_difference,
            "scaled_rms_difference_relative_to_reference": (
                scaled_rms_difference / target_rms
            ),
        }

    treatment_contrast = {
        "support": {
            **support,
            "assertion_and_abstention_rate": (
                support["groups_with_assertion_and_abstention"] / support["groups"]
            ),
            "varied_assertion_probability_rate": (
                support["groups_with_varied_assertion_probability"] / support["groups"]
            ),
        },
        "pairwise": pairwise,
    }

    return {
        "schema_version": 1,
        "method": "fixed_arm_scale_to_reference_centered_rms",
        "reference_rule": reference_rule,
        "target_centered_rms": target_rms,
        "assertion_cost": assertion_cost,
        "parse_failure": parse_failure,
        "profile_inputs": sorted(profile_inputs),
        "selected_items": len(selected_ids),
        "arms": arms,
        "treatment_contrast": treatment_contrast,
    }


def make_mc_reward_fn(
    rule: str,
    *,
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
    audit_path: str | pathlib.Path | None = None,
    min_health_records: int = 256,
    max_invalid_rate: float = 0.01,
    max_abstention_rate: float = 0.95,
):
    """Build a TRL-compatible reward function with an optional fail-closed audit."""
    audit_records: list[dict[str, object]] = []
    # One counter per reward call. rollout_health groups completions by
    # (step, item_id) to detect a sampler that returns byte-identical samples;
    # without a step in the audit row every call for an item collapsed into one
    # group across the whole run and the gate could never fire.
    call_counter = {"step": 0}
    output = pathlib.Path(audit_path) if audit_path is not None else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)

    def reward_fn(prompts=None, completions=None, reference=None, n_choices=None, **kwargs):
        del prompts
        refs = list(reference or [])
        counts = list(n_choices or [])
        rows = list(completions or [])
        if not (len(rows) == len(refs) == len(counts)):
            raise ValueError("completions, reference, and n_choices must have equal lengths")
        item_ids = list(kwargs.get("item_id") or [None] * len(rows))
        if len(item_ids) != len(rows):
            raise ValueError("item_id must be absent or have the same length as completions")

        rewards, batch_audit = [], []
        call_counter["step"] += 1
        for completion, ref, count, item_id in zip(rows, refs, counts, item_ids):
            raw = (
                completion if isinstance(completion, str) else completion[-1].get("content", "")
            )
            scored = score_mc_response(
                raw,
                str(ref),
                int(count),
                rule,
                assertion_cost=assertion_cost,
                parse_failure=parse_failure,
            )
            rewards.append(scored.reward)
            batch_audit.append(
                {
                    "step": call_counter["step"],
                    "item_id": item_id,
                    "raw": raw,
                    **asdict(scored),
                }
            )
        audit_records.extend(batch_audit)
        if output is not None:
            with output.open("a", encoding="utf-8") as handle:
                for record in batch_audit:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

        report = rollout_health(
            audit_records,
            max_invalid_rate=max_invalid_rate,
            max_abstention_rate=max_abstention_rate,
        )
        reward_fn.health_report = report
        if len(audit_records) >= min_health_records and report["status"] == "RED":
            raise RuntimeError(f"training rollout health gate failed: {report['reasons']}")
        return rewards

    reward_fn.__name__ = f"strict_mc_{rule}"
    reward_fn.audit_records = audit_records
    reward_fn.health_report = {"status": "TOO_EARLY", "n": 0, "rates": {}, "reasons": []}
    return reward_fn


def exercise_reward_contract(
    rules: Iterable[str] = ("binary", "quadratic", "quad_cost"),
    *,
    n_choices: int = 4,
    assertion_cost: float = 0.09,
    parse_failure: float = -1.0,
) -> dict[str, int]:
    """Exercise all 101 probabilities and every reachable response state.

    This is deliberately exhaustive rather than a few hand-picked examples.
    It verifies that every valid output receives a finite reward, every malformed
    output receives the declared failure reward, and abstention stays exactly 0.
    """
    checked = collections.Counter()
    reference = "A"
    wrong = "B"
    abstain = idk_letter(n_choices)

    for rule in rules:
        for probability in range(101):
            for answer, expected_outcome in (
                (reference, "CORRECT"),
                (wrong, "INCORRECT"),
                (abstain, "ABSTAINED"),
            ):
                raw = f"ANSWER: {answer}\nPROBABILITY: {probability}"
                result = score_mc_response(
                    raw,
                    reference,
                    n_choices,
                    rule,
                    assertion_cost=assertion_cost,
                    parse_failure=parse_failure,
                )
                if result.outcome != expected_outcome:
                    raise AssertionError(f"{rule} misclassified {raw!r}: {result.outcome}")
                if not math.isfinite(result.reward):
                    raise AssertionError(f"{rule} produced a non-finite reward for {raw!r}")
                if expected_outcome == "ABSTAINED" and result.reward != 0.0:
                    raise AssertionError(f"{rule} did not score abstention as zero")
                checked[rule] += 1

        malformed = (
            "",
            "A",
            "ANSWER: A",
            "ANSWER: A\nPROBABILITY: 101",
            "ANSWER: A\nPROBABILITY: 50.5",
            "Reasoning\nANSWER: A\nPROBABILITY: 50",
            "ANSWER: Z\nPROBABILITY: 50",
        )
        for raw in malformed:
            result = score_mc_response(
                raw,
                reference,
                n_choices,
                rule,
                assertion_cost=assertion_cost,
                parse_failure=parse_failure,
            )
            # Malformed output is never free AND never better than the worst
            # asserted outcome under this rule (quad_cost's worst is -1-c).
            expected_floor = min(parse_failure, RULES[rule](1.0, False, c=assertion_cost))
            if result.outcome != "INVALID" or result.reward != expected_floor:
                raise AssertionError(f"{rule} made malformed output free: {raw!r}")
            checked[rule] += 1

    return dict(checked)


def rollout_health(
    records: Iterable[Mapping[str, object]],
    *,
    max_invalid_rate: float = 0.01,
    max_abstention_rate: float = 0.95,
    max_exact_duplicate_group_rate: float = 0.95,
) -> dict[str, object]:
    """Return a fail-closed health verdict over actual scored trajectories."""
    rows = list(records)
    if not rows:
        return {"status": "RED", "reasons": ["no_rollouts"], "n": 0, "rates": {}}

    counts = collections.Counter(str(row.get("outcome", "MISSING")) for row in rows)
    n = len(rows)
    rates = {key: value / n for key, value in sorted(counts.items())}
    reasons = []
    if rates.get("INVALID", 0.0) > max_invalid_rate:
        reasons.append("invalid_rate")
    if rates.get("ABSTAINED", 0.0) > max_abstention_rate:
        reasons.append("abstention_collapse")
    if "MISSING" in rates:
        reasons.append("missing_outcome")

    # At temperature 1, every completion being byte-identical within almost
    # every multi-sample group is usually a sampling configuration failure, not
    # evidence that the model is certain.  This caught a hosted API behavior in
    # which setting one explicit seed caused all ``num_samples`` generations to
    # repeat.  Only evaluate rows that carry the raw text and a group identity;
    # generic callers that provide outcome counts alone retain the old contract.
    groups: dict[tuple[object, str], list[str]] = collections.defaultdict(list)
    for row in rows:
        item_id = row.get("item_id")
        raw = row.get("raw")
        if item_id is None or raw is None:
            continue
        groups[(row.get("step"), str(item_id))].append(str(raw))
    comparable_groups = [group for group in groups.values() if len(group) >= 2]
    exact_duplicate_groups = sum(len(set(group)) == 1 for group in comparable_groups)
    exact_duplicate_rate = (
        exact_duplicate_groups / len(comparable_groups) if comparable_groups else None
    )
    if (
        exact_duplicate_rate is not None
        and exact_duplicate_rate > max_exact_duplicate_group_rate
    ):
        reasons.append("exact_duplicate_group_collapse")
    return {
        "status": "RED" if reasons else "GREEN",
        "reasons": reasons,
        "n": n,
        "rates": rates,
        "group_diversity": {
            "comparable_groups": len(comparable_groups),
            "exact_duplicate_groups": exact_duplicate_groups,
            "exact_duplicate_group_rate": exact_duplicate_rate,
        },
    }
