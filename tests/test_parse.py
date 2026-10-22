"""Parsing separates three things that must never be confused: an answer, an
abstention, and a response that ignored the format. Collapsing the last two is
how incoherence starts scoring as honesty."""
import pytest

from belowzero.prompts import build_messages, idk_letter, parse


@pytest.mark.parametrize("text,want", [
    ("ANSWER: Paris\nPROBABILITY: 90",              ("Paris", 0.90, False, True)),
    ("ANSWER: Paris\nCONFIDENCE: 90",               ("Paris", 0.90, False, True)),
    ("ANSWER: I DON'T KNOW\nPROBABILITY: 5",        ("I DON'T KNOW", 0.05, True, True)),
    ("ANSWER: line one\nline two\nPROBABILITY: 40", ("line one\nline two", 0.40, False, True)),
    # An answer without a usable probability is malformed, not an answer at an
    # imputed confidence (0.5 fabricated a calibration point; 1.0 paid a correct
    # answer the maximum score for omitting the number).
    ("ANSWER: Paris",                               ("Paris", None, False, False)),
    # Notation decides the reading: an integer is a percentage, a decimal at or
    # below 1.0 is a fraction. "0.85" once became 0.0085 (the notation artifact).
    ("ANSWER: Paris\nPROBABILITY: 0.85",            ("Paris", 0.85, False, True)),
    ("ANSWER: Paris\nPROBABILITY: 1.0",             ("Paris", 1.0, False, True)),
    ("ANSWER: Paris\nPROBABILITY: 1",               ("Paris", 0.01, False, True)),
    ("ANSWER: Paris\nPROBABILITY: 0.5%",            ("Paris", 0.005, False, True)),
    ("ANSWER: Paris\nPROBABILITY: 150",             ("Paris", None, False, False)),
    ("",                                            ("", None, False, False)),
    ("Paris, probably.",                            ("Paris, probably.", None, False, False)),
])
def test_parse(text, want):
    assert parse(text) == want


def test_multiline_answer_is_not_truncated():
    """Regression: the answer regex once stopped at the first newline, silently
    breaking every length and structure checker on the behaviour track."""
    ans, _, _, _ = parse("ANSWER: - one\n- two\n- three\nPROBABILITY: 80")
    assert ans.count("\n") == 2


def test_ten_choice_prompt_appends_k_as_abstention():
    """MMLU-Pro already uses A through J, so its required abstention option is K."""
    item = {
        "kind": "mc",
        "question": "Choose one.",
        "choices": [f"option {i}" for i in range(10)],
    }
    messages = build_messages(item, {"prompt": "Return the requested fields."})

    assert idk_letter(item) == "K"
    assert "J. option 9\nK. I DON'T KNOW" in messages[1]["content"]
    assert "single letter A-K" in messages[1]["content"]


def test_answer_only_protocol_needs_no_probability():
    """The no-probability control: an ANSWER line alone is well formed, the
    abstention string still counts, and the confidence slot is always None so
    the arm can never be mistaken for a calibrated one."""
    from belowzero.contracts import PROMPT_ONLY_CONTRACTS
    from belowzero.prompts import parse_answer_only
    assert PROMPT_ONLY_CONTRACTS["answer_only"]["protocol"] == "answer_only"
    assert "PROBABILITY" not in PROMPT_ONLY_CONTRACTS["answer_only"]["prompt"]
    assert parse_answer_only("ANSWER: B") == ("B", None, False, True)
    assert parse_answer_only("ANSWER: I DON'T KNOW") == ("I DON'T KNOW", None, True, True)
    assert parse_answer_only("ANSWER: B\nPROBABILITY: 90") == ("B", None, False, True)
    assert parse_answer_only("I think it is B") == ("I think it is B", None, False, False)
