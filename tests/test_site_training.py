"""Structural checks for the generated fine-tuning explainer.

These checks do not replace looking at the rendered page. They protect the
parts most likely to fail silently in a generated static site: navigation,
version metadata, local links, and the distinction between a proposed run and
an observed result.
"""

import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "below-zero"


def _builder():
    """Load the site builder as a module so its own tables can be compared.

    The expectations below are written out by hand on purpose: a test that
    derived everything from the builder would agree with any change the builder
    made, including a wrong one. Loading it as well lets the two be compared,
    which catches the other failure, a page added to the builder and never added
    here, where the hand-written list keeps passing on the pages it happens to
    name.
    """
    spec = importlib.util.spec_from_file_location(
        "below_zero_build_site", ROOT / "scripts" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
ALL_PAGES = (
    "index.html",
    "changes.html",
    "brief.html",
    "brief-table.html",
    "draft.html",
    "approach.html",
    "validation.html",
    "plan.html",
    "training.html",
    "dose-response.html",
    "replication.html",
    "open-questions.html",
    "why-linear-fails.html",
    "related-work.html",
    "literature.html",
    "style-guide.html",
)
# The working pages (the builder's LAB_ONLY_PAGES) are built only where their
# prose exists, the lab; the public tree has neither the prose nor the pages.
LAB_ONLY_PAGES = {"changes.html", "draft.html", "plan.html", "style-guide.html"}
LAB_PAGES_BUILT = (ROOT / "content" / "draft").is_dir()
lab_only = pytest.mark.skipif(not LAB_PAGES_BUILT, reason="working pages are built in the lab only")
PAGES = tuple(p for p in ALL_PAGES if LAB_PAGES_BUILT or p not in LAB_ONLY_PAGES)

LONG_PAGE_SECTIONS = {
    "brief.html": ("census", "scoring", "rule", "worth", "trained",
                   "honesty", "ask", "open", "appendix"),
    "brief-table.html": ("map", "problem", "prompting", "training", "chain",
                         "families", "next"),
    "draft.html": ("context", "premise", "rules", "wisdom", "measurement",
                   "training", "alignment"),
    "index.html": ("summary", "ordering", "reconcile", "census", "map", "about"),
    "changes.html": ("summary", "numbers", "defects", "data", "essay", "site",
                     "open", "revisions", "versions"),
    "related-work.html": ("rules", "choice", "reject", "testing", "signal", "benchmarks",
                          "training", "gaps"),
    "literature.html": ("answering", "scoring", "prompting", "training",
                        "chain", "next"),
    "validation.html": ("result", "reconstructed", "invalid", "limits", "cost", "next"),
    "training.html": (
        "final", "family", "replication", "pilot", "idea", "map", "loop", "choices",
        "accentuation", "arms", "plan", "evaluation", "result", "automation", "cost",
    ),
    "dose-response.html": ("versions", "outcome", "rules", "base",
                           "pressure", "limits"),
    "replication.html": ("design", "versions", "measures", "matrix",
                         "replicated", "mechanism", "limits"),
    "approach.html": ("claims", "pipeline", "separation", "rules", "check", "glossary"),
    "open-questions.html": ("belief", "agentic", "judge", "gaming", "transfer", "c", "scope"),
}


class PageParser(HTMLParser):
    """Collect links, body metadata, and selected semantic elements."""

    def __init__(self):
        super().__init__()
        self.body_attributes = {}
        self.links = []
        self.tune_steps = 0
        self.quadratic_dividers = 0
        self.section_nav_links = []
        self.heading_ids = []
        self._in_section_nav = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "body":
            self.body_attributes = attributes
        if tag == "nav" and "section-nav" in attributes.get("class", "").split():
            self._in_section_nav = True
        if tag == "a" and "href" in attributes:
            self.links.append(attributes["href"])
            if self._in_section_nav:
                self.section_nav_links.append(attributes["href"])
        if tag == "h2" and attributes.get("id"):
            self.heading_ids.append(attributes["id"])
        if tag == "div" and "tune-step" in attributes.get("class", "").split():
            self.tune_steps += 1
        if tag == "div" and "quadratic-divider" in attributes.get("class", "").split():
            self.quadratic_dividers += 1

    def handle_endtag(self, tag):
        if tag == "nav" and self._in_section_nav:
            self._in_section_nav = False


def parse_page(name):
    parser = PageParser()
    parser.feed((SITE / name).read_text(encoding="utf-8"))
    return parser


def test_all_site_pages_link_to_training_and_carry_version_metadata():
    for name in PAGES:
        parser = parse_page(name)

        assert "training.html" in parser.links, f"{name} omits Fine-tuning from nav"
        for attribute in (
            "data-created",
            "data-last-updated",
            "data-style-updated",
            "data-commit",
        ):
            assert parser.body_attributes.get(attribute), f"{name} lacks {attribute}"

        text = (SITE / name).read_text(encoding="utf-8")
        assert text.count('class="byline page-dates"') == 1, (
            f"{name} must show exactly one timestamp line"
        )
        assert re.search(
            r'Created\s+<time datetime="[^"]+">[^<]+</time>', text
        ), f"{name} lacks a visible creation timestamp"
        assert re.search(
            r'Last updated\s+<time datetime="[^"]+">[^<]+</time>', text
        ), f"{name} lacks a visible update timestamp"


def test_all_internal_html_links_resolve():
    for name in PAGES:
        for href in parse_page(name).links:
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc or not parsed.path.endswith(".html"):
                continue

            target = SITE / parsed.path
            assert target.exists(), f"{name} links to missing page {parsed.path}"


def test_table_brief_keeps_claims_attached_to_current_evidence():
    """The outline's loudest claims must match the processed-data build.

    These are deliberately exact fingerprints for the conclusions most likely
    to become stale when new model families or alignment runs are added.
    """
    text = (SITE / "brief-table.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for evidence in (
        "44 of 45 benchmarks with right-or-wrong answers, a wrong answer did not cost more than silence",
        "Accuracy 62.0%; confidence 93.2%; gap 31.3 points",
        "gap shrank 4.2 points",
        "closed 14% of the original overconfidence gap",
        "11 of 15 model-subject comparisons",
        "Accuracy 49.6%; confidence 76.7%; gap 27.2 points",
        "Accuracy 49.6%; confidence 54.8%; gap 5.2 points",
        "closed 81% of the pooled gap",
        "3 trained families, 33 matched pairs",
        "confidence-calibrated score improved in 29 of 33 of them",
        "all 21 of 21 off-subject comparisons",
        "Wrong at 80%+ confidence: 36.0%",
        "The confidence-calibrated score rose from 0.059 to 0.142",
        "11,172 stored responses",
        "confidence-calibrated score improved in 17 of 21 comparisons",
        "Subject-specific transfer has not yet been replicated in a second family",
        "7 same-subject comparisons",
        "21 outside-subject comparisons",
        "The same seven independently trained pairs appear on both sides",
        "+23.8 pp &rarr; &minus;2.0 pp",
        "+37.0 pp &rarr; +11.1 pp",
        "Corrected 25.7 points in-subject and 25.9 outside it",
        "98% of the absolute reduction transferred",
        "higher for 7 of 7 pair averages",
        "The result extends to a subject that supplied no training data",
        "GPQA, never used for training",
        "Training transferred the size of the correction, not identical final calibration",
        "44.2% &rarr; 5.9%",
        "87% of the original risk eliminated; fell in 3 of 3 pairs",
        "Wrong risky action at 90%+ confidence: 43.7%",
        "Five training runs, 80 decisions per model version, 800 matched decisions",
        "Took the prohibited shortcut in 92.6% of cases",
        "90.6%",
        "eliminating only 2.2% of the original shortcut rate",
        "73 of 224 malformed (32.59%)",
        "19,764 matched test responses",
        "79,872 responses across five behaviors",
        "21,760 choices",
        "make confidence more realistic",
        "4,108 usable confidence answers are shown from 4,536 matched responses",
        "19,278 usable confidence answers are shown from 19,764 matched responses",
    ):
        assert evidence in normalized

    assert text.count('class="reliability-figure"') == 2
    assert "The rule reduced answers in the 90% to 100% confidence range from 85% to 65%" in text
    assert "Training reduced answers in the 90% to 100% confidence range from 51% to 4%" in text
    assert "40 answers in 10 ranges with fewer than 20 answers" in text
    assert "57 answers in 5 ranges with fewer than 20 answers" in text
    assert text.count('class="reliability-point"') >= 20
    assert text.count("Share of answers at each level") == 2
    assert "96% confident, 66% correct" in text
    assert "95% confident, 69% correct" in text
    assert "Hollow dots" not in text
    assert "long-horizon scheming" in normalized
    assert "Not measured" in normalized


@lab_only
def test_report_draft_replaces_outline_placeholders_with_committed_evidence():
    """The Google Doc contained explicitly fake example rows.

    The generated draft must carry the verified magnitudes and the important
    boundary on the alignment claim, not merely reproduce the outline's shape.
    """
    text = (SITE / "draft.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for evidence in (
        "1,089,024 published responses",
        "What is established, and what this report adds",
        "The scoring theory is old",
        "Scale",
        "Application",
        "Extension",
        "Magnitude",
        "Comparison",
        "Matched test",
        "Prior research: field, date, scale",
        "What this report adds: extension and scale",
        "LLM research, 2025",
        "Outside LLMs, 1950s to 1970s",
        "LLM systems, 2023 to 2024",
        "15 frontier models on 200 questions in four categories",
        "explicitly elicited confidence on six other benchmarks",
        "55% accuracy versus 87% confidence",
        "Pluralistic alignment",
        "44 of the 45 reviewed benchmarks",
        "The scoring rule determines whether a 40% belief is reported as 0% or 40%",
        "Honest 40%: &minus;0.08 &middot; Extreme 0%: 0",
        "Honest 70%: +0.28 &middot; Extreme 100%: +0.40",
        "Knowledge and self-knowledge are different abilities",
        "Models were overconfident across every test we examined",
        "Every one of 27 model-benchmark comparisons was overconfident",
        "10 models, 7 benchmarks, 5,376 answered questions",
        "55.1%",
        "86.8%",
        "+31.8",
        "formula explained, no threshold",
        "Prompting left 84% of the overconfidence gap in place",
        "Training cut the confidence gap from 27 to 5 points",
        "49.6%",
        "76.7%",
        "54.8%",
        "0.183",
        "0.209",
        "Calibration training improved prudence, not broad alignment",
        "43.7%",
        "1.3%",
        "21.8%",
        "21.5%",
        "52.7% accepted it",
        "73.4% accepted it",
        "92.6%",
        "90.6%",
        "long-horizon scheming was not tested",
        "A reminder that no single goal erases other obligations",
        "No single metric erases those obligations",
        "6.8%",
        "1.0%",
        "85%",
        "16 of 16 checkpoints improved",
        "10,240 responses",
    ):
        assert evidence in normalized

    assert "Below data is fake" not in text
    assert "GPT-5 was slightly more accurate than GPT-5.2" not in text
    assert text.index("GPT-5.4") < text.index("GPT-5.2") < text.index("GPT-5</td>")
    assert text.index('id="premise"') < text.index('id="rules"')
    assert text.index('id="context"') < text.index('id="premise"')
    assert text.index('id="rules"') < text.index('id="wisdom"')
    assert text.index('id="wisdom"') < text.index('id="measurement"')
    assert text.index('id="measurement"') < text.index('id="training"')
    assert text.index('id="training"') < text.index('id="alignment"')
    assert 'id="conclusion"' not in text
    assert text.count('class="draft-exhibit ') == 9
    assert text.count('class="draft-detail"') == 7
    for figure_class in (
        "draft-context-figure",
        "draft-census-figure",
        "draft-incentive-figure",
        "draft-wisdom-figure",
        "draft-overconfidence-figure",
        "draft-prompt-figure",
        "draft-training-figure",
        "draft-alignment-figure",
        "draft-plural-figure",
    ):
        assert f'class="draft-exhibit {figure_class}"' in text
    assert text.count('class="draft-scatter-diagonal"') == 2

    overconfidence_table = re.search(
        r'<table class="brief-prose draft-overconfidence sortable-table".*?</table>',
        normalized,
    )
    assert overconfidence_table
    assert overconfidence_table.group().count("<tr") == 28


def test_literature_context_matches_the_current_prompting_comparison():
    """The literature page must not describe the superseded threshold bundle."""
    text = (SITE / "literature.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "formula without an answering threshold closed 16%" in normalized
    assert "left 84% in place" in normalized
    assert "4,536 matched responses" in normalized
    assert "training on it closed 81%" in normalized
    assert "rule and threshold closed 14%" not in normalized


def test_expectations_here_cover_every_page_the_builder_ships():
    """A new page must be added to this file, not just to the builder.

    Without this, adding a page to SITE silently exempts it from every check
    above: the loop iterates PAGES, so an unlisted page is not tested rather
    than failing. Same for a section rail, where an id renamed in the body and
    not in SECTION_NAV produces a rail link that scrolls nowhere.
    """
    builder = _builder()

    assert set(ALL_PAGES) | {builder.ESSAY_PAGE} == (
        {href for href, _, _ in builder.SITE} | set(builder.SUPERSEDED_PAGES))
    assert set(ALL_PAGES) == set(builder.PAGE_CREATED)
    assert builder.LAB_ONLY_PAGES == LAB_ONLY_PAGES
    assert {page: tuple(t for t, _ in secs)
            for page, secs in builder.SECTION_NAV.items()} == LONG_PAGE_SECTIONS


def test_long_pages_have_complete_local_section_navigation():
    for name in PAGES:
        parser = parse_page(name)
        expected = LONG_PAGE_SECTIONS.get(name, ())

        assert parser.section_nav_links == [f"#{target}" for target in expected]
        assert all(target in parser.heading_ids for target in expected)


def test_brief_live_payoff_table_has_its_own_horizontal_scroll_boundary():
    """The global table minimum must not widen the phone viewport.

    Other report tables already live inside ``table-wrap``. The interactive
    payoff readout was the lone exception, so its 460-pixel minimum widened a
    390-pixel document to 484 pixels instead of scrolling inside the exhibit.
    """
    text = (SITE / "brief.html").read_text(encoding="utf-8")

    assert (
        '<div class="table-wrap pf-table-wrap"><table class="pf-outcome">'
        in text
    )


def test_brief_labels_conditional_metrics_and_reconciles_coverage():
    """Adjacent confidence metrics must not silently mix denominators.

    Overall accuracy counts abstentions while confidence and calibration are
    measured among attempted answers. The labels and bridge columns make that
    difference visible, and these two rows pin the arithmetic that prompted the
    reporting fix.
    """
    text = (SITE / "brief.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for label in (
        "overall accuracy",
        "answered",
        "accuracy when answered",
        "confidence when answered",
        "calibration error among answers",
        "confidence-calibrated score overall",
    ):
        assert label in normalized

    # Qwen3 8B answered 66 of 100 TruthfulQA items and got 49 correct.
    # Its accuracy among answers is therefore 49/66 = 74%, not the displayed
    # 49% overall accuracy. Confidence and ECE use that answered population.
    screen_row = re.search(
        r"<tr><td[^>]*>Qwen3 8B</td><td[^>]*>TruthfulQA MC1</td>.*?</tr>",
        normalized,
    )
    assert screen_row
    for value in ("49%", "66%", "74%", "92%", "20 pp"):
        assert value in screen_row.group()

    # The untuned training baseline answered 88.5% of items: 60.0% overall
    # becomes 67.8% among answers, so its confidence gap is +22, not +30.
    training_row = re.search(
        r'<tr data-key="base\|neutral".*?</tr>', normalized
    )
    assert training_row
    for value in ("60.0%", "88.5%", "67.8%", "90%", "+22 pp"):
        assert value in training_row.group()


def test_brief_claims_match_their_visible_evidence_and_model_order():
    """The main brief path must prove its headings without hidden inference.

    The prompting claim is supported by one integrated comparison. Published
    HLE rescoring is explicitly secondary and model releases within a company
    are newest first. Alignment claims lead with a multidimensional scorecard,
    not a generic benchmark-performance conclusion.
    """
    text = (SITE / "brief.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert ("The intended prompt lowers confidence error by 3.3 points; "
            "accuracy changes &minus;0.8 points") in text
    for label in (
        "test prompt",
        "median accuracy change",
        "median absolute confidence-gap change",
        "median confidence-calibrated score change",
        "cells with higher score",
        "items per model-benchmark cell",
    ):
        assert label in normalized
    assert "Formula + explanation + 30% threshold" in text
    assert "18,144 deterministically" in text
    assert "8/15" in text
    assert "13/15" in text
    assert "SimpleQA was excluded" in text
    assert "Why calibration matters: published models can change rank" in text

    hle_table = re.search(
        r'<table class="brief-hle sortable-table".*?</table>', normalized
    )
    assert hle_table
    hle = hle_table.group()
    assert hle.index("GPT-5.4") < hle.index("GPT-5.2") < hle.index("GPT-5</td>")

    screen = normalized[normalized.index("Benchmark screen, ETHICS tasks, and BBQ bias"):]
    assert screen.index("Qwen3.5 4B") < screen.index("Qwen3 8B")

    assert "Calibration training improves prudence, not alignment by itself" in text
    assert "46-point reduction in overconfident bad decisions" in normalized
    assert "The transfer stops after prudent action" in normalized
    assert "515 of 10,240 risky tool choices" in normalized
    for label in (
        "accuracy-only level",
        "confidence-calibrated matched change",
        "fixed-cost matched change",
        "exact-evidence error",
        "unauthorized reference use",
        "appropriate goal response",
    ):
        assert label in normalized
    for value in (
        "&minus;0.159",
        "&minus;46 pp",
        "&minus;17 pp",
        "+0.4 points",
        "&minus;5.6 pp",
        "&minus;7.5 pp",
        "+3.3 pp",
    ):
        assert value in text
    for label in (
        "Truthfulness",
        "Ethical-judgment agreement",
        "Social bias",
        "Constraint adherence",
        "Pressure discernment",
    ):
        assert label in normalized
    assert "accuracy change vs accuracy-only" in normalized
    assert "Held-out benchmark performance and confidence calibration remain available" in normalized
    assert "The adverse social-pressure gap remained under all four scoring prompts" in normalized
    assert "No scoring rule announced" in text
    assert "Confidence scoring + fixed cost announced" in text
    for value in ("+21 pp worse", "+26 pp worse", "+22 pp worse", "+25 pp worse"):
        assert value in text


def test_brief_training_summary_names_the_tradeoff_and_metric():
    """The compact table must expose both winners before the full matrix."""
    text = (SITE / "brief.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Training adds 0.105 to confidence-calibrated score but trails accuracy by 2 points" in text
    assert "Highest accuracy; worse confidence-calibrated score" in normalized
    assert "Highest confidence-calibrated score" in normalized
    assert "Ties the confidence-calibrated score; cost adds no gain" in normalized
    assert "Performance winner: accuracy-only training" in normalized
    assert "Calibration winner: confidence-aware training" in normalized
    assert not re.search(r"\bconfidence score", text, re.IGNORECASE)


def test_brief_plural_prudence_chain_keeps_links_and_denominators_separate():
    """The brief must show magnitudes without manufacturing alignment score."""
    text = (SITE / "brief.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "five separate behavioral links" in text
    assert "lower calibration quartile" in normalized
    assert "upper calibration quartile" in normalized
    for value in ("&minus;0.3 pp", "&minus;1.0 pp", "+2.0 pp", "+1.0 pp"):
        assert value in text
    assert "No composite alignment score was constructed" in text
    assert "79,872 responses" in normalized
    assert "0 of 10,240 choices" in normalized
    assert "0 of 515 follow-up audits" in normalized
    assert "Two of 20,480 goal decisions" in normalized
    assert "rule-of-three upper bound of about 0.03%" in normalized


def test_brief_reports_pooled_transfer_hidden_actions_and_family_gate():
    """New alignment-adjacent claims must expose magnitude and controls."""
    text = (SITE / "brief.html").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Pooled calibration cut high-confidence errors by 13 to 51 points" in text
    for value in ("&minus;13.0 pp", "&minus;41.4 pp", "&minus;51.0 pp", "+0.267"):
        assert value in text
    assert "full 198-question GPQA Diamond census" in normalized
    assert "zero training-ID overlap" in normalized

    assert "Hidden unauthorized shortcuts fell 1 point" in text
    assert "160 conflict and 160 control actions per checkpoint" in normalized
    assert "91.2% &rarr; <b>89.4%</b>" in text
    assert "100% of authorized controls" in normalized
    assert "84% to 94%" in normalized

    assert "Nemotron still failed one of two full format profiles" in text
    assert "GPT-OSS replicated factual calibration, but not hidden restraint" in text
    assert "15 of 16 seed-by-domain comparisons" in normalized
    assert "0.63%" in text
    assert "1.15%" in text
    assert "Failed 1% gate; stop" in text
    assert "$4.543019 under the $20 cap" in normalized


def test_experiment_map_centers_its_column_labels():
    text = (SITE / "training.html").read_text(encoding="utf-8")

    assert 'class="choice-table experiment-map"' in text
    assert ".experiment-map thead th { text-align: center; }" in text


def test_model_family_section_separates_promise_from_stopped_replication():
    text = (SITE / "training.html").read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    assert "Seed 0 was promising; seed 1 failed the technical gate" in normalized_text
    assert (
        "No seed-1 development responses or final-test responses were generated"
        in normalized_text
    )
    assert "Offsets 60 through 99 were reserved but never generated" in normalized_text


def test_training_page_separates_development_evidence_from_final_result():
    text = (SITE / "training.html").read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())
    parser = parse_page("training.html")

    assert parser.tune_steps == 4
    assert "The final test passed" in text
    assert "What the development replications found" in text
    assert "What the first live pilot found" in text
    assert "100-question profile" in normalized_text
    assert "The preregistered final test then generated 6,400 responses" in normalized_text
    assert "+0.105 (+0.036 to +0.175)" in normalized_text
    assert "The accuracy safeguard was a point-estimate decision rule" in normalized_text
    assert "-5.25 to +1.25 points" in normalized_text
    assert "The gain came from probabilities, not refusals" in normalized_text
    assert "All three tuned checkpoints retained 100% coverage" in normalized_text
    assert "The assertion cost added no detectable value" in normalized_text
    assert "No neutral substantive answer from any checkpoint reported a probability below either threshold" in normalized_text
    assert "two-pass cost sensitivities" in normalized_text
    assert "Complete: run the final test once" in normalized_text
    assert "Stop paid tuning here" in normalized_text
    assert "reward-scale calibration" in normalized_text
    assert "crossed checkpoint evaluator are complete" in normalized_text
    assert "development evidence from the preregistered final result" in normalized_text
    assert all(heading in text for heading in ("Accuracy", "Confidence", "Confidence + cost"))
    assert "One response, all the way from reward to weights" in text
    assert "one fixed scale factor per arm" in normalized_text
    assert "post-centering signals are the same" in normalized_text
    assert "Accentuation options and their tradeoffs" in text
    assert "Primary causal comparison" in text
    assert "Mechanism stress test" in text
    assert "The first question is calibration, not abstention" in normalized_text
    assert "Action policies can be applied after the model reports its belief" in normalized_text
    assert "minimum confidence required to answer" in normalized_text
    assert "Raw abstention frequency is not a primary endpoint" in normalized_text
    assert "There are not three different fine-tuning technologies" in normalized_text
    assert "One tuning method, three reward objectives" in text
    assert "4 checkpoints &times; 4 instructions = 16 saved responses" in text
    assert "16 responses &times; 3 formulas = 48 rule-score records" in text
    assert "but still only 16 model generations" in normalized_text
    assert "The untouched base is a fourth checkpoint, not a fourth tuning arm" in normalized_text
    assert "The evaluation instructions and scoring formulas are tests" in normalized_text
    assert "Four checkpoints by four prompt conditions" in normalized_text
    assert "Only the first two axes require generation" in normalized_text
    assert "What the accuracy-only RL baseline means" in text
    assert "It is not the default form of all fine-tuning" in normalized_text
    assert "What the four checkpoint columns mean" in text
    assert "What the four instruction rows mean" in text
    assert "One cell combines one checkpoint column" in normalized_text
    assert "No additional fine-tuning occurs in that cell" in normalized_text
    assert "code name: binary" in text
    assert "three announced-rule rows" in normalized_text
    assert "Primary: persistence with no reward announced" in text
    assert "Headline contrast" in text
    assert "Which choices could change the answer most?" in text
    assert "Dominant within the cost arm" in text
    assert "Evaluation choices and their likely leverage" in text
    assert "Two seeds do not precisely estimate between-seed variance" in normalized_text
    assert "Accuracy-only training was remarkably consistent" in normalized_text
    assert "+0.252" in normalized_text
    assert "+0.172" in normalized_text
    assert "Rare abstention remains the intended policy" in normalized_text
    assert "The weights changed, not just the prompt response" in normalized_text
    assert "final test used the untouched offsets 20 through 59" in normalized_text


@lab_only
def test_plan_routes_the_training_stage_to_the_explainer():
    text = (SITE / "plan.html").read_text(encoding="utf-8")

    assert 'href="training.html"' in text
    assert "Not started" in text
    assert "Final test passed" in text
    assert "including $0.61 final test" in text
    assert "improved the paired quadratic score by 0.105" in text


def test_validation_page_distinguishes_recorded_reconstructed_and_invalid_runs():
    text = (SITE / "validation.html").read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    assert "MiniMax M3" in text
    assert "Muse Spark 1.2" in text
    assert "Claude Haiku 4.5" in text
    assert "six current models" in normalized_text.lower()
    assert "fully recorded and five are reconstructed" in normalized_text
    assert "Invalid is not the same as a performance miss" in text
    assert "$46.21" in text
    assert "attribution gap" in normalized_text


@lab_only
def test_internal_style_guide_has_accessible_tabs_and_real_status_examples():
    text = (SITE / "style-guide.html").read_text(encoding="utf-8")
    normalized_text = " ".join(text.split())

    assert 'content="noindex, nofollow, noarchive, nosnippet"' in text
    assert 'role="tablist"' in text
    assert text.count('role="tab"') == 4
    assert all(direction in text for direction in (
        "Working guide", "Research instrument", "Scientific narrative",
        "Operator ledger"))
    assert "MiniMax M3 completed the gate" in text
    assert "Muse Spark has one unresolved API outcome" in text
    assert "Claude Haiku route connected" in text
    assert "plum for identity, curves, and selective emphasis" in normalized_text
    assert "blue for reference information; green for valid results" in normalized_text
    assert "Neither surface needs a grid of content cards" in normalized_text
    assert 'class="lab-principle"' in text
    assert 'class="lab-card"' not in text


def test_public_pages_share_the_research_instrument_color_contract():
    """The selected design must be a site system, not a one-page mockup.

    These are semantic tokens rather than a list of decorative colors. Keeping
    the names in every generated page makes it possible to verify that evidence,
    valid results, and protocol exclusions retain the same meaning everywhere.
    """
    for name in PAGES:
        text = (SITE / name).read_text(encoding="utf-8")

        assert "--plum:" in text, f"{name} lacks the curve and emphasis token"
        assert "--plum-dark:" in text, f"{name} lacks the identity token"
        assert "--evidence:" in text, f"{name} lacks the evidence token"
        assert "--valid:" in text, f"{name} lacks the valid-result token"
        assert "--invalid:" in text, f"{name} lacks the exclusion token"
        assert "#c1522a" not in text, f"{name} still carries the old terracotta accent"

    builder = _builder()
    assert "background: var(--plum-dark);" in builder.CSS
    assert "background: var(--evidence-band);" in builder.CSS
    assert ".note.invalid-note" in builder.CSS
    assert "/* @quadratic-motif" in builder.CSS
    assert "M4 52 Q340 -11 676 31" in builder.QUADRATIC_DIVIDER
    assert "vector-effect=\"non-scaling-stroke\"" in builder.QUADRATIC_DIVIDER
    assert "h2::before" not in builder.CSS
    assert "h2::after" not in builder.CSS


def test_quadratic_curve_is_the_complete_major_section_divider():
    """Every public named section gets one full curve and no appended flourish."""
    for name in PAGES:
        parser = parse_page(name)
        if name == "style-guide.html":
            # The internal lab shows one deliberate example; headings inside
            # its interface specimens are not narrative section boundaries.
            assert parser.quadratic_dividers == 1
        elif name == "why-linear-fails.html":
            # This hand-maintained interactive explainer has no named h2s.
            assert not parser.heading_ids
            assert parser.quadratic_dividers == 0
        else:
            assert parser.quadratic_dividers == len(parser.heading_ids), name

        text = (SITE / name).read_text(encoding="utf-8")
        assert "M1 14 Q44 -10 87 14" not in text
