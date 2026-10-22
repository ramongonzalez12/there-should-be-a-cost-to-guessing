"""Prompt assembly and response parsing."""

from __future__ import annotations

import hashlib
import json
import re

# MMLU-Pro has ten answer choices, so appending the required abstention option
# needs K.  Keep the full alphabet here so prompt assembly, unlike the dataset
# reference labels, is not silently limited to ten existing options.
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def messages_sha256(messages: list[dict]) -> str:
    """Fingerprint the exact ordered messages sent to a model."""
    canonical = json.dumps(
        messages, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _published_mc_prompt(item: dict, *, treatment: bool) -> str:
    """Build the disclosed Artificial Analysis zero-shot MC prompt.

    The control is byte-for-byte the published template after substituting the
    question and choices.  The treatment changes only what the intervention
    logically requires: it adds the abstention choice and requests probability.
    """
    opts = list(item.get("choices") or [])
    if treatment:
        opts.append("I DON'T KNOW")
    letters = _LETTERS[:len(opts)]
    allowed = "/".join(letters)
    final = (
        "The last two lines of your response should be in the following format: "
        f"'Answer: {allowed}' and 'Probability: 0-100'."
        if treatment else
        "The last line of your response should be in the following format: "
        f"'Answer: {allowed}' (e.g. 'Answer: A')."
    )
    choices = "\n".join(f"{letters[i]}) {choice}" for i, choice in enumerate(opts))
    return f"Answer the following multiple choice question. {final}\n\n" \
           f"{item['question']}\n\n{choices}"


def build_messages(item: dict, contract: dict) -> list[dict]:
    """Assemble the prompt. The contract goes in the system message and the
    question in the user message, identically across every arm — the only text
    that varies between arms is the announced rule itself."""
    protocol = contract.get("protocol")
    if protocol in {"published_standard", "published_treatment"}:
        treatment = protocol == "published_treatment"
        if item["kind"] == "mc":
            user = _published_mc_prompt(item, treatment=treatment)
        else:
            # OpenAI's published SimpleQA harness sends the bare question.  The
            # treatment retains that question verbatim and puts the experimental
            # instruction in a system message.
            user = item["question"]
        messages = []
        if treatment:
            messages.append({"role": "system", "content": contract["prompt"]})
        messages.append({"role": "user", "content": user})
        return messages

    system = contract["prompt"]
    if item["kind"] == "mc":
        opts = item["choices"] or []
        idk = _LETTERS[len(opts)]
        body = "\n".join(f"{_LETTERS[i]}. {c}" for i, c in enumerate(opts))
        # Historical protocols append abstention. Preserve their prompts for
        # reproducibility; the September 20 confidence-only design needs a
        # separately versioned path. Only a FIXED wrong-answer penalty collapses
        # to rescaled accuracy without abstention. A confidence-dependent
        # quadratic score can distinguish calibration with the original choices.
        user = (f"{item['question']}\n\n{body}\n{idk}. I DON'T KNOW\n\n"
                f"Reply with a single letter A-{idk} as your ANSWER.")
    else:
        user = item["question"]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def idk_letter(item: dict) -> str:
    """Which letter means abstention for this item."""
    return _LETTERS[len(item.get("choices") or [])]


ANSWER_RE = re.compile(r"answer\s*[:=]\s*(.*?)(?=\n\s*(?:probability|confidence)\s*[:=]|\Z)",
                       re.IGNORECASE | re.DOTALL)
# The token keeps its text (not just its value) because the notation decides
# the reading: "85" is a percentage, "0.85" is a fraction. Group 2 records an
# explicit percent sign so "0.85%" can still mean 0.85 of one percent.
CONF_RE = re.compile(r"(?:probability|confidence)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?|\.\d+)\s*(%?)",
                     re.IGNORECASE)


def probability_from_token(token: str, percent_sign: str = "") -> float | None:
    """Read a stated probability token as a fraction in [0, 1], or None.

    Integers are percentages: "85" -> 0.85, "0" -> 0.0, "1" -> 0.01. A token
    written with a decimal point whose value is at most 1.0 is read as a
    fraction: "0.85" -> 0.85, "1.0" -> 1.0, unless it carries an explicit
    percent sign. Anything outside 0-100 is malformed and returns None.

    Why this exists: until 2026-08-27 every parser here divided every token by
    100, so a model writing "PROBABILITY: 0.85" against the requested integer
    format was stored at 0.0085. That is the "notation artifact": it put 481
    treatment-arm responses that were 85% correct into the 0% confidence bin
    and made the announced rule look as if it lowered confidence. The reading
    below is the analysis-only correction adopted in
    scripts/analyze_notation_artifact.py, now applied at the source so no
    downstream table can inherit the poisoned column again.
    """
    try:
        value = float(token)
    except ValueError:
        return None
    if "." in token and value <= 1.0 and not percent_sign:
        return value
    if 0.0 <= value <= 100.0:
        return value / 100.0
    return None


def last_probability(raw: str) -> float | None:
    """The LAST stated probability in a response, read with the notation rule.

    Last, not first, for the same reason Artificial Analysis takes the last
    answer: a model that revises itself should be scored on the number it
    ended with, not the one it abandoned. Pairing the last answer with the
    first probability (the previous behaviour) attached a discarded confidence
    to a kept answer.
    """
    matches = list(CONF_RE.finditer(raw or ""))
    if not matches:
        return None
    m = matches[-1]
    return probability_from_token(m.group(1), m.group(2))
# Textual abstention only. A bare letter is NOT matched here: which letter means
# "I don't know" depends on how many options the item had, and that is the
# caller's business (see idk_letter). Conflating them would mark every model
# that answered "E" on a five-option question as having abstained.
IDK_RE = re.compile(
    r"^\s*(i\s*don'?t\s*know|i\s*do\s*not\s*know|idk|unknown|unverified|"
    r"abstain|no\s*answer|cannot\s+determine|insufficient\s+information)\b\.?\s*$",
    re.IGNORECASE)


def parse(raw: str) -> tuple[str, float | None, bool, bool]:
    """Returns (answer, probability in [0,1] or None, is_abstention, followed_format).

    Note what is NOT here: a parse failure does not become an abstention. That
    distinction matters — scoring unparseable output as 'not attempted' rewards
    incoherence, which is exactly how a naive penalty benchmark gets gamed on
    day one. Unparseable is handled downstream as INCORRECT."""
    raw = raw or ""
    # Last ANSWER block, matching the probability rule below and the published
    # parity parser: a self-corrected response is scored on its final answer.
    matches = list(ANSWER_RE.finditer(raw))
    m = matches[-1] if matches else None
    formatted = bool(m)
    ans = (m.group(1) if m else raw).strip().strip("|").strip()
    ans = re.split(r"\n\s*confidence\s*[:=]", ans, flags=re.IGNORECASE)[0].strip()
    conf = last_probability(raw)
    # The contract requires both lines. An ANSWER with no usable PROBABILITY is
    # malformed, not an answer at an imputed confidence: imputing 0.5 fabricates
    # a calibration observation, and imputing 1.0 pays a correct answer the
    # maximum score for omitting the number. This matches parse_published and
    # training_contract, which already refused to impute.
    if formatted and conf is None:
        formatted = False
    return ans, conf, bool(IDK_RE.match(ans)), formatted


def parse_answer_only(raw: str) -> tuple[str, float | None, bool, bool]:
    """The `answer_only` protocol: an ANSWER line and nothing else.

    Same answer and abstention reading as `parse`, but a missing probability is
    not a format failure because none was asked for. The probability slot is
    always None so no downstream table can mistake this arm for a calibrated
    one; its outcomes are accuracy and abstention only."""
    raw = raw or ""
    matches = list(ANSWER_RE.finditer(raw))
    m = matches[-1] if matches else None
    ans = (m.group(1) if m else raw).strip().strip("|").strip()
    return ans, None, bool(IDK_RE.match(ans)), bool(m)


_AA_PRIMARY = re.compile(
    r"(?i)[*_]{0,2}answer[*_]{0,2}\s*:[\s*_]{0,2}\s*([A-Z])(?![A-Za-z0-9])"
)
_AA_FALLBACKS = [
    re.compile(r"\\boxed\{[^}]*([A-Z])[^}]*\}"),
    re.compile(r"answer is ([A-Z])", re.IGNORECASE),
    re.compile(r"answer is \(([A-Z])", re.IGNORECASE),
    re.compile(r"([A-Z])\)\s*[^A-Z]*"),
    re.compile(r"([A-Z])\s+is\s+the\s+correct\s+answer", re.IGNORECASE),
    re.compile(r"([A-Z])\s*$"),
    re.compile(r"([A-Z])\s*\."),
    # Artificial Analysis' final, deliberately permissive fallback. Keep it
    # last: on a well-formed response the more specific patterns above should
    # win, while this catches a terminal choice followed by punctuation.
    re.compile(r"([A-Z])\s*[^\w]"),
]


def parse_published(raw: str, item: dict, *, treatment: bool) -> tuple[str, float | None,
                                                                         bool, bool]:
    """Parse the disclosed standard benchmark formats.

    Artificial Analysis takes the last answer match to preserve a model's
    self-correction.  Free-form controls use the whole response, as SimpleQA
    does, because requiring an ANSWER field would itself change the benchmark.
    """
    raw = raw or ""
    if item["kind"] != "mc":
        if treatment:
            return parse(raw)
        ans = raw.strip()
        return ans, None, bool(IDK_RE.match(ans)), bool(ans)

    n_choices = len(item.get("choices") or [])
    choice_letters = set(_LETTERS[:n_choices])
    valid = set(_LETTERS[:n_choices + int(treatment)])
    stripped = raw.strip().upper()
    answer = stripped if len(stripped) == 1 and stripped in valid else ""
    matches = [m.group(1).upper() for m in _AA_PRIMARY.finditer(raw)
               if m.group(1).upper() in valid]
    if matches:
        answer = matches[-1]
    else:
        for pattern in _AA_FALLBACKS:
            # The abstention letter may only come from an explicit "Answer:"
            # field. The permissive prose fallbacks ("E. coli", "D) ...") could
            # otherwise manufacture an abstention out of ordinary text, and only
            # in the treatment arm, which is a one-directional error on the
            # experiment's primary outcome.
            matches = [m.group(1).upper() for m in pattern.finditer(raw)
                       if m.group(1).upper() in choice_letters]
            if matches:
                answer = matches[-1]
                break
    conf = last_probability(raw) if treatment else None
    abstained = treatment and answer == idk_letter(item)
    # Both fields are part of the treatment response contract. Accepting an
    # answer or abstention without probability would silently impute missing
    # confidence downstream and make malformed abstentions free.
    formatted = bool(answer) and (not treatment or conf is not None)
    return answer, conf, abstained, formatted
