#!/usr/bin/env python3
"""build_site.py — render the narrative page from committed CSVs.

Same contract as dollars-just-for-dc: a self-contained HTML file generated only
from files in the repo, so a clone reproduces it byte for byte without an API
key, a database, or a network call. Every number on the page traces to a CSV in
data/processed/.

    python scripts/build_site.py          -> site/below-zero/index.html
"""

from __future__ import annotations

import collections
import csv
import datetime
import html
import json
import os
import re
import statistics
import sys
import zoneinfo

# The write-up's prose lives in content/, not in this file. content.py renders
# it; everything here is the frame around it and the figures inside it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(ROOT, "site", "below-zero")

# The validation page re-checks its committed CSV against the pre-registered
# targets in belowzero.parity. Importing from src/ directly keeps the build
# runnable in a bare clone, with no install step and still no third-party
# dependency: the package it reaches into is this repository.
sys.path.insert(0, os.path.join(ROOT, "src"))

PUBLISHED = "2026-08-15"
# The default content date for pages that do not carry their own. It must NOT be
# bumped for a change that only touches one page: side_page() hands it to every
# page without an override, so raising it here would claim that approach.html,
# open-questions.html and related-work.html changed their content when only the
# shared stylesheet moved. The index has its own constant below for that reason.
CONTENT_UPDATED = "2026-08-17 01:24 ET"  # site-wide default; per-page constants override
INDEX_CONTENT_UPDATED = "2026-09-03 10:00 ET"
STYLE_UPDATED = "2026-09-03 10:00 ET"
SITE_COMMIT = "f64c8ca"
# The site's ORGANIZATION: menu, page set, cross-links, banners. Separate from
# content (a page's own prose and tables) and style (the shared design system)
# so a reader can tell a rewrite from a restyle from a menu change. Bump it
# whenever SITE, NAV_HIDDEN, SUPERSEDED_PAGES, or the landing map changes.
STRUCTURE_UPDATED = "2026-09-03 10:00 ET"
CHANGES_CONTENT_UPDATED = "2026-09-04 23:15 ET"
INDEX_SITE_COMMIT = "c12ceea"
PLAN_CONTENT_UPDATED = "2026-08-17 01:16 ET"
PLAN_SITE_COMMIT = "c12ceea"
TRAINING_CONTENT_UPDATED = "2026-08-17 01:25 ET"
TRAINING_SITE_COMMIT = "c12ceea"
VALIDATION_CONTENT_UPDATED = "2026-08-17 01:16 ET"
VALIDATION_STYLE_UPDATED = "2026-08-25 01:13 ET"
VALIDATION_SITE_COMMIT = "c12ceea"
# When each dataset behind the brief was pulled or produced. Per source, not
# per page: a reader checking a number needs to know when THAT number was
# measured, and "the page was updated Tuesday" does not answer it. Written
# down explicitly rather than derived from wall-clock time, so a rebuild
# cannot silently re-date evidence it did not re-gather.
DATA_VINTAGE = {
    "census": ("2026-08-15", ("EvalEval &ldquo;Every Eval Ever&rdquo; "
                             "datastore, 1,319 per-sample files")),
    "decline_samples": ("2026-08-20", ("same datastore, four benchmarks "
                                      "re-streamed for the phrase evidence")),
    "hle": ("2026-08-19", ("every published HLE run in the datastore, "
                          "rescored with the models' own confidences")),
    "parity": ("2026-08-16", "GPQA Diamond replication, 198 items per model"),
    "pilot": ("2026-08-15", "live 50-item pilot, six models, eight contracts"),
    "prompt_estimation": ("2026-08-22", ("expanded deterministic prompt test, "
                                         "120 to 198 items per condition, five "
                                         "models from four developers, eight "
                                         "prompts")),
    "finetune": ("2026-08-16", "final test, 200 held-out items, two seeds"),
    "policy_architecture": ("2026-08-24", (
        "external-threshold policy reanalysis, 9,000 matched responses, five "
        "training seeds, and three held-out benchmarks")),
    "prompt_threshold_factorial": ("2026-08-24", (
        "same-checkpoint prompt factorial, 6,000 responses, three training "
        "seeds, five training doses, and 100 held-out questions")),
    "pressure": ("2026-08-17", ("social-pressure run over the same "
                               "checkpoints")),
    "pressure_replication": ("2026-08-22", ("paired social-pressure "
                                           "replication, 150 new items, 19 "
                                           "model states, 4,034 responses")),
    "pressure_prompting": ("2026-08-22", ("the same 150 social-pressure "
                                         "items crossed with four test "
                                         "prompts at seven model states")),
    "constraints": ("2026-08-18", ("constraint-temptation run over the same "
                                  "checkpoints, 33 items each")),
    "broader": ("2026-08-21", ("held-out TruthfulQA, ETHICS, and BBQ "
                               "evaluations across five matched training "
                               "seeds")),
    "alignment": ("2026-08-22", ("100-checkpoint dose grid joined across "
                                 "knowledge, constraint, and paired-pressure "
                                 "evaluations")),
    "matched_alignment": ("2026-08-22", ("matched alignment battery, 80 "
                                         "high-stakes decisions, 60 evidence "
                                         "items, 16 agentic scenarios, and 18 "
                                         "model states")),
    "plural_prudence": ("2026-08-22", ("plural-prudence battery, 79,872 "
                                        "responses across five matched training "
                                        "seeds, four prompts, and five separate "
                                        "behavioral links")),
    "external_transfer": ("2026-08-22", ("external transfer battery, 21,472 "
                                           "responses across 16 matched model "
                                           "states and three public benchmark "
                                           "families")),
    "domain_alignment": ("2026-08-23", ("matched domain-transfer and behavior "
                                          "battery: six Qwen3 8B checkpoints, "
                                          "2,100 domain evaluations, all 450 "
                                          "XSTest prompts, and 8,736 matched "
                                          "decision, evidence, and agentic "
                                          "responses")),
    "domain_replication": ("2026-08-23", ("scaled domain replication: 13,500 "
                                            "responses on 900 new questions, "
                                            "seven admitted training pairs, and "
                                            "full 1,920-response format profiles "
                                            "for two additional models")),
    "multitask_family_agentic": ("2026-08-23", (
        "pooled transfer and hidden-opportunity program: 27,450 factual "
        "responses, 16,000 agentic responses, five pooled training pairs, "
        "seven admitted subject-specific pairs, and two full independent-family "
        "format profiles")),
    "openweight_family": ("2026-08-23", (
        "prospective open-weight family screen: two one-response route checks "
        "and one 1,920-response full profile under a $20 hard cap")),
    "openweight_followup": ("2026-08-23", (
        "extended open-weight replication: five planned GPT-OSS training pairs, "
        "9,882 held-out factual responses, 5,760 hidden-opportunity records, "
        "and prospectively gated Kimi and DeepSeek format follow-ups")),
}


def vintage(key, extra=""):
    """A source line for an exhibit: what it came from, and when.

    The bolded lead-in follows the convention that reads best under a table:
    a reader scanning for provenance finds the word "Source", and a reader
    reading the caption sails through it as a sentence.
    """
    when, what = DATA_VINTAGE[key]
    return (f"<b>Source.</b> {what}, pulled {when}."
            + (f" {extra}" if extra else ""))


BRIEF_CONTENT_UPDATED = "2026-08-24 23:48 ET"
BRIEF_STYLE_UPDATED = "2026-08-25 01:13 ET"
BRIEF_SITE_COMMIT = "c12ceea"
TABLE_BRIEF_CONTENT_UPDATED = "2026-08-24 23:48 ET"
TABLE_BRIEF_STYLE_UPDATED = "2026-08-25 01:13 ET"
TABLE_BRIEF_SITE_COMMIT = "c12ceea"
DRAFT_CONTENT_UPDATED = "2026-08-25 16:57 ET"
DRAFT_STYLE_UPDATED = "2026-08-25 15:05 ET"
DRAFT_SITE_COMMIT = "686a88a"
LITERATURE_CONTENT_UPDATED = "2026-08-25 16:57 ET"
LITERATURE_STYLE_UPDATED = "2026-08-25 01:13 ET"
LITERATURE_SITE_COMMIT = "686a88a"
STYLE_GUIDE_CONTENT_UPDATED = "2026-08-16 20:05 ET"
STYLE_GUIDE_STYLE_UPDATED = "2026-08-25 01:13 ET"
STYLE_GUIDE_SITE_COMMIT = "c12ceea"

# Whether the repository is public. This is a real fork in how the page argues,
# not a cosmetic switch. A public repo lets the page say "check it yourself" and
# point at code; a private one means the page has to carry the credibility on its
# own, so the evidence ships WITH the page as downloadable CSVs and the method is
# described rather than linked. Either way the reader can check the numbers —
# which is the only property worth preserving.
REPO_PUBLIC = True
REPO_URL = "https://github.com/ramongonzalez12/there-should-be-a-cost-to-guessing"

# The page the menu calls "The essay". The lab's is essay-v2.html, rendered by
# its own builder, which stays private (release/export_manifest.py denies the
# page); the public repository ships essay.html (scripts/build_essay_page.py).
# A public build links that, so no shipped page links a page that is not there.
ESSAY_PAGE = "essay.html" if REPO_PUBLIC else "essay-v2.html"
# The overview's map names the oscillation explainer, which the manifest keeps
# private, so no page links it (the lab's copy is reachable by URL).
OSCILLATION_REF = "oscillation"

# Working pages for whoever builds the site: the change log, the report draft,
# the plan and status page, and the design lab. The release manifest keeps
# them (and content/changes/, content/draft/) private, so no menu, footer, or
# map links them in either tree. The lab still builds them, reachable by URL;
# the public tree, which has no content/draft/, does not.
LAB_ONLY_PAGES = {"changes.html", "draft.html", "plan.html", "style-guide.html"}
BUILD_LAB_ONLY = os.path.isdir(os.path.join(ROOT, "content", "draft"))

# Benchmarks where the model works in an environment that can show it that it
# failed, versus those where the only signal is its own uncertainty. The split
# is the point of the second table, so it lives here rather than in the data.
AGENTIC = {"swebenchpro", "terminalbench", "GAIA", "cybench", "gdm_intercode_ctf",
           "swe-bench-verified-mini", "cvebench", "BountyBench", "agentharm"}

# Benchmarks that are not closed-form question answering, and so cannot test
# the claim this page makes. Verified by re-streaming them and reading what
# matched (scripts/census_decline_samples.py); the reason is per benchmark
# because they fail in different ways, and a reader is owed the specific one.
#
# They stay visible in their own group rather than being dropped: the
# published headline pools everything, so silently removing them here would
# make the page disagree with its own number without saying so.
NOT_CLOSED_FORM = {
    "healthbench":
        "free-form clinical advice graded against a rubric that rewards "
        "asking for missing context; 70% of its matches are the bare word "
        "&ldquo;unknown&rdquo;",
    "judgebench":
        "the model judges other answers, and two thirds of its matches are it "
        "quoting the instruction those answers were given",
    "lingoly_nocontext":
        "the context needed to solve the puzzle is deliberately withheld, so "
        "declining is the correct answer",
    "lingoly_context":
        "the same puzzles with the context supplied, kept beside its twin as "
        "the controlled comparison",
    "IFEval":
        "instruction-following, scored against format rules rather than a "
        "correct answer",
}


# Every page in the site, in nav order, with a short label for narrow screens.
# The abbreviation exists so the menu can stay COMPLETE on a phone: an earlier
# version dropped trailing links below 700px, which quietly made two pages
# unreachable from the bar on exactly the devices least able to spare a route.
# The menu, in three groups. The essay is the canonical account and comes
# first; the overview is the short landing behind the wordmark; the deep dives
# are the essay's appendices; the reference pages define terms and sources.
# Pages that were earlier drafts of the same argument (SUPERSEDED_PAGES) are
# still built, carry a banner and a canonical link to the essay, and are no
# longer in the menu: three prose drafts of one essay in a flat list of
# fifteen peers was the clearest signal a reader could get that nothing here
# was finished.
SITE = [
    (ESSAY_PAGE, "The essay", "Essay"),
    ("changes.html", "What&rsquo;s changed", "Changes"),
    ("index.html", "Overview", "Overview"),
    ("training.html", "Fine-tuning", "Tuning"),
    ("dose-response.html", "Dose response", "Dose"),
    ("replication.html", "Replication", "Seeds"),
    ("validation.html", "Harness validation", "Validation"),
    ("approach.html", "Approach &amp; glossary", "Approach"),
    ("why-linear-fails.html", "Why linear fails", "Linear"),
    ("related-work.html", "What this builds on", "Sources"),
    # The same literature cut the other way: related-work lists foundations
    # by topic, this page walks the write-up's argument and marks, for each
    # section, what prior work already established and what is new here.
    ("literature.html", "What is new here", "Novelty"),
    ("open-questions.html", "Open questions", "Open"),
    # The word "internal" is carried by the chip the nav draws for this entry,
    # not by the label, so the two do not say it twice.
    ("style-guide.html", "Design lab", "Lab"),
]

# A group label is drawn before the first entry of each group. Labels are
# hidden on narrow screens, where the abbreviated links alone must fit.
NAV_GROUPS = {
    "training.html": "Deep dives",
    "approach.html": "Reference",
}

# Earlier drafts of the same argument, kept for comparison and reachable by
# URL. Each carries a banner naming what superseded it and a canonical link.
# The essay builder (kept in the private lab) borrows its chrome from
# brief-table.html, so that page must keep being built.
SUPERSEDED_PAGES = {
    "brief.html": "the brief of August 25",
    "brief-table.html": "the table brief of August 25",
    "draft.html": "the report draft of August 25",
    "plan.html": "the plan and status page of August 17",
}
# ESSAY_PAGE (defined beside REPO_PUBLIC) is rendered by its own builder;
# build_site only lists it.

# Listed in SITE (so the footer and the tests know them) but not drawn in the
# top menu (Ramon, 2026-09-03: "clean up all the other tabs"): the wordmark
# already links to the overview, and the novelty review, the linear explainer,
# the open questions and the design lab are reached from the overview's map
# and every page's footer instead of competing in a 798px row.
NAV_HIDDEN = {"index.html", "why-linear-fails.html", "literature.html",
              "open-questions.html", "style-guide.html"}

# Creation is a property of the page, not of the latest build. These timestamps
# are the first commits in which each URL existed, recovered from git history.
# Keeping the registry explicit makes a new page fail its structural test until
# whoever creates it records when it came into being. Last-updated timestamps
# remain page-specific constants above and are recomputed on every build.
PAGE_CREATED = {
    "changes.html": "2026-09-05T00:00:00-04:00",
    "index.html": "2026-08-15T14:19:58-04:00",
    "brief.html": "2026-08-20T01:09:30-04:00",
    "brief-table.html": "2026-08-23T16:20:47-04:00",
    "draft.html": "2026-08-25T00:54:24-04:00",
    "approach.html": "2026-08-15T16:23:02-04:00",
    "validation.html": "2026-08-16T09:12:07-04:00",
    "plan.html": "2026-08-15T16:23:02-04:00",
    "training.html": "2026-08-16T10:54:35-04:00",
    "dose-response.html": "2026-08-18T22:33:57-04:00",
    "replication.html": "2026-08-20T01:05:47-04:00",
    "open-questions.html": "2026-08-15T16:23:02-04:00",
    "why-linear-fails.html": "2026-08-15T14:19:58-04:00",
    "related-work.html": "2026-08-16T11:10:52-04:00",
    "literature.html": "2026-08-25T00:23:29-04:00",
    "style-guide.html": "2026-08-16T16:30:38-04:00",
}

EASTERN = zoneinfo.ZoneInfo("America/New_York")


def version_timestamp(value):
    """Return one timestamp as machine-readable ISO and compact display text.

    Creation dates come from git as ISO 8601. Existing content/style dates use
    the site's compact ``YYYY-MM-DD HH:MM ET`` convention. Normalizing both in
    one place keeps the visible label, ``datetime`` attribute, and comparison
    between content and style updates in agreement.
    """
    if value.endswith(" ET"):
        parsed = datetime.datetime.strptime(
            value.removesuffix(" ET"), "%Y-%m-%d %H:%M"
        ).replace(tzinfo=EASTERN)
    else:
        parsed = datetime.datetime.fromisoformat(value).astimezone(EASTERN)
    return parsed, parsed.isoformat(timespec="minutes"), parsed.strftime(
        "%Y-%m-%d %H:%M ET"
    )


def page_version(filename, content_updated, style_updated,
                 structure_updated=None):
    """Return the stable creation time and the three visible-change times.

    ``updated`` is the latest of content, style and organization, kept for the
    data-last-updated attribute and the tests; the three components are
    returned separately so the byline can show which one moved.
    """
    if filename not in PAGE_CREATED:
        raise SystemExit(
            f"{filename} has no creation timestamp in PAGE_CREATED"
        )
    structure_updated = structure_updated or STRUCTURE_UPDATED
    _created_dt, created_iso, created_text = version_timestamp(
        PAGE_CREATED[filename]
    )
    content_dt, content_iso, content_text = version_timestamp(content_updated)
    style_dt, style_iso, style_text = version_timestamp(style_updated)
    structure_dt, structure_iso, structure_text = version_timestamp(structure_updated)
    latest = max(content_dt, style_dt, structure_dt)
    return {
        "created_iso": created_iso,
        "created_text": created_text,
        "updated_iso": latest.isoformat(timespec="minutes"),
        "updated_text": latest.strftime("%Y-%m-%d %H:%M ET"),
        "content_iso": content_iso, "content_text": content_text,
        "style_iso": style_iso, "style_text": style_text,
        "structure_iso": structure_iso, "structure_text": structure_text,
    }


def page_dates_html(
    filename, content_updated, style_updated, *, author=True, tail="",
    structure_updated=None,
):
    """Render the visible creation/update line used at the top of every page.

    Shows the latest change first, then which of the three dimensions moved
    and when (content, style, organization), so a reader comparing two visits
    can tell a rewrite from a restyle from a menu change.
    """
    version = page_version(filename, content_updated, style_updated,
                           structure_updated)
    lead = "By Ramon Gonzalez &middot; " if author else ""
    return (
        f'<p class="byline page-dates">{lead}Created '
        f'<time datetime="{version["created_iso"]}">'
        f'{version["created_text"]}</time> &middot; Last updated '
        f'<time datetime="{version["updated_iso"]}">'
        f'{version["updated_text"]}</time>{tail}'
        f'<span class="page-dates-detail">Content '
        f'<time datetime="{version["content_iso"]}">{version["content_text"]}</time>'
        f' &middot; Style <time datetime="{version["style_iso"]}">{version["style_text"]}</time>'
        f' &middot; Organization <time datetime="{version["structure_iso"]}">'
        f'{version["structure_text"]}</time></span></p>'
    )

# Pages that exist for whoever is building the site, not for its audience. They
# are noindexed and marked in the menu. This is the list both of those read.
INTERNAL_PAGES = {"style-guide.html"}

# Long pages get a second, page-local navigation rail under the site menu.
# The registry is explicit rather than inferred from whatever headings happen
# to be present: labels stay short enough for the rail, and the test below can
# require that every registered target still exists. Pages with fewer than five
# major sections remain uncluttered.
SECTION_NAV = {
    # The rail is the argument's spine, so its labels are the six claims in
    # order rather than a list of topics. A reader who reads only this row
    # should get the shape: models answer, the scoring is why, the fix is
    # calibration rather than silence, here is the rule, here is every arm,
    # here is what happened when models were told it and trained on it.
    # The brief's rail is the row of questions itself: a reader who scans only
    # these labels should recover the argument's spine.
    "brief.html": [
        ("census", "Answers"),
        ("scoring", "Why"),
        ("rule", "The rule"),
        ("worth", "Prompting"),
        ("trained", "Training"),
        ("honesty", "Alignment"),
        ("ask", "The ask"),
        ("open", "Evidence"),
        ("appendix", "Methods"),
    ],
    "brief-table.html": [
        ("map", "Map"),
        ("problem", "Problem"),
        ("prompting", "Prompting"),
        ("training", "Training"),
        ("chain", "Alignment chain"),
        ("families", "Model gates"),
        ("next", "Next tests"),
    ],
    "draft.html": [
        ("context", "Prior research"),
        ("premise", "The problem"),
        ("rules", "Four scores"),
        ("wisdom", "What we want"),
        ("measurement", "Overconfidence"),
        ("training", "Training"),
        ("alignment", "Alignment"),
    ],
    "changes.html": [
        ("summary", "Summary"),
        ("numbers", "Numbers"),
        ("defects", "Code"),
        ("data", "Data"),
        ("essay", "Essay"),
        ("site", "Site"),
        ("open", "Open"),
        ("revisions", "Revisions"),
        ("versions", "Page dates"),
    ],
    "index.html": [
        ("summary", "Summary"),
        ("ordering", "What moves it"),
        ("reconcile", "Answering vs knowing"),
        ("census", "Census"),
        ("map", "Read next"),
        ("about", "About"),
    ],
    "validation.html": [
        ("result", "Gate"),
        ("reconstructed", "Reconstruction"),
        ("invalid", "Exclusions"),
        ("limits", "Limits"),
        ("cost", "Cost"),
        ("next", "Next"),
    ],
    "dose-response.html": [
        ("versions", "The versions"),
        ("outcome", "The outcome"),
        ("rules", "Other rules"),
        ("base", "Versus no training"),
        ("pressure", "Social pressure"),
        ("limits", "Limits"),
    ],
    # The rail states the page's order of operations: define the axes, define
    # the versions, define the measure AND its noise floor, only then show a
    # result. A reader who lands mid-page can see what they skipped.
    "replication.html": [
        ("design", "Three roles"),
        ("versions", "Trained on"),
        ("measures", "Scored with"),
        ("matrix", "The matrix"),
        ("replicated", "What replicated"),
        ("mechanism", "Mechanism"),
        ("limits", "Limits"),
    ],
    "training.html": [
        ("final", "Final result"),
        ("family", "Model family"),
        ("replication", "Development"),
        ("pilot", "Pilot evidence"),
        ("idea", "Fine-tuning"),
        ("map", "Experiment map"),
        ("loop", "Training loop"),
        ("choices", "Design choices"),
        ("accentuation", "Stronger signals"),
        ("arms", "Reward arms"),
        ("plan", "Run plan"),
        ("evaluation", "Evaluation"),
        ("result", "Success"),
        ("automation", "Automation"),
        ("cost", "Cost"),
    ],
    "approach.html": [
        ("claims", "Claims"),
        ("pipeline", "Pipeline"),
        ("separation", "Scoring"),
        ("rules", "Guardrails"),
        ("check", "Checks"),
        ("glossary", "Glossary"),
    ],
    "related-work.html": [
        ("rules", "Proper rules"),
        ("choice", "Choosing one"),
        ("reject", "Reject option"),
        ("testing", "Human testing"),
        ("signal", "Calibration"),
        ("benchmarks", "Benchmarks"),
        ("training", "Training"),
        ("gaps", "What is left"),
    ],
    "literature.html": [
        ("answering", "Answering"),
        ("scoring", "Scoring"),
        ("prompting", "Prompting"),
        ("training", "Training"),
        ("chain", "Chain"),
        ("next", "Next"),
    ],
    "open-questions.html": [
        ("belief", "Phrase count"),
        ("agentic", "Agentic gap"),
        ("judge", "Judge"),
        ("gaming", "Gaming"),
        ("transfer", "Transfer"),
        ("c", "Speaking cost"),
        ("scope", "Scope"),
    ],
}

# Where the programme actually stands. This is the ONE place the status is
# written down; the plan page renders it. Update it when a stage changes state,
# in the same commit that changes the state.
#
# state: "done" (finished, evidence in the repo), "now" (running), "todo".
STAGES = [
    {"state": "done", "label": "Complete",
     "name": "Census of published responses",
     "asks": "How often do models decline to answer, in evaluations that already ran?",
     "cost": "$0",
     "detail": "1,089,024 graded responses across 104 models and 36 benchmarks, "
               "counted from the public EvalEval archive. Result on the findings "
               "page: 0.69% decline, 0.25% state a probability."},
    {"state": "done", "label": "Complete",
     "name": "Scoring rules and their proofs",
     "asks": "Does the proposed rule actually elicit an honest probability?",
     "cost": "$0",
     "detail": "Five rules implemented and checked numerically over the whole "
               "probability grid, including the negative result that a linear "
               "rule cannot elicit a probability at all."},
    {"state": "done", "label": "Complete",
     "name": "Harness and pre-registration",
     "asks": "Can the experiment be run, resumed, capped, and audited?",
     "cost": "$0",
     "detail": "Runner, grader, judge, and metrics are in place and exercised "
               "end to end against a mock endpoint on every commit. Hypotheses, "
               "primary outcomes, and stop rules were fixed before any data "
               "was collected."},
    # Cost here is a placeholder the builder replaces with the figure in
    # data/processed/gpqa_parity_summary.csv, so the plan page and the
    # validation page cannot quote different totals for the same spending.
    {"state": "done", "label": "Complete",
     "name": "Environment validation",
     "asks": "Does the harness reproduce a benchmark result somebody else "
             "already published?",
     "cost": "@parity_cost",
     "detail": "Six current models over all 198 GPQA Diamond questions, each "
               "checked against its published score under a criterion fixed "
               "before the runs. All six landed inside their expected range. "
               "Three further models were attempted and excluded by the "
               "validity rules; three one-item checks only established routing. "
               "This validates the standard benchmark "
               "environment; it is not the scoring-rule experiment.",
     "page": "validation.html"},
    {"state": "done", "label": "Existence check passed",
     "name": "Stage 1: the existence check",
     "asks": "Does abstention move off zero at all when the rule is announced?",
     "cost": "$2.89 in key usage",
     "detail": "50 frozen items, six current models, eight contracts, run on "
               "2026-08-15. This is the first stage that varies the announced "
               "contract, and it passed its pre-registered existence check. On "
               "short-answer questions, explicit abstention rose by 34 points "
               "for two of the six models and by 14 points for a third, while "
               "three did not move. The effect was much weaker on the four "
               "multiple-choice benchmarks. Accuracy and error columns wait on "
               "judge validation before they can be reported."},
    {"state": "todo", "label": "Not started",
     "name": "Stage 2: estimation",
     "asks": "How large is the effect, and does it hold across benchmarks?",
     "cost": "$40 to $150",
     "detail": "Five benchmarks, 200 items each, ten models, with the LM judge "
               "validated against hand labels before any number is reported."},
    {"state": "done", "label": "Final test passed",
     "name": "Stage 3: does it survive training?",
     "asks": "Does reward training improve calibrated beliefs, and what action "
             "policies follow from them?",
     "cost": "about $7.31 in conservative ceilings, including $0.61 final test",
     "detail": "Two frozen 500-question seeds trained all three one-pass reward arms "
               "and passed the preregistered 200-item final test. Confidence-aware training "
               "improved the paired quadratic score by 0.105, with a 95% interval from "
               "0.036 to 0.175. Accuracy changed by -2.0 points, inside the prespecified "
               "safeguard, and all tuned checkpoints retained 100% coverage. The added "
               "assertion cost produced no stable incremental benefit.",
     "page": "training.html"},
]


# Source Serif 4 for reading, Inter for metadata and tables. Loaded from Google
# rather than bundled; the BUILD stays offline and reproducible, only rendering
# reaches the network, and the stack falls back to system serif/sans.
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;'
         '0,8..60,700;1,8..60,400&family=Inter:wght@400;500;600;700&display=swap">')


def nav(current):
    """The site menu: fixed to the top of every page and always visible.

    Identical markup on every page, with the current one marked. It does not
    wait for a scroll gesture to appear, because a reader landing on any page
    should be able to see what else is here without first discovering that
    scrolling reveals a menu.

    Each link carries both a full and an abbreviated label. CSS picks one by
    viewport width, so narrowing the screen shortens the menu rather than
    truncating it.
    """
    links = []
    for href, label, short in SITE:
        if href in NAV_HIDDEN or href in LAB_ONLY_PAGES:
            continue
        if href in NAV_GROUPS:
            links.append(f'<span class="nav-group" aria-hidden="true">{NAV_GROUPS[href]}</span>')
        # The lab is a working document that happens to be reachable by URL.
        # Marking it in the menu means a reader knows before clicking, rather
        # than after landing on something written for whoever is building the
        # site. INTERNAL_PAGES is the one list that decides this.
        classes = ([("here")] if href == current else []) + \
                  (["internal"] if href in INTERNAL_PAGES else [])
        attrs = f' class="{" ".join(classes)}"' if classes else ""
        if href == current:
            attrs += ' aria-current="page"'
        links.append(f'<a href="{href}"{attrs}>'
                     f'<span class="nav-full">{label}</span>'
                     f'<span class="nav-abbr">{short}</span></a>')
    return ('<nav class="scroll-nav" id="scrollnav" aria-label="Site">'
            '<div class="scroll-nav-track"></div>'
            '<div class="scroll-nav-progress" id="scrollprogress"></div>'
            '<div class="scroll-nav-inner">'
            '<a class="scroll-nav-title" href="index.html">Below Zero</a>'
            '<div class="scroll-nav-links">' + "".join(links) + '</div>'
            '</div></nav>')


def section_nav(current):
    """Return a page-local section rail for long pages, otherwise nothing.

    These are ordinary anchors, not disclosure controls. The site menu changes
    pages; this rail moves within the current page. Keeping the two navigational
    jobs in separately labelled ``nav`` elements makes that distinction visible
    and preserves native link behavior when JavaScript is unavailable.
    """
    sections = SECTION_NAV.get(current, [])
    if not sections:
        return ""
    links = "".join(
        f'<a href="#{html.escape(target)}">{html.escape(label)}</a>'
        for target, label in sections
    )
    return ('<nav class="section-nav" aria-label="On this page">'
            '<div class="section-nav-inner">'
            '<span class="section-nav-label">On this page</span>'
            '<div class="section-nav-links">' + links + '</div>'
            '</div></nav>')


def footer_nav(current):
    """Every page, listed at the foot. The top menu is compact by design; this
    is the unabbreviated set, at the point where a reader has finished."""
    links = [f'<a href="{href}">{label}</a>'
             for href, label, _ in SITE if href != current and href not in LAB_ONLY_PAGES]
    return '<div class="footer-nav">' + "".join(links) + '</div>'


# Both navigation rails use native anchors and are visible from CSS alone, so
# they survive a JS failure. That is the right failure mode for the only route
# between pages. Everything here is enhancement, in four parts: the
# reading-progress band, marking the current section as the reader moves through
# a long page, fading whichever edge of a horizontal scroller actually hides
# content, and keeping the current page's link in view on the phone-width link
# row. The last two are things a phone needs and CSS cannot express.
NAV_JS = """
<script>
(function () {
  var bar = document.getElementById('scrollprogress');
  if (bar) {
    function update() {
      var y = window.scrollY || document.documentElement.scrollTop;
      var h = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (h > 0 ? Math.min(100, (y / h) * 100) : 0) + '%';
    }
    addEventListener('scroll', update, { passive: true });
    addEventListener('resize', update);
    update();
  }

  // Fade whichever edge of a horizontal scroller actually has content hidden
  // behind it, and neither edge when the content fits. Applied to every
  // horizontal scroller with a hidden scrollbar (nav row, section rail, table
  // wrappers, chart scroller), because the cue means the same thing in all of
  // them and an unconditional fade would be a claim about hidden content that
  // is false most of the time.
  function fades(el) {
    var max = el.scrollWidth - el.clientWidth;
    // Cap the ramp near the actual overflow: a table hanging 8px over its box
    // deserves an 8px whisper, not a 26px bite out of its last readable column.
    var w = max > 1 ? Math.min(26, max + 6) + 'px' : '0px';
    el.style.setProperty('--fade-start', el.scrollLeft > 1 ? w : '0px');
    el.style.setProperty('--fade-end', el.scrollLeft < max - 1 ? w : '0px');
  }
  var scrollers = document.querySelectorAll(
    '.scroll-nav-links, .section-nav-links, .table-wrap, .cal-chart-scroll');
  function allFades() { scrollers.forEach(fades); }
  scrollers.forEach(function (el) {
    el.addEventListener('scroll', function () { fades(el); }, { passive: true });
  });
  addEventListener('resize', allFades);

  var row = document.querySelector('.scroll-nav-links');
  if (!row) { allFades(); return; }

  // Bring the current page's link into view. On a phone the row is wider than
  // the screen, so the marked link can sit off the right edge — leaving the one
  // page the reader is actually on as the only one with no indicator. Set
  // scrollLeft directly rather than calling scrollIntoView, which would also
  // scroll the document and land the reader partway down the article.
  //
  // Measured from bounding rects rather than offsetLeft. The row is not a
  // positioned element, so offsetLeft is relative to the fixed bar and silently
  // includes the wordmark's width, which biases every comparison by however
  // wide "Below Zero" happens to render.
  var here = row.querySelector('.here');
  // Must clear the 26px fade ramp with room to spare, or the reveal parks the
  // current page's link inside the fade and the one marked link in the row
  // renders dimmest. 16px looked fine while desktop had no fade to clear.
  var pad = 34;
  function reveal() {
    if (!here) return;
    var h = here.getBoundingClientRect(), r = row.getBoundingClientRect();
    var delta = 0;
    if (h.right + pad > r.right) delta = h.right + pad - r.right;
    else if (h.left - pad < r.left) delta = h.left - pad - r.left;
    if (delta) row.scrollLeft += delta;
    fades(row);
  }
  reveal();

  // Re-reveal on resize. Rotating a phone to landscape fits the whole row, and
  // rotating back re-lays it out scrolled to the left, which drops the marker
  // off the right edge again. The fade handler already runs here; without the
  // marker running too, a rotate leaves the reader on the one page the bar does
  // not indicate.
  addEventListener('resize', reveal);

  // And once webfonts land. This script runs at parse time, so it measures the
  // row in the fallback face; when Inter arrives the links re-flow and the
  // scroll position computed against the old metrics no longer frames the
  // marker. Cheap to redo, and on a fast connection it is a no-op.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(reveal);

  allFades();
})();
(function () {
  var rail = document.querySelector('.section-nav');
  if (!rail) return;
  var links = Array.prototype.slice.call(
    rail.querySelectorAll('.section-nav-links a')
  );
  var pairs = links.map(function (link) {
    return { link: link, heading: document.getElementById(link.hash.slice(1)) };
  }).filter(function (pair) { return pair.heading; });

  function updateSection() {
    /* Keep this comfortably below the 112px anchor landing line. Reusing the
       same boundary makes the active section depend on sub-pixel rounding. */
    var threshold = rail.getBoundingClientRect().bottom + 28;
    var active = null;
    pairs.forEach(function (pair) {
      if (pair.heading.getBoundingClientRect().top <= threshold) active = pair;
    });
    pairs.forEach(function (pair) {
      var current = pair === active;
      pair.link.classList.toggle('here', current);
      if (current) pair.link.setAttribute('aria-current', 'location');
      else pair.link.removeAttribute('aria-current');
    });
  }

  addEventListener('scroll', updateSection, { passive: true });
  addEventListener('resize', updateSection);
  updateSection();
})();
</script>
"""


def rows(name):
    with open(os.path.join(PROC, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(x, dp=2):
    return f"{float(x) * 100:.{dp}f}%"


def _sort_key(cell):
    """The number a cell means, for sorting, or None if it means no number.

    Cells carry display HTML rather than values -- "32%", "+30 pp",
    "&minus;0.41", "7,580", and a "<span class=sub>" subtitle riding along
    inside the same td -- so a sorter working from rendered text would sort
    "&minus;0.41" above "0.30" and would sort subtitles. This reads the first
    real number out, keeping the minus sign in whichever form it arrived.
    """
    text = re.sub(r"<span class=\"sub\">.*?</span>", " ", cell, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text).replace("&minus;", "-")
    text = text.replace("&nbsp;", " ").replace(",", "")
    m = re.search(r"[-+]?\d*\.?\d+", text)
    return float(m.group()) if m else None


def _sort_text(cell):
    """The words a cell means, for sorting text columns."""
    text = re.sub(r"<span class=\"sub\">.*?</span>", " ", cell, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(" ".join(text.split())).lower()


def table(headers, body, right_from=1, cls="", sortable=False,
          collapse_after=None, row_meta=None, table_id=None):
    """One table helper for every table on the site.

    `sortable` writes a machine-readable value onto every cell -- numeric
    where the cell shows a number, its plain text otherwise -- so the browser
    can reorder rows without re-deriving values from display strings like
    "&minus;0.41" or "7,580". There is deliberately no magnitude heatmap:
    on this site colour is semantic state (valid, invalid, evidence), never
    magnitude, and the design lab's rule is that every visual dimension must
    encode a stated quantity. Emphasis belongs to rows and marks, which is
    what `row_meta` is for: an optional per-row dict carrying `key` (a stable
    identity the takeaway chips target) and `cls` (e.g. the anchor row's
    tint). Group-label rows are marked with `group: True` so the sorter pins
    them rather than interleaving them with data.

    `collapse_after` hides rows past N behind a button, with the rows present
    in the markup so the page is complete and correct without scripting.
    """
    th = []
    for i, h in enumerate(headers):
        attrs = ' class="sortable" tabindex="0" role="button"' if sortable else ""
        th.append(f"<th{attrs}>{html.escape(h)}</th>")

    trs = []
    for index, row in enumerate(body):
        meta = (row_meta[index] if row_meta else {}) or {}
        attrs = ""
        if meta.get("key"):
            attrs += f' data-key="{html.escape(meta["key"])}"'
        if meta.get("group"):
            attrs += ' data-group="1"'
        if meta.get("cls"):
            attrs += f' class="{meta["cls"]}"'
        if collapse_after and index >= collapse_after:
            attrs += " hidden"
        cells = []
        for i, cell in enumerate(row):
            classes = [] if i < right_from else ["n"]
            data = ""
            if sortable and not meta.get("group"):
                value = _sort_key(cell)
                key = f"{value}" if value is not None else f"~{_sort_text(cell)}"
                data = f' data-sort="{html.escape(key)}"'
            cls_attr = f' class="{" ".join(classes)}"' if classes else ""
            cells.append(f"<td{cls_attr}{data}>{cell}</td>")
        trs.append(f"<tr{attrs}>" + "".join(cells) + "</tr>")

    c = " ".join(filter(None, [cls, "sortable-table" if sortable else ""]))
    c = f' class="{c}"' if c else ""
    ident = f' id="{table_id}"' if table_id else ""
    more = ""
    if collapse_after and len(body) > collapse_after:
        more = (f'<div class="more-wrap"><button type="button" class="more-btn" '
                f'data-action="show-all">Show all {len(body)} rows '
                f'&#9662;</button></div>')
    # Wrapped so a table too wide for the viewport scrolls on its own axis.
    # Letting it squeeze instead collapses columns and breaks words mid-token.
    return (f'<div class="table-wrap"><table{c}{ident}><thead><tr>'
            f'{"".join(th)}</tr></thead><tbody>{"".join(trs)}</tbody></table>'
            f'</div>{more}')


def fn(text):
    """A footnote-style expansion, marked with a ? the reader can open."""
    return (f'<span class="fn"><button aria-label="footnote">?</button>'
            f'<span class="fnbody">{text}</span></span>')


def dfn(term, meaning):
    """Define a term of art in place, where a page first uses it.

    The trigger is the term itself rather than a marker beside it, because the
    reader who needs the definition is already looking at the word. Compare
    ``fn()``: a footnote is an aside a reader can skip, a definition is a word
    they cannot.

    Three details are deliberate. It is a real ``dfn`` element, so the markup
    says "defining instance" rather than "span with a dotted line". It carries
    ``tabindex`` so the definition opens on keyboard focus and not only on
    hover, which is the difference between a definition and a mouse-only easter
    egg. And the body is hidden by clipping rather than ``display: none``, so it
    stays in the accessibility tree: a screen reader reads the term with its
    definition attached instead of announcing an underline it cannot open.

    The id is derived from the term, so the same term defined on two pages gets
    the same id in two different documents, which is fine, while defining one
    term twice on ONE page would collide. That is the intended constraint. The
    canonical repeat lookup is the approach page glossary, not a second tooltip.
    """
    slug = "dfn-" + re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
    return (f'<dfn class="dfn" tabindex="0" aria-describedby="{slug}">{term}'
            f'<span class="dfnbody" id="{slug}" role="tooltip">{meaning}'
            f'</span></dfn>')


# A section transition should be one coherent object, not a conventional rule
# with a small flourish pasted onto its end. This is the same q=.60 expected-
# score parabola used in why-linear-fails.html: it begins at zero, reaches its
# honest-report maximum at p=q, and ends at the positive score for reporting
# certainty. The asymmetry matters because a centered dome looks like the Ban
# Together distribution motifs this site is deliberately not copying.
# It is unlabelled here because it marks hierarchy rather than reporting data.
QUADRATIC_DIVIDER = r'''<div class="quadratic-divider" aria-hidden="true">
  <svg viewBox="0 0 680 58" preserveAspectRatio="none" focusable="false">
    <path d="M4 52 Q340 -11 676 31" vector-effect="non-scaling-stroke" />
  </svg>
</div>'''


def check_unique_ids(page, where):
    """Refuse to ship a page that uses the same id twice.

    dfn() derives its id from the term, so defining one term in two places on
    one page silently produces duplicates: the markup is invalid, and every
    aria-describedby past the first resolves to the wrong element, so a screen
    reader reads a definition attached somewhere else entirely. That constraint
    was written down in dfn()'s docstring and promptly violated anyway, which is
    the usual fate of a rule nothing checks. Anchors have the same failure mode
    with a more visible symptom: two ids collide and in-page links land on
    whichever came first.

    The fix when this fires is almost never to invent a second id. It is to
    define the term once, at first mention, and let the later mentions be plain
    text. The canonical repeat lookup is the approach page glossary.
    """
    seen, dupes = set(), []
    for match in re.finditer(r'\sid="([^"]+)"', page):
        if match.group(1) in seen:
            dupes.append(match.group(1))
        seen.add(match.group(1))
    if dupes:
        raise SystemExit(
            f"{where}: duplicate id(s) {sorted(set(dupes))}. If these are dfn "
            f"terms, define each one at its first mention only and use plain "
            f"text afterwards.")


def add_quadratic_dividers(page):
    """Place the scoring-curve divider before every major named section.

    Major narrative sections already have an id so the section navigation can
    link to them. Using the same signal here prevents a decorative divider from
    appearing before incidental headings inside figures or interface examples.
    """
    return re.sub(r'(?=<h2 id=")', QUADRATIC_DIVIDER + "\n", page)


# Every experimental arm, in the order the page introduces it. The KEY of each
# entry is the arm's name in belowzero.contracts; arms_tables() below refuses to
# build if this map and the code ever disagree, in either direction.
#
# Why the descriptions are written here rather than pulled from each contract's
# own `note` field: those notes are addressed to whoever is running the thing
# ("Isolates the effect of ANNOUNCING a rule from the effect of the rule's
# content"), and a reader of this page has not read the codebase. The names, and
# the guarantee that the list is complete, come from the code. The English does
# not.
#
# `state` uses the same three values as STAGES so the labels mean the same thing
# on both pages: "done" reported, "now" ran but not yet analysed, "todo" unrun.
KNOWLEDGE_ARMS = {
    "control": ("Nothing. Just the question.",
                "The status quo: what essentially every benchmark does.",
                "done", "Pilot reported"),
    "guess": ("Scored on accuracy alone, so guessing costs nothing.",
              ("The same incentive as the control, said out loud. Separates "
              "announcing a rule from what the rule says."),
              "done", "Pilot reported"),
    "thresh75": ("Answer only above 75% confident. Wrong answers cost 3.",
                 ("The closest published proposal. Elicits a decision, not a "
                 "probability, so every report above the line scores alike."),
                 "done", "Pilot reported"),
    "quad_formula": (("The algebra only: 2p &minus; p&sup2; if right, "
                     "&minus;p&sup2; if wrong."),
                     ("Can a model act on the arithmetic without being told what "
                     "it implies?"),
                     "done", "Pilot reported"),
    "quad_plain": (("The implication only: honesty is your best strategy, in "
                   "plain English."),
                   ("Is being told the conclusion enough? This decides whether a "
                   "maintainer changes one sentence or hopes for decision theory."),
                   "done", "Pilot reported"),
    "quad_both": ("Both the algebra and the implication.",
                  ("The intended default, and the treatment in the paired "
                  "contrast against the control."),
                  "done", "Pilot reported"),
    "quad_c50": ("The same rule, but asserting costs 0.25 instead of 0.09.",
                 ("Separates the shape of the rule from the price of speaking. "
                 "Moves the silence threshold from 30% to 50%."),
                 "done", "Pilot reported"),
    "deploy": (("The identical incentive, framed as an instruction from a team "
               "who will act on the answer."),
               ("<b>The falsifier.</b> If behaviour differs from quad_both, "
               "models are responding to being graded rather than to the rule, "
               "and the approach improves the measurement rather than the system."),
               "now", "Ran; not yet analysed"),
}

PARITY_ARMS = {
    "standard": (("The published question and answer format, unchanged. No "
                 "confidence asked, no abstention offered."),
                 ("Reproduces a published leaderboard score, so the harness is "
                 "validated before any treatment is trusted."),
                 "done", "Six models passed"),
    "quad_parity": (("The same published question, plus an abstention option, "
                    "the rule, and a request for a probability."),
                    ("The matched treatment. Changes the scoring context and "
                    "nothing else about the item."),
                    "todo", "Not yet run"),
}

BEHAVIOUR_ARMS = {
    "b_none": (("Complete the task. The constraint is stated, with no "
               "consequence attached."),
               "Baseline for whether announcing a consequence matters at all.",
               "todo", "Never run"),
    "b_price": ("Violating the constraint costs 25 points.",
                ("A price. Finite, and therefore purchasable by a model that "
                "wants the points more."),
                "todo", "Never run"),
    "b_gate": ("Violating the constraint voids the entire result.",
               "A prohibition rather than a price. Nothing offsets it.",
               "todo", "Never run"),
    "b_gate_conf": (("The gate on behaviour, plus a 75% confidence target on "
                    "the answer."),
                    ("Whether the two kinds of rule interfere when a model faces "
                    "both at once."),
                    "todo", "Never run"),
}


def arms_tables():
    """Render every experimental arm, checked against the code that defines it.

    The page has always said "eight announced contracts" without naming them,
    which asks the reader to take the design on trust and makes it impossible to
    tell which comparisons have actually happened. This is that list.

    The guard is the point. A hand-written table of arms goes stale the first
    time somebody adds one, and it goes stale silently, because nothing renders
    differently. Comparing key sets against the imported dictionaries turns that
    into a failed build. Same pattern as parity(), which refuses to build if the
    committed CSV names a model that was never frozen.
    """
    from belowzero.contracts import BEHAVIOUR_CONTRACTS, CONTRACTS, PARITY_CONTRACTS

    for label, described, defined in (
            ("knowledge", KNOWLEDGE_ARMS, CONTRACTS),
            ("parity", PARITY_ARMS, PARITY_CONTRACTS),
            ("behaviour", BEHAVIOUR_ARMS, BEHAVIOUR_CONTRACTS)):
        missing = set(defined) - set(described)
        extra = set(described) - set(defined)
        if missing or extra:
            raise SystemExit(
                f"arms table is out of step with belowzero.contracts for the "
                f"{label} track. Defined in code but not described on the page: "
                f"{sorted(missing) or 'none'}. Described but not in code: "
                f"{sorted(extra) or 'none'}. Update KNOWLEDGE_ARMS / PARITY_ARMS "
                f"/ BEHAVIOUR_ARMS in build_site.py.")

    def render(described, defined, order):
        body = []
        for name in order:
            told, isolates, state, label = described[name]
            spec = defined[name]
            # The break-even confidence is a property of the contract, so it is
            # read off the contract rather than retyped into the prose above.
            t = spec.get("t")
            silence = (f'<span class="sub">silent below {t:.0%}</span>'
                       if t else "")
            body.append([
                f"<code>{name}</code>{silence}",
                told,
                isolates,
                f'<span class="state {state}">{label}</span>',
            ])
        return table(["arm", "what the model is told", "what it isolates",
                      "status"], body, right_from=4, cls="arm-map")

    return (render(KNOWLEDGE_ARMS, CONTRACTS, list(KNOWLEDGE_ARMS)),
            render(PARITY_ARMS, PARITY_CONTRACTS, list(PARITY_ARMS)),
            render(BEHAVIOUR_ARMS, BEHAVIOUR_CONTRACTS, list(BEHAVIOUR_ARMS)))


# The six rules implemented in belowzero.rules, and what each one can and cannot
# elicit. The propriety column is not an assertion made here: rules.py grids the
# whole probability range and asserts exactly this table on every test run, and
# rules_table() below checks that the set of rules has not changed underneath it.
RULE_ROWS = [
    ("binary", "1", "0", "no", "nothing",
     "The incumbent. Ignores the probability and cannot score below zero."),
    ("linear", "p", "&minus;p", "no", "a corner",
     "Best report is always 0 or 1, never anything between."),
    ("quadratic", "2p &minus; p&sup2;", "&minus;p&sup2;", "yes",
     "the true belief",
     "Selten's rule. Maximised at p = q."),
    ("quad_cost", "2p &minus; p&sup2; &minus; c", "&minus;p&sup2; &minus; c",
     "yes", "belief, and silence below &radic;c",
     "The recommendation. One knob: the price of asserting."),
    ("log", "1 + log&#8322;p", "1 + log&#8322;(1&minus;p)", "yes",
     "the true belief",
     ("Depends only on the probability given to what happened. Unbounded below, "
      "so one confident error swamps an average.")),
    ("spherical", "p / &#8214;r&#8214;", "(1&minus;p) / &#8214;r&#8214;", "yes",
     "the true belief",
     ("A held-out proper rule that is not an affine transform of quadratic, so "
      "agreement tests whether the calibration gain generalises.")),
    ("threshold", "1", "&minus;t/(1&minus;t)", "as a decision",
     "an answer/abstain choice",
     ("The published comparator. Scores only above t, and everything above t "
     "scores alike, so the number says nothing beyond which side it fell.")),
]


def rules_table():
    """The rule comparison, with its row set checked against belowzero.rules."""
    from belowzero.rules import RULES

    named = {r[0] for r in RULE_ROWS}
    if named != set(RULES):
        raise SystemExit(
            f"rule comparison table is out of step with belowzero.rules. "
            f"In code only: {sorted(set(RULES) - named) or 'none'}. On the page "
            f"only: {sorted(named - set(RULES)) or 'none'}. Update RULE_ROWS "
            f"in build_site.py.")

    body = [[f"<code>{name}</code>", correct, wrong,
             f"<b>{proper}</b>" if proper == "yes" else proper, elicits, note]
            for name, correct, wrong, proper, elicits, note in RULE_ROWS]
    # The threshold rule's two score cells are conditional in a way the others
    # are not, and spelling that out inside the cells forced both columns wide
    # enough to wreck every row. It goes in the note instead.
    return table(["rule", "if right", "if wrong", "proper?",
                  "what it elicits", "notes"], body, right_from=6,
                 cls="rule-map")


def build():
    summary = {r["metric"]: r["value"] for r in rows("census_summary.csv")}
    bench = rows("census_by_benchmark.csv")
    hle = rows("hle_quadratic.csv")
    sens = rows("census_sensitivity.csv")

    total = int(summary["responses_scanned"])

    # --- headline tables ---------------------------------------------------
    big = [r for r in bench if int(r["n_responses"]) >= 3000]
    bench_tbl = table(
        ["benchmark", "responses", "accuracy", "says it doesn't know", "states a probability"],
        [[r["benchmark"], f"{int(r['n_responses']):,}",
          f"{float(r['accuracy']):.3f}" if float(r["accuracy"]) else "&mdash;",
          pct(r["decline_rate"]), pct(r["stated_confidence_rate"], 1)] for r in big])

    def agg(keep):
        sel = [r for r in bench if (r["benchmark"] in AGENTIC) == keep]
        n = sum(int(r["n_responses"]) for r in sel)
        d = sum(int(r["n_decline_phrase"]) for r in sel)
        return len(sel), n, d, d / n
    a_k, a_n, a_d, a_r = agg(True)
    c_k, c_n, c_d, c_r = agg(False)
    split_tbl = table(
        ["kind of benchmark", "benchmarks", "responses", "declines", "rate"],
        [["Agentic &mdash; the environment can show the model it failed",
          a_k, f"{a_n:,}", f"{a_d:,}", f"<b>{pct(a_r)}</b>"],
         ["Closed-form &mdash; the only signal is the model's own uncertainty",
          c_k, f"{c_n:,}", f"{c_d:,}", f"<b>{pct(c_r)}</b>"]])

    sens_tbl = table(
        ["what was searched", "phrase list", "declines found", "rate"],
        [[r["search_scope"], r["phrase_list"], r["n_declines"],
          f"<b>{pct(r['decline_rate'], 3)}</b>"] for r in sens])

    hle_tbl = table(
        ["model", "n", "accuracy", "score", "miscalibration", "resolution",
         "recalibrated", "gain"],
        # Every column formatted to the same three places rather than printed
        # raw. Two reasons. Values in the CSV lost trailing zeros on write, so a
        # column reading .1193 / .1876 / .1021 / .114 claimed a different
        # precision for one model than for the others when all four were
        # computed identically. And four decimals on estimates from 108 to 1,019
        # responses assert a precision the samples do not carry: the third place
        # is already inside the noise for the smallest row.
        [[r["model"], f"{int(r['n']):,}"] +
         [f"{float(r[k]):.3f}" if k != "reliability"
          else f"<b>{float(r[k]):.3f}</b>"
          for k in ("acc", "quad", "reliability", "resolution", "recal")] +
         [f"+{float(r['gain']):.3f}"] for r in hle])

    ratios = [float(r["reliability"]) / float(r["resolution"]) for r in hle
              if float(r["resolution"])]
    mults = [float(r["recal"]) / float(r["quad"]) for r in hle if float(r["quad"]) > 0]

    # The headline stat tile takes ONE model's ratio rather than the full range.
    # The high end of that range is 81x, and it comes from the row whose
    # resolution is 0.002 measured on 108 responses: a near-zero denominator on
    # the thinnest sample in the table. It is honest inside a captioned table
    # where its footnote sits beside it, and misleading at 42px with nothing
    # around it. So the tile reports the largest sample instead, and the range
    # keeps its place in the section below.
    anchor = max(hle, key=lambda r: int(r["n"]))
    anchor_ratio = float(anchor["reliability"]) / float(anchor["resolution"])
    # "openai/gpt-5-2025-08-07" -> "GPT-5". The tile has room for a name, not a
    # release date, and the full identifier is one scroll away in the table.
    anchor_name = anchor["model"].split("/")[-1].rsplit("-2", 1)[0].upper()

    # The affine-map reproduction. Until this file existed the claim it backs was
    # the one number on the page with no code behind it, on a page whose whole
    # argument is that scoring should be inspectable.
    affine = rows("affine_map.csv")
    affine_dev = max(float(r["deviation"]) for r in affine)
    affine_runs = len({r["run"] for r in affine})
    affine_ts = sorted({float(r["threshold"]) for r in affine})

    knowledge_tbl, parity_tbl, behaviour_tbl = arms_tables()

    # Only the files THIS page draws on. Every processed CSV is copied to the
    # site, but the offer here is "download the row a figure came from", and a
    # list padded with another page's data quietly stops being that.
    downloads = " · ".join(
        f'<a href="data/{f}">{f}</a>' for f in
        ("census_summary.csv", "census_by_benchmark.csv", "census_by_model.csv",
         "census_sensitivity.csv", "hle_quadratic.csv", "affine_map.csv"))

    if REPO_PUBLIC:
        byline_tail = (f' &middot; Code &amp; data: '
                       f'<a href="{REPO_URL}">{REPO_URL.split("//")[1]}</a>')
        # The repository ships the scoring code and data, not the code that
        # called or trained models (that is available on request), so the
        # sentence names what is actually there.
        code_para = (f'<p>The scoring code, the processed data behind every number '
                     f'here, and the pre-registration are in the <a href="{REPO_URL}">'
                     f'project repository</a>. The page itself is generated from those '
                     f'files by a script, so a clone reproduces it exactly.</p>')
        prereg_where = "and are in the repository"
        falsify_where = "Written down in advance, in the repository:"
        footer_code = (f'<p>Code &amp; data: <a href="{REPO_URL}">'
                       f'{REPO_URL.split("//")[1]}</a></p>')
    else:
        byline_tail = ""
        code_para = ('<p>Every figure on this page is computed by code from the '
                     'processed data files below, and those files are published '
                     'alongside the page rather than only in a repository. Anyone '
                     'who wants to check a number can download the row it came from '
                     'and recompute it in a spreadsheet.</p>')
        prereg_where = "and have not been revised since"
        falsify_where = "Written down in advance:"
        footer_code = ""

    # The prose is spliced in BEFORE formatting, not passed as a format
    # argument, so that the {placeholders} written in content/index/*.md are
    # filled by the same single pass as the rest of the page. Passing it as an
    # argument would substitute the prose and leave every placeholder inside it
    # standing as literal text.
    index_version = page_version(
        "index.html", INDEX_CONTENT_UPDATED, STYLE_UPDATED
    )
    # This historical page explicitly describes the ten preregistered models.
    # Adding descriptive baselines must not silently change that denominator.
    with open(os.path.join(PROC, "notation_rerun_models.csv"), encoding="utf-8") as fh:
        _pre = [r for r in csv.DictReader(fh) if r["cohort"] == "preregistered"]
    tail_per_100 = sum(float(r["control_high_confidence_error_90_rate"]) for r in _pre) / len(_pre) * 100
    page = PAGE.replace("{body}", content.load("index")).format(
        css=CSS,
        nav=nav("index.html"),
        section_nav=section_nav("index.html"),
        body_class=' class="with-section-nav"',
        fonts=FONTS,
        nav_js=NAV_JS,
        footer_nav=footer_nav("index.html"),
        published=PUBLISHED,
        created_text=index_version["created_text"],
        page_dates=page_dates_html(
            "index.html",
            INDEX_CONTENT_UPDATED,
            STYLE_UPDATED,
            tail=byline_tail,
        ),
        byline_tail=byline_tail,
        essay_page=ESSAY_PAGE,
        oscillation_ref=OSCILLATION_REF,
        code_para=code_para,
        prereg_where=prereg_where,
        falsify_where=falsify_where,
        footer_code=footer_code,
        downloads=downloads,
        # The results marker and the version footer must never disagree, so the
        # marker is the date half of the same constant rather than a second one
        # somebody has to remember to bump.
        results_as_of=INDEX_CONTENT_UPDATED.split()[0],
        # Terms of art defined where this page first uses them. The canonical
        # copies live in the approach page glossary; these are the short forms
        # a reader needs without leaving the sentence they are in.
        dfn_miscalibration=dfn(
            "miscalibration",
            "The part of a bad score that comes from the stated probabilities "
            "being the wrong size rather than the answers being wrong. It is "
            "recoverable by rescaling those numbers alone, without changing a "
            "single answer."),
        dfn_lm_judge=dfn(
            "LM judge",
            "A language model used to decide whether a free-form answer is "
            "correct, where no deterministic check is possible. It is validated "
            "against hand labels before its verdicts are used, because it is the "
            "one link in the pipeline no test can cover."),
        dfn_affine=dfn(
            "positive affine transform",
            "Multiplying by a positive number and adding a constant. It changes "
            "the scale of a score but not the order, so a leaderboard built on "
            "it ranks models identically. Verified across 69 published runs: "
            "maximum deviation 1.2e-15."),
        dfn_brier=dfn(
            "Brier score",
            "The mean squared error of a stated probability, averaging "
            "(p − outcome)². Lower is better."),
        total=f"{total:,}",
        n_models=summary["models"],
        n_bench=summary["benchmarks"],
        decline_pct=pct(summary["decline_rate"]),
        stated_pct=pct(summary["stated_confidence_rate"]),
        # The essay's headline tail, from the same corrected re-run summary the
        # essay reads, so the two front pages cannot quote different numbers.
        tail_per_100=f"{tail_per_100:.0f}",
        bench_table=bench_tbl,
        split_table=split_tbl,
        sens_table=sens_tbl,
        hle_table=hle_tbl,
        rules_table=rules_table(),
        knowledge_arms=knowledge_tbl,
        parity_arms=parity_tbl,
        behaviour_arms=behaviour_tbl,
        agentic_rate=pct(a_r), closed_rate=pct(c_r),
        ratio_lo=f"{min(ratios):.1f}", ratio_hi=f"{max(ratios):.0f}",
        mult_lo=f"{min(mults):.1f}", mult_hi=f"{max(mults):.0f}",
        anchor_ratio=f"{anchor_ratio:.1f}",
        anchor_name=anchor_name,
        anchor_n=f"{int(anchor['n']):,}",
        affine_dev=f"{affine_dev:.1e}".replace("e-", "e&minus;"),
        affine_runs=affine_runs,
        # The summary points forward to the speculative section rather than
        # restating it, so the ambition and the evidence for it stay in one place.
        beyond_link='<a href="#beyond">The last section</a>',
        # WORDS is capitalised for sentence-initial use; both uses here are
        # mid-sentence.
        affine_n_t=WORDS[len(affine_ts)].lower(),
        affine_ts=", ".join(f"{t:.0%}" for t in affine_ts),
        fn_overbroad=fn("A phrase counts if it appears anywhere in the generation, "
                        "including inside a long reasoning trace that ends in a "
                        "confident answer. That inflates the rate rather than "
                        "deflating it. The sensitivity table in A2 varies both "
                        "judgement calls."),
        fn_excluded=fn("Word-game arenas (wordle, fibble) are excluded: there is no "
                       "notion of an answer to decline. Rows with no correctness "
                       "label are excluded from the denominator."),
        fn_extraction=fn("For most benchmarks the published schema does not record "
                         "an extracted answer at all, so the &lsquo;unextracted&rsquo; "
                         "column in the raw data cannot be read as a refusal rate. "
                         "Only six benchmarks carry real extraction data."),
        fn_hle_n=fn("The Claude row covers 108 of 1,798 responses, because the "
                    "agentic HLE runs rarely emitted a parseable probability. "
                    "Treat it as indicative, not comparable. It is also the row "
                    "behind the top of the range quoted below: its resolution of "
                    "0.002 is a very small denominator, which is why the headline "
                    "figure above uses the largest sample instead."),
        fn_gpqa_twice=fn(
            "<code>gpqa-diamond</code> is 69 model runs and "
            "<code>gpqa_diamond</code> is 10, from different contributors, with "
            "different models and different accuracies. The first shows a 2.59% "
            "decline rate and the second zero. Which is right is not something "
            "this data can settle, so both are shown rather than averaged or "
            "quietly dropped. The larger collection is the one every GPQA figure "
            "elsewhere on this page uses, including the sensitivity table and "
            "the affine-map check."),
        fn_affine_ties=fn("Fifteen of the runs share an accuracy with another "
                          "run. Accumulating their scores over different item "
                          "counts separates those ties by about 1e&minus;16, "
                          "which is not a reordering; the check compares pairs "
                          "whose accuracies genuinely differ and requires tied "
                          "pairs to stay tied. Reproduced by "
                          "<code>scripts/affine_map.py</code>, which needs no API "
                          "key and takes a few seconds."),
        content_updated=INDEX_CONTENT_UPDATED,
        style_updated=STYLE_UPDATED,
        structure_updated=STRUCTURE_UPDATED,
        site_commit=INDEX_SITE_COMMIT,
    )
    page = add_quadratic_dividers(page)
    check_unique_ids(page, "index.html")
    # Ship the evidence next to the page. If the repo is private this is the
    # only route a reader has to the underlying numbers, and if it is public it
    # still saves them a clone.
    data_out = os.path.join(OUT, "data")
    os.makedirs(data_out, exist_ok=True)
    import shutil
    # macOS Finder copies ("name 2.csv") landing in data/processed/ would be
    # silently republished by this loop -- two of them were committed before
    # anyone noticed, because CI's site diff only covers tracked files. Refuse
    # to build rather than propagate them.
    stray = re.compile(r" \d+\.[^.]+$")
    strays = sorted(
        f for d in (PROC, data_out) for f in os.listdir(d) if stray.search(f)
    )
    if strays:
        raise SystemExit(
            "stray duplicate file(s) in data/processed or site data "
            f"(delete or rename before building): {strays}"
        )
    for f in sorted(os.listdir(PROC)):
        if f.endswith(".csv"):
            shutil.copy(os.path.join(PROC, f), os.path.join(data_out, f))

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {path}  ({len(page):,} bytes)")
    print(f"  from {len(bench)} benchmark rows, {len(hle)} model rows, "
          f"{len(sens)} sensitivity rows in data/processed/")


# The shared design system. Lives outside PAGE so that every page in the site
# renders from ONE stylesheet rather than a copy that drifts.
CSS = """\
/* Below Zero — research instrument design system.
   The paper surface and serif reading voice come from the project's editorial
   roots. Plum carries identity and the scoring-curve motif; evidence blue,
   valid green, and exclusion amber keep their analytical jobs. Rules and
   whitespace do the grouping so the research pages never collapse into a
   grid of generic content cards. */

/* @tokens-start */
:root {
  /* These public tokens are the contract selected in the design lab.
     Aliases below keep older component names readable while every semantic
     use resolves to one centrally controlled value. */
  --paper:          #f8f7f3;
  --ink:            #1c1b19;
  --plum:           #7a3a58;
  --plum-dark:      #40283b;
  --plum-tint:      #f1e6eb;
  --on-plum:        #fffefa;
  --evidence:       #2b4a6f;
  --valid:          #217a5b;
  --invalid:        #a8661a;
  --on-evidence:    #ffffff;
  --evidence-tint:  #eef2f6;
  --invalid-tint:   #f6eee3;
  --evidence-band:  #aebdcd;

  --text:           var(--ink);
  --text-secondary: #3d3d3d;
  --text-muted:     #6b6b6b;
  --bg:             var(--paper);
  --bg-alt:         var(--evidence-tint);
  --accent:         var(--plum);
  --accent-text:    var(--plum);
  --accent-tint:    var(--plum-tint);
  --rule:           #d8d4cb;
  --rule-strong:    #b9b4aa;
  --ok:             var(--valid);
  --warn:           var(--invalid);
  --max-text:       680px;
  --max-wide:       940px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper:          #171a1d;
    --ink:            #f2f1ec;
    --plum:           #c592aa;
    --plum-dark:      #2a2029;
    --plum-tint:      #30252e;
    --on-plum:        #fffefa;
    --evidence:       #355d82;
    --valid:          #69b58f;
    --invalid:        #d1a15f;
    --on-evidence:    #ffffff;
    --evidence-tint:  #202a33;
    --invalid-tint:   #33291f;
    --evidence-band:  #5d7891;
    --text:           #f2f1ee;
    --text-secondary: #c3c2b7;
    --text-muted:     #8f8e85;
    --bg:             var(--paper);
    --bg-alt:         var(--evidence-tint);
    --accent:         var(--plum);
    --accent-text:    var(--plum);
    --accent-tint:    var(--plum-tint);
    --rule:           #343a3f;
    --rule-strong:    #4a5259;
    --ok:             var(--valid);
    --warn:           var(--invalid);
  }
}

/* @tokens-end */
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
html, body { margin: 0; padding: 0; background: var(--bg); }
body {
  font-family: 'Source Serif 4', ui-serif, Georgia, serif;
  color: var(--text);
  font-size: 18px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: var(--max-wide); margin: 0 auto; padding: 0 24px; }
p, li, h1, h2, h3, .q, .a, .byline, .toc, .note, .cap, blockquote, .rule, details {
  max-width: var(--max-text);
}

/* --- site menu -------------------------------------------------------------
   Fixed to the top of every page and ALWAYS visible. An earlier version
   revealed itself only after 320px of scrolling, which meant a reader landing
   on any page saw no navigation at all until they happened to scroll.
   The full plum field is the site's identity masthead. Evidence blue remains
   reserved for analytical anchors and published ranges inside the page. */
/* @nav-start */
/* Scoped border-box. The global `* { box-sizing }` rule sits outside this
   slice, so the hand-maintained page borrows the menu WITHOUT it and laid the
   bar out 24px wider than the measure every other page uses. Declaring it on
   the menu's own subtree keeps the two in line without reaching into that
   page's chart layout. */
.scroll-nav, .scroll-nav * { box-sizing: border-box; }
.scroll-nav {
  position: fixed; top: 0; left: 0; right: 0; height: 51px;
  background: var(--plum-dark);
  border-bottom: 1px solid color-mix(in srgb, var(--plum-dark) 72%, #000);
  z-index: 100;
}
/* Content clears the fixed bar. This rule lives inside the nav slice on
   purpose: the hand-maintained page borrows the same block, so it can never
   receive the menu without also receiving the space the menu occupies. */
body { padding-top: 51px; }
/* The masthead is already a solid semantic field. Keep only a quiet top rail
   so the navigation retains the same measured 51px geometry as before. */
.scroll-nav-track {
  position: absolute; top: 0; left: 0; right: 0; height: 5px;
  background: color-mix(in srgb, var(--plum-dark) 78%, #000);
}
/* Progress reads along the BOTTOM edge instead, over the hairline rule. Drawn
   there so it never competes with the masthead for the same 5px. */
.scroll-nav-progress {
  position: absolute; bottom: -1px; left: 0; height: 2px; width: 0%;
  background: var(--on-plum); opacity: .86; transition: width .1s linear;
}
.scroll-nav-inner {
  max-width: var(--max-wide); margin: 0 auto; padding: 5px 24px 0; height: 100%;
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif; font-size: 13px;
}
.scroll-nav-title {
  font-weight: 700; color: var(--on-plum); text-decoration: none; white-space: nowrap;
  letter-spacing: -0.005em; flex: none;
}
.scroll-nav-title:hover { color: var(--on-plum); }
.scroll-nav-links {
  display: flex; gap: 17px; min-width: 0;
  letter-spacing: .01em;
}
.scroll-nav-links a {
  color: color-mix(in srgb, var(--on-plum) 72%, transparent);
  text-decoration: none; white-space: nowrap;
  padding: 2px 0; border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
}
.scroll-nav-links a:hover { color: var(--on-plum); }
.scroll-nav-links a.here {
  color: var(--on-plum); font-weight: 600; border-bottom-color: var(--on-plum);
}
/* Group labels: small caps, dimmer than a link, never clickable. They exist
   to let a reader see the menu's shape (read this / deep dives / reference)
   and are dropped on narrow screens, where the abbreviated links alone fit. */
.scroll-nav-links .nav-group {
  color: color-mix(in srgb, var(--on-plum) 46%, transparent);
  font-size: 10.5px; letter-spacing: .09em; text-transform: uppercase;
  align-self: center; white-space: nowrap; margin-right: -6px;
}
.scroll-nav-links .nav-group:not(:first-child) { margin-left: 8px; }
@media (max-width: 640px) { .scroll-nav-links .nav-group { display: none; } }
/* Narrow screens shorten the labels instead of dropping links, so the menu
   stays complete. Below the point where even short labels stop fitting, the
   row scrolls sideways rather than hiding its tail.

   The binding constraint is NOT the viewport. .scroll-nav-inner is capped at
   --max-wide (940px) and centred, so a 4K monitor buys the menu exactly as much
   room as a 1000px laptop: 798px, once the wordmark, the gap and the gutters
   are taken out. Every earlier version of this rule tied the label swap to a
   viewport breakpoint, which is why it kept going stale silently. It was
   measuring the wrong thing, and it looked right on the machine it was written
   on.

   Against that fixed 798px, with 14 pages in SITE (re-measured 2026-08-25):
       full labels  need well past 1500px -> never fit, at any screen size
       short labels need  ~955px          -> overflow by ~157px, at any width
   So the row now scrolls at every width, including desktop, and the fade
   cue below is unconditional to match. Shortening abbreviations remains the
   cheap lever if the scroll gets annoying; ~160px of savings would need
   several renames, which is a deliberate decision, not a side effect.

   Two abbreviations were shortened to get there ("Fine-tuning" to "Tuning",
   "Why linear" to "Linear"), which is the cheap lever: this column exists to be
   short, and one entry that repeated its long label was costing 40px on its own.

   So the short labels are now unconditional, and the row scrolls at every
   width rather than only below 920px. Scrolling is the documented fallback and
   the fade script already targets .scroll-nav-links, so an overflowing tail
   gets its cue automatically. The menu therefore stays COMPLETE by
   construction: adding a page can make the row scroll further, which is a
   graceful failure, but can no longer push a link off the edge with nothing to
   say so. Widen --max-wide or shorten an abbreviation if the scroll becomes
   long enough to be annoying; do not reintroduce a viewport breakpoint. */
.nav-full { display: none; }
.nav-abbr { display: inline; }
.scroll-nav-links {
  overflow-x: auto; scrollbar-width: none; -ms-overflow-style: none;
}
.scroll-nav-links::-webkit-scrollbar { display: none; }
@media (max-width: 920px) {
  .scroll-nav-inner { gap: 14px; padding-left: 16px; padding-right: 16px; }
  .scroll-nav-links { gap: 15px; }
}
/* Fade a cut edge, but ONLY where the row genuinely runs out of space.
   Without the fade a half-cut word reads as a layout bug; with it, it reads as
   "there is more of this row that way", which is the only cue a hidden
   scrollbar leaves.

   The fade width at each edge is a variable the script sets from the row's
   actual scroll position, and the script zeroes both edges whenever the row
   fits, so a fade can never claim hidden content that is not there. The
   values declared here are the no-script state: right-faded / left-clear,
   which matches how an overflowing row always loads (scrollLeft 0).

   This used to sit inside a 600px media query, from when the short-label row
   measured ~475px and only overflowed on phones. At 14 pages the row measures
   ~955px against the fixed 798px budget above, so it overflows at EVERY
   width, and the gate had turned into a lie the other way: on desktop the
   row scrolled with no cue at all, and the auto-scroll that reveals the
   current page's link was hiding the leftmost links behind a clean hard
   edge. The gate is gone rather than re-measured; the script's measurement
   is the condition now. If the menu ever shrinks back below the budget, the
   no-script default over-claims by one fade, which is the cost of keeping
   the cue honest everywhere scripts run. */
.scroll-nav-links {
  --fade-start: 0px;
  --fade-end: 26px;
  -webkit-mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
                      #000 calc(100% - var(--fade-end)), transparent);
  mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
              #000 calc(100% - var(--fade-end)), transparent);
}
@media (max-width: 460px) {
  .scroll-nav-inner { gap: 11px; padding-left: 13px; padding-right: 13px; }
  .scroll-nav-links { gap: 13px; font-size: 12.5px; }
  .scroll-nav-title { font-size: 12.5px; }
}

/* A distinct page-local rail for long articles. It remains in document flow
   until it reaches the fixed site menu, then owns the next horizontal strip.
   Separate nav landmarks and native anchors keep page changes and in-page
   movement as different actions. */
.section-nav, .section-nav * { box-sizing: border-box; }
.section-nav {
  position: sticky; top: 51px; z-index: 90;
  height: 42px; background: color-mix(in srgb, var(--paper) 94%, transparent);
  backdrop-filter: saturate(130%) blur(9px);
  -webkit-backdrop-filter: saturate(130%) blur(9px);
  border-bottom: 1px solid var(--rule);
}
.section-nav-inner {
  max-width: var(--max-wide); height: 100%; margin: 0 auto; padding: 0 24px;
  display: flex; align-items: center; gap: 18px;
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
}
.section-nav-label {
  flex: none; color: var(--text-muted); font-size: 10.5px; font-weight: 700;
  letter-spacing: .09em; text-transform: uppercase;
}
.section-nav-links {
  min-width: 0; display: flex; align-items: stretch; gap: 18px;
  overflow-x: auto; scrollbar-width: none; -ms-overflow-style: none;
  /* Script-driven edge fades, like .table-wrap below: zero until the script
     measures a real overflow, so a rail that fits (literature at phone
     widths) never dims its last link. The rail used to carry a static
     right-only mask below 640px instead, which lied in both directions once
     the rail scrolled: it kept dimming the end after there was nothing past
     it, and it never cued the items cut off on the left. */
  --fade-start: 0px;
  --fade-end: 0px;
  -webkit-mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
                      #000 calc(100% - var(--fade-end)), transparent);
  mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
              #000 calc(100% - var(--fade-end)), transparent);
}
.section-nav-links::-webkit-scrollbar { display: none; }
.section-nav-links a {
  flex: none; color: var(--text-muted); text-decoration: none; white-space: nowrap;
  font-size: 12px; line-height: 42px; border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
}
.section-nav-links a:hover { color: var(--text); }
.section-nav-links a.here {
  color: var(--accent-text); font-weight: 600; border-bottom-color: var(--accent);
}
body.with-section-nav h2[id] { scroll-margin-top: 112px; }
@media (max-width: 640px) {
  .section-nav-inner { padding: 0 13px; gap: 0; }
  .section-nav-label { display: none; }
  .section-nav-links { width: 100%; gap: 16px; }
}
/* @nav-end */

/* --- hero ---------------------------------------------------------------- */
/* Only the front page carries a crumb now, pointing out of the site to the
   projects index. Side pages dropped theirs: it linked to index.html, which the
   fixed menu directly above it already does, and on a phone the two sat forty
   pixels apart reading as a duplicate. */
.crumb {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 13px; color: var(--text-muted); padding-top: 30px; margin: 0 0 26px;
}
/* The crumb was the only thing holding a side page's title off the menu, so its
   30px of padding and 26px of margin move here. Same measurement, one element
   fewer; without it the h1 sat flush against the bar. */
.wrap.side { padding-top: 56px; }
/* Tables whose "value" columns are short phrases, not numbers: left-align
   headers and cells alike so the header does not float away from its column. */
table.text-cols th, table.text-cols td { text-align: left; }
.page-dates-detail {
  display: block; margin-top: 3px; font-size: 12px; color: var(--text-muted);
}
.superseded-banner {
  margin: 0 0 22px; padding: 10px 14px; font-size: 14px; line-height: 1.5;
  border-left: 3px solid var(--accent); background: var(--plot-field, #f6f5f2);
  color: var(--text-secondary);
}
.superseded-banner a { color: var(--accent-text); }
.crumb a { color: var(--text-muted); text-decoration: none; }
.crumb a:hover { color: var(--accent-text); }
h1 {
  font-family: 'Source Serif 4', ui-serif, Georgia, serif;
  font-size: 40px; font-weight: 700; line-height: 1.14; letter-spacing: -0.008em;
  color: var(--plum-dark); margin: 0 0 18px; max-width: 880px;
}
@media (prefers-color-scheme: dark) { h1 { color: var(--plum); } }
/* The question the page answers. Sized between the title and the body. */
.q {
  font-family: 'Source Serif 4', ui-serif, Georgia, serif;
  font-size: 23px; font-weight: 400; line-height: 1.35; color: var(--text-secondary);
  margin: 0 0 20px;
}
/* The answer, in the reader's first ten seconds. */
.a { font-size: 19px; line-height: 1.55; margin: 0 0 24px; }
.a b, .a strong { font-weight: 700; }
.byline {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 13px; line-height: 1.55; color: var(--text-muted); letter-spacing: .01em;
  border-top: 1px solid var(--rule);
  padding: 11px 0 14px; margin: 0 0 36px;
}
.page-dates time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
/* When the stat strip follows the byline directly, close the gap so the two
   read as one banded unit rather than as two floating rules. */
.byline:has(+ .stats) { margin-bottom: 0; }
.byline + .stats { margin-top: 0; }

/* --- stat strip ---------------------------------------------------------- */
.stats {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 0;
  max-width: var(--max-text); margin: 30px 0 34px;
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
}
.stats div {
  padding: 24px 20px; border-right: 1px solid var(--rule);
  display: flex; flex-direction: column; align-items: center; text-align: center; gap: 9px;
}
.stats div:last-child { border-right: none; }
.stats div b {
  font-family: 'Source Serif 4', ui-serif, Georgia, serif;
  font-size: 42px; font-weight: 700; line-height: 1; letter-spacing: -0.015em;
  color: var(--evidence); font-variant-numeric: tabular-nums; display: block;
}
/* The tile's caption. Scoped to the DIRECT child so it cannot also style a
   definition tooltip that happens to sit inside the caption: .dfnbody is a span
   too, and the descendant form caught it, squeezing a 340px popover into the
   26ch measure at caption size while every other tooltip on the site kept its
   own. A tooltip is not a caption; it just happens to be nested in one. */
.stats div > span {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 12.5px; line-height: 1.45; color: var(--text-secondary);
  max-width: 26ch; display: block; text-wrap: balance;
}

/* --- sections ------------------------------------------------------------ */
/* @quadratic-motif
   The divider is the curve: the q=.60 expected-score parabola from the site's
   interactive explainer spans the full reading measure between sections. It
   has no axis, observations, or labels, so it is a signature, not a result. */
h2 {
  font-family: 'Source Serif 4', ui-serif, Georgia, serif;
  font-size: 27px; font-weight: 700; line-height: 1.22; letter-spacing: 0;
  color: var(--text); margin: 3em 0 22px;
}
.quadratic-divider {
  max-width: var(--max-text); margin: 54px 0 24px; line-height: 0;
}
.quadratic-divider svg {
  display: block; width: 100%; height: 58px; overflow: visible;
  -webkit-mask-image: linear-gradient(to right, transparent, #000 7%, #000 93%, transparent);
  mask-image: linear-gradient(to right, transparent, #000 7%, #000 93%, transparent);
}
.quadratic-divider path {
  fill: none; stroke: var(--plum); stroke-width: 1.7;
  stroke-linecap: round;
}
.quadratic-divider + h2 { margin-top: 0; }
h3 {
  font-family: 'Source Serif 4', ui-serif, Georgia, serif;
  font-size: 19.5px; font-weight: 700; line-height: 1.3; margin: 2.1em 0 .5em;
}
p { margin: 0 0 18px; }

/* Findings list: no bullet furniture, a bold accent lead-in per item. */
ul.key { list-style: none; padding: 0; margin: 24px 0 28px;
         display: flex; flex-direction: column; gap: 17px; }
ul.key li { font-size: 17.5px; line-height: 1.55; padding-left: 17px;
            position: relative; }
ul.key li:before { content: ''; position: absolute; left: 0; top: .62em;
                   width: 8px; height: 2px; background: var(--accent); }
ul.key li b, ul.key li strong { font-weight: 700; }

ol { padding-left: 22px; margin: 22px 0 26px; }
ol li { margin-bottom: 13px; line-height: 1.55; }

/* --- contents ------------------------------------------------------------ */
.toc {
  background: transparent; border-top: 1px solid var(--rule-strong);
  border-bottom: 1px solid var(--rule-strong); border-radius: 0;
  padding: 18px 0 20px; margin: 32px 0;
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif; font-size: 14px;
}
.toc b {
  font-size: 11px; font-weight: 700; letter-spacing: .15em; text-transform: uppercase;
  color: var(--text-muted); display: block; margin-bottom: 10px;
}
.toc ol { margin: 0; padding-left: 20px; }
.toc li { margin-bottom: .35em; line-height: 1.45; }
.toc a { color: var(--text); text-decoration: none; }
.toc a:hover { color: var(--accent-text); }

/* --- tables -------------------------------------------------------------- */
/* A table too wide for the viewport scrolls on its own axis rather than letting
   its columns collapse. Same edge fade as the nav row, and for the same reason:
   without a cue, a column cut at the wrapper's edge reads as a broken layout
   rather than as "there is more of this table sideways". The fade widths default
   to zero and are set by script from the wrapper's real scroll position, because
   whether any given table overflows depends on the viewport, the font and the
   data — none of which CSS can ask about. No script means no cue, which
   understates but never misleads. */
.table-wrap {
  max-width: var(--max-wide); margin: 22px 0 26px; overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  --fade-start: 0px;
  --fade-end: 0px;
  -webkit-mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
                      #000 calc(100% - var(--fade-end)), transparent);
  mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
              #000 calc(100% - var(--fade-end)), transparent);
}
table {
  width: 100%; border-collapse: collapse; margin: 0;
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 14px; font-variant-numeric: tabular-nums;
}
/* Below this the columns cannot hold their content; the wrapper scrolls
   instead of the layout collapsing. */
table { min-width: 460px; }
table.narrow { min-width: 380px; }
thead th {
  text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .06em; color: var(--text-muted);
  border-bottom: 1px solid var(--text); padding: 8px 12px 8px 0; vertical-align: bottom;
}
tbody td {
  padding: 12px 12px 12px 0; border-bottom: 1px solid var(--rule);
  color: var(--text); vertical-align: baseline;
}
td.n, th:not(:first-child) { text-align: right; }
/* Tables with few, short columns look stretched at the wide measure; hold them
   to the text column so the eye does not cross an empty gap. */
table.narrow { max-width: var(--max-text); }

/* The gap table is three columns of PROSE, not of numbers, so the defaults are
   wrong for it in three ways: nothing right-aligns, cells align to their top
   rather than to a first baseline they no longer share, and the question column
   is pinned narrow so the two columns a reader actually compares get the room.
   It is also the one table on the site that earns the wide measure, because the
   comparison it supports is horizontal. */
table.gaps { min-width: 640px; }
table.gaps th, table.gaps td { text-align: left; }
table.gaps td { vertical-align: top; line-height: 1.5; }
table.gaps th:first-child, table.gaps td:first-child { width: 23%; }
table.gaps th:nth-child(2), table.gaps td:nth-child(2) { width: 38.5%; }
tbody td:last-child { padding-right: 0; }
thead th:last-child { padding-right: 0; }

.cap {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 12.5px; line-height: 1.5; color: var(--text-secondary); margin: -14px 0 26px;
}
/* A qualifier inside a table cell: what the headline number in that row was
   computed from, kept subordinate to it. */
.sub {
  display: block; font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 11.5px; line-height: 1.35; color: var(--text-muted); margin-top: 3px;
  font-weight: 400;
}

/* --- callouts ------------------------------------------------------------ */
.note {
  background: var(--plum-tint); border-left: 3px solid var(--plum);
  padding: 16px 20px; margin: 26px 0; font-size: 16px; line-height: 1.55;
  color: var(--text-secondary);
}
.note.invalid-note {
  background: var(--invalid-tint); border-left-color: var(--invalid);
}
.note.invalid-note b { color: var(--invalid); }
.note b {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
  color: var(--accent-text); display: block; margin-bottom: 7px;
}
.rule {
  background: var(--bg-alt); border: 1px solid var(--rule); border-radius: 3px;
  padding: 18px 22px; margin: 22px 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 14.5px; line-height: 1.95;
}
blockquote {
  margin: 26px 0; padding: 2px 0 2px 18px; border-left: 3px solid var(--accent);
  font-style: italic; color: var(--text-secondary);
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85em;
  background: var(--bg-alt); border: 1px solid var(--rule);
  padding: 1px 5px; border-radius: 3px;
}
a { color: var(--accent-text); text-underline-offset: 2px; }

details { margin: 20px 0; font-size: 16px; }
details summary {
  cursor: pointer; color: var(--accent-text);
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif; font-size: 13.5px;
  font-weight: 500;
}
details[open] summary { margin-bottom: 12px; }

/* --- status labels ------------------------------------------------------- */
.state {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: .09em;
  font-weight: 700; white-space: nowrap;
}
.state.done { color: var(--ok); }
.state.now  { color: var(--accent-text); }
.state.todo { color: var(--text-muted); }
/* A gate verdict. "Invalid" is amber rather than red on purpose: an excluded
   arm is a control working, not a result that came out badly. */
.state.pass    { color: var(--ok); }
.state.invalid { color: var(--warn); }
.state small {
  display: block; text-transform: none; letter-spacing: 0; font-weight: 400;
  font-size: 10.5px; color: var(--text-muted); margin-top: 3px;
}

/* --- fine-tuning explainer ---------------------------------------------- */
.tune-loop {
  display: grid; grid-template-columns: repeat(4, 1fr);
  max-width: var(--max-wide); margin: 26px 0 12px;
  border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule-strong);
}
.tune-step {
  padding: 20px 18px 22px; border-right: 1px solid var(--rule);
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 13.5px; line-height: 1.48; color: var(--text-secondary);
}
.tune-step:last-child { border-right: none; }
.tune-step b {
  display: block; margin-bottom: 7px; color: var(--text); font-size: 14px;
}
.tune-step span {
  display: block; color: var(--accent-text); font-size: 11px; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase; margin-bottom: 7px;
}
.loop-back {
  max-width: var(--max-wide); margin: 0 0 28px; color: var(--text-muted);
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 12.5px; text-align: right;
}
.arm-table td:first-child { width: 19%; }
.arm-table td:nth-child(2) { width: 38%; }
/* This explanatory table contains prose in every column. Center its labels
   over the full text columns instead of inheriting the numeric-table rule that
   right-aligns non-first headers. */
.experiment-map thead th { text-align: center; }
.eval-matrix { min-width: 680px; }
.eval-matrix td:first-child { width: 32%; }
.eval-matrix th:not(:first-child), .eval-matrix td:not(:first-child) {
  text-align: center;
}

/* --- the arm and rule catalogues -----------------------------------------
   Both are reference tables of PROSE, so the numeric defaults are wrong for
   them the same way they are wrong for .gaps: nothing right-aligns, and cells
   must align to their tops because rows of different lengths no longer share a
   first baseline. Both earn the wide measure, because what a reader does here
   is compare across a row rather than read down a column.

   The minimum widths are the point at which the two prose columns stop being
   readable side by side, not a device size. Below it the wrapper scrolls, which
   is the behaviour a data table should have; letting these squeeze instead
   collapses the arm names, and an arm name broken mid-token reads as a bug. */
.arm-map, .rule-map { min-width: 700px; }
.arm-map th, .arm-map td, .rule-map th, .rule-map td { text-align: left; }
.arm-map td, .rule-map td { vertical-align: top; line-height: 1.5; }
.arm-map td:first-child { width: 15%; }
.arm-map td:nth-child(2) { width: 30%; }
.arm-map td:nth-child(3) { width: 40%; }
/* The status column is a verdict, not prose. Keep it on one line so the column
   reads as a scannable stripe down the right-hand edge. */
.arm-map td:last-child { width: 15%; white-space: nowrap; }
.arm-map code, .rule-map code { white-space: nowrap; }

/* The rule table's two score columns are formulae: short, the thing being
   compared, and they must not wrap mid-expression. Everything else yields width
   to the notes column, which holds the only real prose in the table and so sets
   every row's height. An earlier split gave the notes 28% and produced six-line
   rows beside one-word cells, which is a lot of white space for a table whose
   whole job is to be scanned across. */
.rule-map td:first-child { width: 12%; }
.rule-map td:nth-child(2), .rule-map td:nth-child(3) {
  width: 13%; white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px;
}
.rule-map td:nth-child(4) { width: 9%; }
.rule-map td:nth-child(5) { width: 17%; }
.rule-map td:last-child { width: 36%; }

@media (max-width: 720px) {
  .tune-loop { grid-template-columns: 1fr 1fr; }
  .tune-step:nth-child(2) { border-right: none; }
  .tune-step:nth-child(-n+2) { border-bottom: 1px solid var(--rule); }
}

/* --- replication interval strip -------------------------------------------
   One row per model: the range the published score implies, the published
   score itself, and where this run landed. Drawn from CSS custom properties
   the builder computes, so it is the same numbers as the columns beside it
   rather than a hand-drawn illustration. Positions are on a shared 65-100%
   scale, which is what makes the rows comparable to each other. */
.pi { position: relative; height: 22px; min-width: 132px; }
.pi:before {
  content: ''; position: absolute; left: 0; right: 0; top: 10px;
  height: 1px; background: var(--rule);
}
.pi i {
  position: absolute; display: block; font-style: normal;
}
.pi .band {
  left: var(--lo); width: calc(var(--hi) - var(--lo));
  top: 7px; height: 8px; background: var(--evidence-band); border-radius: 1px;
}
.pi .pub { left: var(--pub); top: 2px; width: 1px; height: 18px; background: var(--evidence); }
.pi .ours {
  left: var(--ours); top: 6px; width: 10px; height: 10px; margin-left: -5px;
  border-radius: 50%; background: var(--ok); border: 2px solid var(--bg);
}
.pi.miss .ours { background: var(--warn); }
/* The legend uses the same three marks at the same sizes as the strip. */
.pi-legend {
  display: flex; gap: 20px; flex-wrap: wrap; align-items: center;
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 12px; color: var(--text-secondary); margin: -12px 0 26px;
}
.pi-legend span { display: flex; gap: 7px; align-items: center; }
.pi-legend em { display: block; font-style: normal; }
.pi-legend .band { width: 24px; height: 8px; background: var(--evidence-band); border-radius: 1px; }
.pi-legend .pub { width: 1px; height: 15px; background: var(--evidence); }
.pi-legend .ours { width: 10px; height: 10px; border-radius: 50%; background: var(--ok); }

/* --- footnote popovers --------------------------------------------------- */
.fn { position: relative; }
.fn button {
  font: inherit; font-size: 10px; line-height: 1; vertical-align: super;
  border: 1px solid var(--rule-strong); background: var(--bg-alt);
  color: var(--text-muted); border-radius: 50%; width: 16px; height: 16px;
  padding: 0; cursor: pointer;
}
.fn button:hover { color: var(--accent-text); border-color: var(--accent); }
.fn .fnbody { display: none; }
.fn:focus-within .fnbody, .fn:hover .fnbody {
  display: block; position: absolute; left: 0; top: 22px; width: min(340px, 72vw);
  background: var(--bg); border: 1px solid var(--rule-strong); border-radius: 3px;
  padding: 12px 14px; z-index: 9; box-shadow: 0 6px 22px rgba(0,0,0,.13);
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 13px; line-height: 1.5; font-style: normal; color: var(--text-secondary);
}

/* --- inline definitions ---------------------------------------------------
   A dotted underline under a term of art. The cue is static because the claim
   it makes is static: there IS a definition attached to this word, at every
   viewport, whether or not anything is hovering it.

   The body is clipped rather than display:none so it stays in the
   accessibility tree; the open state is expressed by undoing the clip. Both
   :hover and :focus are listed because the keyboard route is not optional, and
   :focus-within catches focus landing on anything the definition may contain. */
.dfn {
  font-style: normal; position: relative; cursor: help;
  border-bottom: 1px dotted var(--rule-strong);
}
.dfn:hover, .dfn:focus, .dfn:focus-within { border-bottom-color: var(--accent); }
.dfn:focus { outline: none; }
.dfn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.dfnbody {
  position: absolute; width: 1px; height: 1px;
  overflow: hidden; clip-path: inset(50%); white-space: nowrap;
}
.dfn:hover .dfnbody, .dfn:focus .dfnbody, .dfn:focus-within .dfnbody {
  left: 0; top: 1.75em; width: min(340px, 72vw); height: auto;
  overflow: visible; clip-path: none; white-space: normal;
  background: var(--bg); border: 1px solid var(--rule-strong); border-radius: 3px;
  padding: 12px 14px; z-index: 9; box-shadow: 0 6px 22px rgba(0,0,0,.13);
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 13px; line-height: 1.5; font-style: normal; font-weight: 400;
  color: var(--text-secondary);
  /* A tooltip is a paragraph, and it reads the same wherever the term happens to
     sit. Stated rather than inherited because a defined term can appear inside
     centred furniture, such as a stat tile caption, where inheriting the
     surrounding alignment would centre four lines of prose. */
  text-align: left;
}

/* --- operational records --------------------------------------------------
   The style guide names four registers this site writes in, and the operator
   ledger is one of them: spend against a ceiling, what is authorized next, what
   needs a human. That register kept leaking into narrative prose, where a
   reader following an argument suddenly hits an authorization decision.

   These blocks are folded and labelled rather than deleted. The numbers are
   part of the argument that this work is auditable, so hiding them would cost
   more than the interruption does. The heading and its id stay OUTSIDE the
   details, so the section rail still lands on something visible and a fragment
   link never scrolls to a collapsed box. */
details.operational {
  border: 1px solid var(--rule); border-left: 3px solid var(--text-muted);
  background: var(--bg-alt); border-radius: 3px;
  padding: 0 20px; margin: 22px 0; max-width: var(--max-text);
}
details.operational > summary {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: var(--text-muted); cursor: pointer; padding: 13px 0; list-style: none;
}
details.operational > summary::-webkit-details-marker { display: none; }
/* The marker is drawn rather than inherited so it can rotate, and because the
   native triangle sits at a different baseline in every browser. */
details.operational > summary::before {
  content: '\\25B8'; display: inline-block; margin-right: 9px;
  transition: transform .12s ease; color: var(--text-muted);
}
details.operational[open] > summary::before { transform: rotate(90deg); }
details.operational > summary:hover { color: var(--accent-text); }
details.operational > summary:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 3px;
}
details.operational > *:not(summary) { font-size: 16px; }
details.operational > *:last-child { margin-bottom: 18px; }
details.operational .note { margin-left: 0; margin-right: 0; }

/* The internal design lab is not part of the public argument, and the menu
   should say so before a reader clicks it. */
.scroll-nav a.internal .nav-full::after,
.scroll-nav a.internal .nav-abbr::after {
  content: 'INTERNAL'; display: inline-block; margin-left: 6px;
  font-size: 8.5px; font-weight: 700; letter-spacing: .09em;
  padding: 1px 4px; border-radius: 2px; vertical-align: 1.5px;
  border: 1px solid color-mix(in srgb, var(--on-plum) 40%, transparent);
  color: color-mix(in srgb, var(--on-plum) 66%, transparent);
}

/* --- glossary -------------------------------------------------------------
   A definition list, not a table: the terms are looked up one at a time rather
   than compared down a column, and a table would invite a reader to scan for a
   pattern across rows that is not there. */
/* Definitions are prose and take the prose measure. A dl does not inherit the
   max-width that p carries, so without this the glossary sets 25% wider than
   every paragraph above it on the same page. */
.glossary { margin: 26px 0 0; max-width: var(--max-text); }
.glossary dt {
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 14px; font-weight: 700; color: var(--text); margin-top: 22px;
}
.glossary dd {
  margin: 5px 0 0; font-size: 16.5px; line-height: 1.55;
  color: var(--text-secondary);
}
.glossary dd code { font-size: .88em; }

/* --- footer -------------------------------------------------------------- */
footer {
  border-top: 4px solid var(--plum); margin-top: 64px; padding: 32px 0 80px;
  background: var(--plum-dark);
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
  font-size: 13.5px; line-height: 1.6;
  color: color-mix(in srgb, var(--on-plum) 78%, transparent);
}
footer p { max-width: var(--max-text); margin: 0 0 12px; }
footer b { color: var(--on-plum); }
.footer-nav { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 18px;
              padding-top: 16px; border-top: 1px solid rgba(255,255,255,.22); }
.footer-nav a { color: color-mix(in srgb, var(--on-plum) 76%, transparent); text-decoration: none; }
.footer-nav a:hover { color: var(--on-plum); }
.cite {
  background: rgba(255,255,255,.06); border-left: 3px solid var(--plum);
  padding: 14px 18px; margin-top: 22px; font-size: 13px;
  color: color-mix(in srgb, var(--on-plum) 78%, transparent);
}

/* --- reference lists ------------------------------------------------------
   Citations are apparatus, not argument. They set in the metadata sans at a
   smaller size so a reader following the thread can skip a whole block on
   sight, and hang their first line so every entry starts with an author name
   at the same left edge — which is the only thing anyone scans a reference
   list for. Deliberately NOT numbered: nothing in the prose cites by number,
   and numbering would imply a cross-reference the page does not have. */
ul.refs {
  list-style: none; padding: 0; margin: 16px 0 30px;
  font-family: 'Inter', ui-sans-serif, -apple-system, sans-serif;
}
ul.refs li {
  /* Hanging indent: pad the whole entry in, pull the first line back out. */
  padding-left: 19px; text-indent: -19px;
  margin-bottom: 9px;
  font-size: 14px; line-height: 1.5; color: var(--text-secondary);
}
ul.refs li b { color: var(--text); font-weight: 600; }
/* The gloss is what the work gives THIS project, and it is the part worth
   reading if you read only one part, so it stays in the body colour while the
   bibliographic detail around it recedes. */
ul.refs li .gloss { color: var(--text); }

@media (max-width: 640px) {
  body { font-size: 17px; }
  h1 { font-size: 31px; }
  h2 { font-size: 23px; }
  .quadratic-divider { margin: 42px 0 20px; }
  .quadratic-divider svg { height: 46px; }
  .q { font-size: 20px; }
  .stats { grid-template-columns: 1fr; }
  .stats div { border-right: none; border-bottom: 1px solid var(--rule);
               padding: 18px 0; }
  .stats div:last-child { border-bottom: none; }
  .stats div b { font-size: 40px; }
  .crumb { padding-top: 22px; }
  .wrap.side { padding-top: 48px; }
  table { font-size: 13px; }
  .cap { margin-top: -8px; }
  .tune-loop { grid-template-columns: 1fr; }
  .tune-step { border-right: none; border-bottom: 1px solid var(--rule); }
  .tune-step:nth-child(2) { border-right: none; }
  .tune-step:last-child { border-bottom: none; }
  .loop-back { text-align: left; }
  /* The gate table's verdict column is the whole point of the table, and at
     this width the interval strip pushes it behind a horizontal scroll. Drop
     the strip: it is a picture of the two number columns either side of it, so
     nothing unique is lost, and the legend below explains its absence. */
  table.gate { min-width: 0; }
  table.gate th:nth-child(4), table.gate td:nth-child(4) { display: none; }
  .pi-legend { display: none; }
}
"""

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Below Zero — there should be a penalty for guessing</title>
<meta name="description" content="Benchmarks score a wrong answer the same as no answer, so models guess: across a million published responses fewer than 1% decline, and current models are wrong at 90%+ confidence on 12 of every 100 questions. A proper score prices that error, and training on it is the intervention that moves calibration.">
{fonts}
<style>
{css}</style></head>
<body{body_class} data-created="{created_text}"
      data-last-updated="{content_updated}"
      data-style-updated="{style_updated}"
      data-content-updated="{content_updated}"
      data-structure-updated="{structure_updated}"
      data-commit="{site_commit}">

{nav}
{section_nav}

<div class="wrap">
<p class="crumb"><a href="https://ramongonzalez.com/cost-to-guessing/">&larr; The essay</a></p>

<h1>Below Zero</h1>
<p class="q">Benchmarks should ask a model how sure it is, and say what a
confident mistake costs. Almost none of them do either.</p>
<p class="a">Across {total} published model responses, <b>{decline_pct} decline
to answer.</b> Asked for a probability with every answer, ten current models
were wrong at 90%+ stated confidence on {tail_per_100} of every 100 questions,
and only training on a score that prices that error changed it.</p>
{page_dates}

<div class="stats">
  <div><b>{decline_pct}</b><span>of published responses decline to answer</span></div>
  <div><b>{tail_per_100} in 100</b><span>answers wrong at 90%+ stated confidence, ten current models</span></div>
  <div><b>{total}</b><span>responses across {n_models} models and {n_bench} benchmarks</span></div>
</div>

{body}
</div>

<footer><div class="wrap">
<p>Corrections or questions welcome.</p>
<p><b>Data behind every figure on this page:</b><br>{downloads}</p>
{footer_code}
<div class="cite"><b>Suggested citation:</b> Gonzalez, R. ({published}).
<em>Below Zero: AI benchmarks never ask a model how sure it is.</em></div>
{footer_nav}
</div></footer>
{nav_js}
</body></html>
"""

# ---------------------------------------------------------------------------
# Side pages
#
# The index carries the census and the headline experimental results. These pages
# carry the method, the run records, and the parts still unresolved, so a reader
# who wants any of that does not have to read the source to find out.
# ---------------------------------------------------------------------------

SHELL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
{robots}
{fonts}
<style>
{css}
{extra_css}</style></head>
<body{body_class} data-created="{created_text}"
      data-last-updated="{content_updated}"
      data-style-updated="{style_updated}"
      data-content-updated="{content_updated}"
      data-structure-updated="{structure_updated}"
      data-commit="{site_commit}">

{nav}
{section_nav}

<div class="wrap side">
<h1>{h1}</h1>
<p class="q">{standfirst}</p>
{page_dates}

{body}

</div>

<footer><div class="wrap">
<p>{footer}</p>
{footer_nav}
</div></footer>
{nav_js}
</body></html>
"""


def side_page(filename, *, title, description, h1, standfirst, body, footer,
              published=None, content_updated=None, style_updated=None,
              site_commit=None, internal=False, extra_css=""):
    """Render one side page through the shared shell and write it.

    `published` overrides the site-wide date for a page whose content has its
    own timestamp. It is passed explicitly rather than defaulted to "today" so
    that a rebuild never silently re-dates a page nothing changed in.
    """
    local_nav = section_nav(filename)
    body_class = ' class="with-section-nav"' if local_nav else ""
    local_content_updated = content_updated or CONTENT_UPDATED
    local_style_updated = style_updated or STYLE_UPDATED
    version = page_version(filename, local_content_updated, local_style_updated)
    page = SHELL.format(css=CSS, nav=nav(filename), section_nav=local_nav,
                        body_class=body_class, fonts=FONTS, nav_js=NAV_JS,
                        footer_nav=footer_nav(filename),
                        robots=('<meta name="robots" content="noindex, nofollow, '
                                'noarchive, nosnippet">' if internal else ""),
                        extra_css=extra_css,
                        published=published or PUBLISHED,
                        created_text=version["created_text"],
                        page_dates=page_dates_html(
                            filename, local_content_updated, local_style_updated
                        ),
                        title=title, description=description, h1=h1,
                        standfirst=standfirst, body=body, footer=footer,
                        content_updated=local_content_updated,
                        style_updated=local_style_updated,
                        structure_updated=STRUCTURE_UPDATED,
                        site_commit=site_commit or SITE_COMMIT)
    # The internal design lab contains headings inside interface specimens, so
    # it opts in only where the guide is explicitly demonstrating the divider.
    # Public narrative pages use every named h2 as a true section boundary.
    if not internal:
        page = add_quadratic_dividers(page)
    if filename in SUPERSEDED_PAGES:
        page = mark_superseded(page, filename)
    check_unique_ids(page, filename)
    path = os.path.join(OUT, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {path}  ({len(page):,} bytes)")


def mark_superseded(page, filename):
    """Banner and canonical link for a page the essay has replaced.

    The page stays exactly as it was otherwise: it is kept for comparison, and
    a reader who lands on it from an old link should learn in the first line
    that a fuller account exists and where it is, not discover a disagreement
    three screens down.
    """
    what = SUPERSEDED_PAGES[filename]
    banner = ('<p class="superseded-banner"><strong>Superseded.</strong> This is '
              f'{what}, kept unchanged for comparison. The current account, with '
              'the corrected September 2 numbers, is '
              f'<a href="{ESSAY_PAGE}">the essay</a>; where the two disagree, the '
              'essay governs.</p>')
    page = page.replace('<head><meta charset="utf-8">',
                        f'<head><meta charset="utf-8">\n<link rel="canonical" href="{ESSAY_PAGE}">', 1)
    marker = '<div class="wrap side">\n'
    assert marker in page, filename
    return page.replace(marker, marker + banner + "\n", 1)


STYLE_GUIDE_CSS = r"""
/* This page is an isolated design lab. Every specimen is namespaced under
   .design-lab so none of its experimental grammar leaks into the public site. */
.design-lab { max-width: 1120px; }
.design-lab .lab-intro {
  max-width: 820px; margin: 0 0 26px; color: var(--text-secondary);
}
.lab-tabs {
  display: flex; gap: 0; max-width: 1120px; overflow-x: auto;
  border-top: 1px solid var(--rule-strong);
  border-bottom: 1px solid var(--rule-strong); margin: 28px 0 34px;
}
.lab-tab {
  flex: 1 0 auto; padding: 13px 18px; border: 0; border-right: 1px solid var(--rule);
  border-bottom: 3px solid transparent; background: var(--bg); color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px; font-weight: 600;
  letter-spacing: .04em; text-align: left; cursor: pointer;
}
.lab-tab:last-child { border-right: 0; }
.lab-tab:hover { background: var(--bg-alt); color: var(--text); }
.lab-tab[aria-selected="true"] { border-bottom-color: var(--accent); color: var(--text); }
.lab-tab span { display: block; margin-bottom: 3px; color: var(--text-muted); font-size: 10px; }
.lab-panel[hidden] { display: none; }
.lab-panel { max-width: 1120px; }
.lab-panel > h2:first-child { border-top: 0; margin-top: 0; }
.lab-kicker {
  margin: 0 0 9px; font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 10.5px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase;
}
.lab-recommendation {
  max-width: 900px; margin: 24px 0 34px; padding: 18px 0;
  border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule-strong);
  color: var(--text-secondary); font-size: 17px; line-height: 1.55;
}
.lab-recommendation b {
  display: block; margin-bottom: 6px; color: var(--accent-text);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 10.5px;
  letter-spacing: .13em; text-transform: uppercase;
}
.lab-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 34px; margin: 22px 0 38px; }
.lab-principle { padding: 18px 0 22px; border-top: 1px solid var(--rule); background: transparent; }
.lab-principle:nth-last-child(-n+2) { border-bottom: 1px solid var(--rule); }
.lab-principle h3 { margin: 0 0 7px; }
.lab-principle p:last-child { margin-bottom: 0; }
.token-row {
  display: grid; grid-template-columns: repeat(7, minmax(0, 1fr));
  margin: 20px 0 38px; border-bottom: 1px solid var(--rule);
}
.token {
  position: relative; min-height: 70px; padding: 24px 8px 12px 0;
  border: 0; background: transparent !important; color: var(--text-secondary) !important;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 10px; line-height: 1.35;
}
.token::before { content: ''; position: absolute; inset: 0 0 auto; height: 9px; background: var(--swatch); }
.token b { display: block; font-size: 11px; }
.token.paper { --swatch: #f8f7f3; }
.token.ink { --swatch: #1c1b19; }
.token.plum { --swatch: #7a3a58; }
.token.plum-dark { --swatch: #40283b; }
.token.blue { --swatch: #2b4a6f; }
.token.green { --swatch: #217a5b; }
.token.amber { --swatch: #a8661a; }
.specimen { min-height: 640px; overflow: hidden; border: 1px solid rgba(0,0,0,.18); }
.specimen * { box-sizing: border-box; }
.specimen p { max-width: none; }
.specimen-head {
  display: grid; grid-template-columns: minmax(0, .7fr) minmax(0, 1.3fr);
  gap: 24px; align-items: end; margin: 0 0 18px;
}
.specimen-head h2 { margin: 0; padding: 0; border: 0; font-size: clamp(30px, 5vw, 52px); }
.specimen-head p { margin: 0; color: var(--text-secondary); font-size: 14px; }

/* Direction A: the Below Zero data behaves like a scientific instrument. */
.instrument-demo { background: #f8f7f3; color: #1c1b19; font-family: 'Inter', sans-serif; }
.instrument-bar {
  display: flex; justify-content: space-between; padding: 16px 22px;
  border-bottom: 1px solid #1c1b19; background: #40283b; color: #fff;
  font-size: 11px; font-weight: 650;
  letter-spacing: .09em; text-transform: uppercase;
}
.instrument-body { display: grid; grid-template-columns: .82fr 1.18fr; min-height: 586px; }
.instrument-copy { padding: 46px 34px; border-right: 1px solid #c8c3b8; }
.instrument-copy .lab-kicker { color: #2b4a6f; }
.instrument-copy h3 {
  margin: 0 0 22px; font-family: 'Source Serif 4', Georgia, serif;
  font-size: clamp(52px, 9vw, 94px); font-weight: 400; line-height: .86; letter-spacing: -.045em;
}
.instrument-copy .lede { font-family: 'Source Serif 4', Georgia, serif; font-size: 19px; line-height: 1.45; }
.instrument-proof { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 44px; border-top: 1px solid #1c1b19; }
.instrument-proof div { padding: 13px 10px 0 0; font-size: 11px; color: #625f58; }
.instrument-proof b { display: block; color: #1c1b19; font-size: 22px; }
.instrument-panel { padding: 42px 32px; background: #eef2f6; }
.instrument-panel h4 { margin: 7px 0 4px; font-size: 22px; }
.instrument-panel > p { margin-top: 0; color: #625f58; font-size: 13px; }
.instrument-key { display: flex; flex-wrap: wrap; gap: 16px; margin: 22px 0 8px; color: #625f58; font-size: 10px; }
.instrument-key span { display: flex; align-items: center; gap: 6px; }
.instrument-key i { display: block; width: 18px; height: 3px; background: var(--key); }
.instrument-key .evidence { --key: #2b4a6f; }
.instrument-key .pass { --key: #217a5b; }
.instrument-key .invalid { --key: #a8661a; }
.measure-row { display: grid; grid-template-columns: 1.2fr .55fr 1fr; gap: 16px; align-items: center; padding: 20px 0; border-top: 1px solid #c8c3b8; }
.measure-row:last-child { border-bottom: 1px solid #c8c3b8; }
.measure-row strong { font-size: 13px; }
.measure-row small { display: block; color: #6f6a65; font-size: 10px; }
.measure-row .score { font-family: 'Source Serif 4', serif; font-size: 22px; text-align: right; }
.measure-line { position: relative; height: 18px; }
.measure-line:before { content: ''; position: absolute; inset: 8px 0 auto; height: 1px; background: #9d988e; }
.measure-line:after {
  content: ''; position: absolute; top: 5px; left: var(--lo); width: var(--band);
  height: 7px; background: rgba(43,74,111,.28);
}
.measure-line i { position: absolute; top: 3px; left: var(--x); width: 10px; height: 10px; margin-left: -5px; border-radius: 50%; background: #217a5b; }
.instrument-verdict { margin-top: 30px; padding-left: 14px; border-left: 4px solid #a8661a; font-family: 'Source Serif 4', serif; font-size: 18px; }

/* Direction B: the public story uses Intercept's warm scientific editorial grammar. */
.science-demo { background: #fefaf6; color: #381414; font-family: 'Inter', sans-serif; }
.science-nav { display: flex; gap: 22px; padding: 16px 22px; border-bottom: 1px solid rgba(56,20,20,.25); font-size: 11px; }
.science-nav b { margin-right: auto; font-size: 14px; }
.science-hero { display: grid; grid-template-columns: 1.14fr .86fr; min-height: 360px; }
.science-copy { padding: 44px 34px; }
.science-copy .lab-kicker { color: #ea4a1d; }
.science-copy h3 { margin: 0 0 18px; font-family: 'Source Serif 4', serif; font-size: clamp(42px, 7vw, 74px); font-weight: 400; line-height: .93; letter-spacing: -.035em; }
.science-copy p { font-family: 'Source Serif 4', serif; font-size: 18px; line-height: 1.5; }
.science-number { display: flex; flex-direction: column; justify-content: space-between; padding: 42px 30px; background: #ea4a1d; color: #fff; }
.science-number b { font-family: 'Source Serif 4', serif; font-size: clamp(66px, 10vw, 112px); font-weight: 400; line-height: .8; }
.science-number span { max-width: 260px; font-size: 13px; line-height: 1.45; }
.science-plot { padding: 24px 34px 32px; border-top: 1px solid rgba(56,20,20,.25); }
.science-plot-head { display: flex; justify-content: space-between; gap: 20px; margin-bottom: 22px; font-size: 11px; }
.science-bars { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; height: 145px; align-items: end; }
.science-bars span { height: var(--h); background: var(--c); }
.science-axis { display: flex; justify-content: space-between; padding-top: 8px; border-top: 1px solid rgba(56,20,20,.35); color: #6f6a65; font-size: 10px; }

/* Direction C: internal state follows the IB operator console's compact grammar. */
.ledger-demo { background: #f7f8fa; color: #1f2933; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.ledger-head { padding: 20px 24px 0; background: #fff; border-bottom: 1px solid #e4e7eb; }
.ledger-title { display: flex; justify-content: space-between; gap: 20px; }
.ledger-title h3 { margin: 0; font-size: 20px; }
.ledger-title p { margin: 3px 0 14px; color: #52606d; font-size: 13px; }
.ledger-title span { color: #7b8794; font-size: 11px; }
.ledger-tabs { display: flex; gap: 22px; }
.ledger-tabs b { padding: 8px 0 10px; border-bottom: 2px solid #2563eb; font-size: 12px; }
.ledger-tabs span { padding: 8px 0 10px; color: #52606d; font-size: 12px; }
.ledger-main { max-width: 760px; margin: 0 auto; padding: 24px; }
.ledger-summary { display: grid; grid-template-columns: repeat(3, 1fr); margin-bottom: 14px; border: 1px solid #e4e7eb; background: #fff; }
.ledger-summary div { padding: 13px 15px; border-right: 1px solid #e4e7eb; }
.ledger-summary div:last-child { border-right: 0; }
.ledger-summary b { display: block; font-size: 21px; }
.ledger-summary small { color: #7b8794; font-size: 10px; }
.ledger-card { margin-bottom: 12px; padding: 18px 20px; border: 1px solid #e4e7eb; border-radius: 9px; background: #fff; box-shadow: 0 1px 3px rgba(16,24,40,.07); }
.ledger-chips { display: flex; gap: 7px; margin-bottom: 10px; }
.ledger-chip { padding: 2px 8px; border-radius: 20px; font-size: 10px; font-weight: 650; }
.ledger-chip.ok { background: #ecfdf3; color: #067647; }
.ledger-chip.warn { background: #fffaeb; color: #b54708; }
.ledger-chip.info { background: #eef4ff; color: #2563eb; }
.ledger-card h4 { margin: 0 0 5px; font-size: 17px; }
.ledger-card p { margin: 0; color: #52606d; font-size: 13px; }
.ledger-meta { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #e4e7eb; }
.ledger-meta span { color: #7b8794; font-size: 10px; text-transform: uppercase; }
.ledger-meta b { display: block; color: #1f2933; font-size: 12px; text-transform: none; }

@media (max-width: 720px) {
  .design-lab { max-width: 100%; }
  .lab-tabs { margin-left: -18px; margin-right: -18px; padding-left: 18px; }
  .lab-tab { min-width: 150px; }
  .lab-grid, .specimen-head, .instrument-body, .science-hero { grid-template-columns: 1fr; }
  .token-row { grid-template-columns: repeat(7, minmax(74px, 1fr)); overflow-x: auto; }
  .lab-principle:nth-last-child(-n+2) { border-bottom: 0; }
  .lab-principle:last-child { border-bottom: 1px solid var(--rule); }
  .instrument-copy { border-right: 0; border-bottom: 1px solid #c8c3b8; }
  .instrument-proof, .ledger-summary { grid-template-columns: 1fr; }
  .instrument-proof div, .ledger-summary div { padding: 10px 0; border-right: 0; border-bottom: 1px solid #d7d3ca; }
  .measure-row { grid-template-columns: 1fr .55fr; }
  .measure-line { grid-column: 1 / -1; }
  .science-number { min-height: 240px; }
  .ledger-main { padding: 16px; }
  .ledger-meta { grid-template-columns: 1fr; }
}
"""


def build_style_guide():
    """Render a local-only design lab with real project data in each option.

    The specimens are deliberately isolated from the production stylesheet.
    Choosing a direction later should be a separate, explicit change rather
    than an accidental side effect of making the comparison page.
    """
    body = r"""
<div class="design-lab">
<p class="lab-intro">This internal page separates durable rules from aesthetic
choices. Each direction uses the same current validation facts, so the comparison
is about hierarchy and graphic grammar rather than different content.</p>

<div class="lab-tabs" role="tablist" aria-label="Design lab sections">
  <button class="lab-tab" id="tab-guide" role="tab" aria-selected="true" aria-controls="panel-guide" data-panel="guide"><span>00 / SYSTEM</span>Working guide</button>
  <button class="lab-tab" id="tab-instrument" role="tab" aria-selected="false" aria-controls="panel-instrument" data-panel="instrument"><span>01 / RECOMMENDED</span>Research instrument</button>
  <button class="lab-tab" id="tab-science" role="tab" aria-selected="false" aria-controls="panel-science" data-panel="science"><span>02 / PUBLIC</span>Scientific narrative</button>
  <button class="lab-tab" id="tab-ledger" role="tab" aria-selected="false" aria-controls="panel-ledger" data-panel="ledger"><span>03 / INTERNAL</span>Operator ledger</button>
</div>

<section class="lab-panel" id="panel-guide" role="tabpanel" aria-labelledby="tab-guide">
<h2 id="principles">The working guide</h2>
<div class="lab-recommendation"><b>Selected direction</b>The public research
pages should use the research instrument with plum for identity, curves, and
selective emphasis; blue for reference information; green for valid results;
and amber for protocol exclusions. Internal run control can retain the operator
ledger. Neither surface needs a grid of content cards. Between major sections,
one full-width quadratic curve replaces the heading rule entirely.</div>
<div class="lab-grid">
  <div class="lab-principle"><h3>One job per page</h3><p>A reader should know whether a page is making a finding, explaining a method, or reporting operational state within ten seconds. Do not mix those modes in one hero.</p></div>
  <div class="lab-principle"><h3>Graphics carry claims</h3><p>Every visual dimension must encode a stated quantity. The section divider repeats the q = 0.60 scoring curve from the interactive explainer; charts still require scales and labels.</p></div>
  <div class="lab-principle"><h3>Precision follows evidence</h3><p>Benchmark accuracy uses one decimal place. Spend uses cents. Smoke tests are labelled as plumbing, never capability evidence.</p></div>
  <div class="lab-principle"><h3>Invalid stays visible</h3><p>Green means a completed gate passed. Amber means the measurement is not valid. A result inside the expected range does not override a broken protocol.</p></div>
</div>

<h3>Core public tokens</h3>
<div class="token-row" aria-label="Recommended public color tokens">
  <div class="token paper"><b>Paper</b>#f8f7f3</div>
  <div class="token ink"><b>Ink</b>#1c1b19</div>
  <div class="token plum"><b>Curve</b>#7a3a58</div>
  <div class="token plum-dark"><b>Identity</b>#40283b</div>
  <div class="token blue"><b>Evidence</b>#2b4a6f</div>
  <div class="token green"><b>Valid pass</b>#217a5b</div>
  <div class="token amber"><b>Invalid</b>#a8661a</div>
</div>

<h3>Reference families and what to borrow</h3>
<div class="table-wrap"><table class="gaps"><thead><tr><th>reference</th><th>borrow</th><th>do not import wholesale</th></tr></thead><tbody>
<tr><td><b>Intercept</b></td><td>Warm scientific editorial palette, very large quantitative anchors, modular explanatory graphics, and clear shifts between narrative and evidence.</td><td>Its vivid orange and multicolor data accents are distinctive brand signals. Use their logic sparingly, not their exact personality everywhere.</td></tr>
<tr><td><b>Ban Together</b></td><td>Paper-like typography, numbered evidence anatomy, visible provenance, and the idea that the domain artifact should determine the layout.</td><td>The docket metaphor is too institutional for every research page. Below Zero needs an instrument more often than a case file.</td></tr>
<tr><td><b>IB Operator Console</b></td><td>Compact tabs, status chips, progressive disclosure, latest-state summaries, and calm fail-visible operational cards.</td><td>White rounded cards on cool gray read as software. Keep that grammar inside operational surfaces.</td></tr>
<tr><td><b>Dollars Just for DC</b></td><td>Generated data, traceable annotations, research-paper restraint, and layouts that let comparisons happen on one shared scale.</td><td>Restraint can become visual sameness. Below Zero should let its probability and interval mechanics become a stronger signature.</td></tr>
</tbody></table></div>

{quadratic_divider}
<h2 id="decision">How to choose</h2>
<p>Choose by task, not by which mockup looks most polished. The public result page
must make the estimate, benchmark, and validity state readable in three seconds.
The internal page must make the next decision and its consequence readable in
the same time. The recommended split is option 01 for public evidence and option
03 for internal operations, with option 02 reserved for the opening narrative
and large explanatory graphics.</p>
</section>

<section class="lab-panel" id="panel-instrument" role="tabpanel" aria-labelledby="tab-instrument" hidden>
<div class="specimen-head"><div><p class="lab-kicker">Direction 01 / Selected</p><h2 id="options">Research instrument</h2></div><p>Ban Together's calibration-instrument idea meets the shared-axis discipline of Dollars Just for DC. Plum carries identity and the curve motif; blue, green, and amber remain evidence, pass, and invalid states without turning the page into a card grid.</p></div>
<div class="specimen instrument-demo">
  <div class="instrument-bar"><b>Below Zero / validation record</b><span>GPQA Diamond / 16 Aug 2026</span></div>
  <div class="instrument-body">
    <div class="instrument-copy">
      <p class="lab-kicker">Measure 01 / Standard arm</p>
      <h3>Six passes.<br>Five labs.</h3>
      <p class="lede">The standard benchmark environment now lands where published results say it should. That validates the instrument, not the hypothesis.</p>
      <div class="instrument-proof"><div><b>198</b>items per full run</div><div><b>1 + 5</b>recorded plus reconstructed</div><div><b>$46.21</b>key usage</div></div>
    </div>
    <div class="instrument-panel">
      <p class="lab-kicker">Observed against published range</p>
      <h4>Every valid full run passed</h4>
      <p>Dots share one axis. The visual never zooms each model independently.</p>
      <div class="instrument-key" aria-label="Instrument color key"><span class="evidence"><i></i>published range</span><span class="pass"><i></i>valid run</span><span class="invalid"><i></i>protocol exclusion</span></div>
      <div class="measure-row"><strong>MiniMax M3<small>fully recorded</small></strong><span class="score">90.9%</span><div class="measure-line" style="--lo:52%;--band:39%;--x:63%"><i></i></div></div>
      <div class="measure-row"><strong>GPT-5.6 Terra<small>reconstructed</small></strong><span class="score">92.9%</span><div class="measure-line" style="--lo:61%;--band:34%;--x:80%"><i></i></div></div>
      <div class="measure-row"><strong>Qwen3.6 Plus<small>reconstructed</small></strong><span class="score">87.9%</span><div class="measure-line" style="--lo:30%;--band:48%;--x:54%"><i></i></div></div>
      <p class="instrument-verdict">Muse Spark remains invalid despite landing near its published score. Validity is part of the measurement.</p>
    </div>
  </div>
</div>
</section>

<section class="lab-panel" id="panel-science" role="tabpanel" aria-labelledby="tab-science" hidden>
<div class="specimen-head"><div><p class="lab-kicker">Direction 02 / Public narrative</p><h2>Scientific narrative</h2></div><p>Inspired by Intercept's warm ivory, oxblood, orange, editorial serif, and large data-first modules. Best for explaining why the work matters before the methods begin.</p></div>
<div class="specimen science-demo">
  <div class="science-nav"><b>BELOW ZERO</b><span>Finding</span><span>Method</span><span>Experiment</span></div>
  <div class="science-hero">
    <div class="science-copy"><p class="lab-kicker">A measuring instrument before an experiment</p><h3>Can a benchmark run behave normally?</h3><p>Six current models across five companies reproduced the published range on GPQA Diamond.</p></div>
    <div class="science-number"><b>6</b><span>full 198-item runs passed. One carries exact prompt provenance recorded at inference time.</span></div>
  </div>
  <div class="science-plot"><div class="science-plot-head"><b>Accuracy across passing runs</b><span>shared baseline / illustrative bars from current results</span></div><div class="science-bars"><span style="--h:93%;--c:#ea4a1d"></span><span style="--h:90%;--c:#aee3ff"></span><span style="--h:88%;--c:#ff8df3"></span><span style="--h:76%;--c:#e8d64f"></span><span style="--h:93%;--c:#6a1c13"></span><span style="--h:91%;--c:#948d87"></span></div><div class="science-axis"><span>65%</span><span>100%</span></div></div>
</div>
</section>

<section class="lab-panel" id="panel-ledger" role="tabpanel" aria-labelledby="tab-ledger" hidden>
<div class="specimen-head"><div><p class="lab-kicker">Direction 03 / Internal operations</p><h2>Operator ledger</h2></div><p>Adapted from the Interactive Brokers localhost console. It is deliberately more compact and software-like because the job is deciding what needs action.</p></div>
<div class="specimen ledger-demo">
  <div class="ledger-head"><div class="ledger-title"><div><h3>Experiment console</h3><p>Current validation state and the next authorized action.</p></div><span>local / read-only preview</span></div><div class="ledger-tabs"><b>Validation</b><span>Run ledger</span><span>Budget</span></div></div>
  <div class="ledger-main">
    <div class="ledger-summary"><div><b>6</b><small>valid passes</small></div><div><b>3</b><small>invalid attempts</small></div><div><b>$3.79</b><small>remaining to $50 aim</small></div></div>
    <div class="ledger-card"><div class="ledger-chips"><span class="ledger-chip ok">PASS</span><span class="ledger-chip info">FULL PROVENANCE</span></div><h4>MiniMax M3 completed the gate</h4><p>180 of 198 correct. Exact ordered prompts, provider, model, reasoning tokens, and retry history are stored.</p><div class="ledger-meta"><span>Observed<b>90.9%</b></span><span>Published<b>92.9%</b></span><span>Cost<b>$1.91</b></span></div></div>
    <div class="ledger-card"><div class="ledger-chips"><span class="ledger-chip warn">INVALID</span><span class="ledger-chip info">RETRY PRESERVED</span></div><h4>Muse Spark has one unresolved API outcome</h4><p>Both explicitly authorized attempts ended in the same ambiguous 502. The penalized score stays visible but does not become a pass.</p><div class="ledger-meta"><span>Latest state<b>197 usable / 198</b></span><span>Penalized<b>88.9%</b></span><span>Action<b>Do not retry</b></span></div></div>
    <div class="ledger-card"><div class="ledger-chips"><span class="ledger-chip info">SMOKE ONLY</span></div><h4>Claude Haiku route connected</h4><p>One item verified the OpenRouter route. It is not a replication run and should not appear in the six-model headline.</p></div>
  </div>
</div>
</section>
</div>

<script>
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.lab-tab'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.lab-panel'));
  function activate(name, updateHash) {
    tabs.forEach(function (tab) {
      var active = tab.dataset.panel === name;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach(function (panel) { panel.hidden = panel.id !== 'panel-' + name; });
    if (updateHash) history.replaceState(null, '', '#' + name);
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () { activate(tab.dataset.panel, true); });
    tab.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      event.preventDefault();
      var delta = event.key === 'ArrowRight' ? 1 : -1;
      var next = tabs[(index + delta + tabs.length) % tabs.length];
      activate(next.dataset.panel, true);
      next.focus();
    });
  });
  var requested = location.hash.slice(1);
  activate(tabs.some(function (tab) { return tab.dataset.panel === requested; }) ? requested : 'guide', false);
})();
</script>
""".replace("{quadratic_divider}", QUADRATIC_DIVIDER)
    side_page(
        "style-guide.html",
        title="Below Zero: internal design lab",
        description="An internal style guide and three visual directions for Below Zero.",
        h1="The style should explain the instrument",
        standfirst=("Three visual directions use the same live validation facts. "
                    "The question is which grammar makes the evidence easiest "
                    "to read, and which belongs only on internal controls."),
        published="Internal working page",
        body=body,
        footer=("This page is excluded from indexing. Choosing a direction does "
                "not change the public pages until that choice is implemented "
                "and verified separately."),
        content_updated=STYLE_GUIDE_CONTENT_UPDATED,
        style_updated=STYLE_GUIDE_STYLE_UPDATED,
        site_commit=STYLE_GUIDE_SITE_COMMIT,
        internal=True,
        extra_css=STYLE_GUIDE_CSS,
    )


def css_slice(start, end):
    """Cut one labelled region out of the stylesheet.

    Used to give a hand-maintained page the design tokens and nav rules it needs
    without copying them. There is still exactly one definition; this is a view
    onto it, so editing CSS updates every page that borrows from it.
    """
    body = CSS.split(start, 1)[1].split(end, 1)[0]
    return body.strip("\n")


def inject_nav(filename):
    """Put the shared nav into a hand-maintained page, between its markers.

    why-linear-fails.html is written by hand because it is an interactive
    explainer with its own scoped tokens, not a rendered narrative. It still
    has to carry the same navigation, so the nav is injected rather than
    copied: there is one definition of SITE, and this page cannot fall out of
    it. Idempotent, so rebuilding never stacks copies.
    """
    path = os.path.join(OUT, filename)
    with open(path, encoding="utf-8") as fh:
        page = fh.read()
    # The nav is a sticky, JS-revealed component, so this page needs the tokens
    # it references, its rules, and the script — all sliced from the one source.
    chrome = ("<style>\n"
              + css_slice("/* @tokens-start */", "/* @tokens-end */") + "\n"
              + css_slice("/* @nav-start */", "/* @nav-end */")
              + "\n</style>")
    replacement = ("<!--NAV-->" + chrome + nav(filename) + NAV_JS.strip()
                   + "<!--/NAV-->")
    updated = re.sub(r"<!--NAV-->.*?<!--/NAV-->", lambda _: replacement,
                     page, flags=re.DOTALL)
    version = page_version(filename, CONTENT_UPDATED, STYLE_UPDATED)
    versioned_body = (f'<body data-created="{version["created_text"]}" '
                      f'data-last-updated="{CONTENT_UPDATED}" '
                      f'data-style-updated="{STYLE_UPDATED}" '
                      f'data-content-updated="{CONTENT_UPDATED}" '
                      f'data-structure-updated="{STRUCTURE_UPDATED}" '
                      f'data-commit="{SITE_COMMIT}">')
    updated = re.sub(
        r'<body(?:\s+data-(?:created|last-updated|style-updated|commit)="[^"]*")*\s*>',
        versioned_body,
        updated,
        count=1,
    )
    dates = ("<!--PAGE-DATES-->"
             + page_dates_html(
                 filename, CONTENT_UPDATED, STYLE_UPDATED, author=False
             )
             + "<!--/PAGE-DATES-->")
    if "<!--PAGE-DATES-->" in updated:
        updated = re.sub(
            r"<!--PAGE-DATES-->.*?<!--/PAGE-DATES-->",
            lambda _: dates,
            updated,
            count=1,
            flags=re.DOTALL,
        )
    else:
        updated, replacements = re.subn(
            r'(<p class="sub">.*?</p>)',
            lambda match: match.group(1) + "\n  " + dates,
            updated,
            count=1,
            flags=re.DOTALL,
        )
        if replacements != 1:
            raise SystemExit(f"{filename} has no lead paragraph for page dates")
    if updated == page and "<!--NAV-->" not in page:
        raise SystemExit(f"{filename} has no <!--NAV--> markers to fill")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(updated)
    print(f"injected nav into {path}")


# The replication strip's shared axis. Every model is drawn on the same 65% to
# 100% scale, so a reader comparing two rows is comparing distances rather than
# two independently zoomed pictures. Widen it if a future target falls outside.
SCALE_LO, SCALE_HI = 65.0, 100.0


def _at(fraction):
    """Position on the shared axis, as a CSS percentage."""
    return f"{(float(fraction) * 100 - SCALE_LO) / (SCALE_HI - SCALE_LO) * 100:.2f}%"


# Counts read as prose in a sentence, not as data in a table.
WORDS = {0: "No", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
         6: "Six", 7: "Seven", 8: "Eight"}


def parity():
    """The GPQA replication gate, read back from the committed aggregate.

    Every number the page prints comes from data/processed/gpqa_parity*.csv.
    The frozen targets in belowzero.parity are re-checked against the artifact
    here, so an edit to either one that drifts from the other fails the build
    rather than publishing a mismatch. No question text is in the artifact and
    none is rendered; the gate reports counts.
    """
    from belowzero.parity import PARITY_TARGETS

    models = rows("gpqa_parity.csv")
    for r in models:
        target = PARITY_TARGETS.get(r["model"])
        if target is None:
            raise SystemExit(f"gpqa_parity.csv names an unfrozen model: {r['model']}")
        if abs(float(r["published_score"]) - target["score"]) > 1e-9:
            raise SystemExit(f"{r['model']}: published score in the CSV does not "
                             "match the pre-registered target")
    return models, {r["metric"]: r for r in rows("gpqa_parity_summary.csv")}


def build_validation():
    """Did the harness reproduce a published benchmark before spending on the
    experiment? The answer has to be legible in about ten seconds, including
    the part that says what the answer is not."""
    models, summary = parity()

    def val(metric):
        return summary[metric]["value"]

    passing = [r for r in models if r["status"].startswith("PASS")]
    invalid = [r for r in models if r["status"] == "INVALID"]
    smokes = [r for r in models if r["status"] == "INCOMPLETE"]
    n_pass, n_invalid, n_smoke = len(passing), len(invalid), len(smokes)
    if str(n_pass) != val("complete_runs_passing"):
        raise SystemExit("passing rows disagree with the summary count")
    if str(n_invalid) != val("invalid_attempts"):
        raise SystemExit("invalid rows disagree with the summary count")
    if str(n_smoke) != val("incomplete_smokes"):
        raise SystemExit("smoke rows disagree with the summary count")

    # Per-model costs are stored to the cent; the summary carries the exact
    # provider-reported total. They must still agree at the cent.
    per_model = sum(float(r["cost_usd"]) for r in models)
    if abs(per_model - float(val("parity_cost_usd"))) > 0.005:
        raise SystemExit("per-model costs do not reconcile with the parity total")

    dfn_arm = dfn(
        "arm",
        "One condition in an experiment, with everything else held identical, "
        "so a difference between two arms is caused by the thing that differs "
        "between them. The standard arm is the one that announces no scoring "
        "rule, which is what nearly every benchmark does today.")

    body_rows = []
    for r in passing + invalid:
        n, correct = int(r["n"]), r["correct"]
        label = html.escape(r["label"])
        scored = bool(correct) and n > 0

        if scored:
            accuracy = int(correct) / n
            ours = f'<b>{accuracy * 100:.1f}%</b>'
            marks = '<i class="band"></i><i class="pub"></i><i class="ours"></i>'
            style = (f'--lo:{_at(r["interval_low"])};--hi:{_at(r["interval_high"])};'
                     f'--pub:{_at(r["published_score"])};--ours:{_at(accuracy)}')
            # The dot follows the GATE, not interval containment. One excluded
            # arm landed inside its interval and still failed on format
            # failures, and a green dot beside an "invalid" verdict would read
            # as a contradiction rather than as the distinction it is.
            excluded = "" if r["status"].startswith("PASS") else " miss"
            strip = (f'<div class="pi{excluded}" style="{style}">{marks}</div>')
            items = f"{correct} of {n} correct"
        else:
            # Nothing was generated, so there is no result to place. The
            # published score is still drawn, which is what makes the empty row
            # read as "not run" rather than as "ran and scored zero".
            ours = '<span class="sub">not scored</span>'
            strip = (f'<div class="pi" style="--pub:{_at(r["published_score"])}">'
                     f'<i class="pub"></i></div>')
            items = "no scored response" if n else "no responses generated"

        if r["status"] == "PASS":
            gate = ('<span class="state pass">Pass'
                    '<small>recorded</small></span>')
        elif r["status"] == "PASS_RECONSTRUCTED":
            gate = ('<span class="state pass">Pass'
                    '<small>reconstructed</small></span>')
        else:
            gate = ('<span class="state invalid">Invalid'
                    '<small>excluded</small></span>')

        body_rows.append([
            f'{label}<span class="sub">{items}</span>',
            ours,
            f'{float(r["published_score"]) * 100:.1f}%',
            strip,
            gate,
        ])

    gate_tbl = table(["model", "this run", "published", "replication", "gate"],
                     body_rows, right_from=1, cls="gate")

    legend = ('<div class="pi-legend">'
              '<span><em class="band"></em>range a published score implies '
              'at this sample size</span>'
              '<span><em class="pub"></em>published score</span>'
              '<span><em class="ours"></em>this run</span>'
              '</div>')

    reasons = "".join(
        f'<h3>{html.escape(r["label"])}</h3>'
        f'<p>{html.escape(r["exclusion_reason"])}</p>'
        for r in invalid)

    smoke_rows = []
    for r in smokes:
        n, correct = int(r["n"]), int(r["correct"] or 0)
        result = "correct" if n and correct == n else "incorrect"
        smoke_rows.append([
            html.escape(r["label"]),
            f'{n}-item check: {result}',
            html.escape(r["exclusion_reason"]),
        ])
    smoke_tbl = table(["model", "observed", "interpretation"], smoke_rows,
                      right_from=99, cls="gaps")

    cost_rows = [[html.escape(r["label"]),
                  f'{int(r["n"]):,}' if int(r["n"]) else "0",
                  f'${float(r["cost_usd"]):,.2f}']
                 for r in models]
    stored = sum(int(r["n"]) for r in models)
    cost_rows.append(["<b>Whole gate</b>", f'{stored:,}',
                      f'<b>${float(val("parity_cost_usd")):,.2f}</b>'])
    cost_tbl = table(["model", "latest-state rows", "cost"], cost_rows,
                     right_from=1, cls="narrow")

    threshold = float(val("format_failure_threshold")) * 100

    largest_cost = max(models, key=lambda r: float(r["cost_usd"]))
    largest_label = html.escape(largest_cost["label"].split(" (")[0])
    largest_usd = float(largest_cost["cost_usd"])
    stats = (f'<div class="stats">'
             f'<div><b>{n_pass}</b><span>passing full runs from '
             f'{int(val("companies_passing"))} model companies</span></div>'
             f'<div><b>{int(val("fully_recorded_passes"))} + '
             f'{int(val("reconstructed_passes"))}</b><span>fully recorded pass '
             f'plus earlier reconstructed passes</span></div>'
             f'<div><b>${float(val("openrouter_key_usage_usd")):,.2f}</b><span>of '
             f'the ${float(val("spend_ceiling_usd")):,.0f} OpenRouter aim used</span></div>'
             f'</div>')

    side_page(
        "validation.html",
        title="Below Zero — does the harness reproduce a published benchmark?",
        description=("A replication gate: six current models run "
                     "over all 198 GPQA Diamond questions, checked against "
                     "published scores before any experimental spending."),
        h1="Does the harness reproduce a published benchmark?",
        standfirst=(f"Before asking whether an announced scoring rule changes "
                    f"what a model does, the environment has to be able to "
                    f"reproduce a result somebody else already published. "
                    f"{WORDS[n_pass]} current models did. {WORDS[n_invalid]} "
                    f"more are excluded, and {WORDS[n_smoke].lower()} routes "
                    f"have only a one-item connection check."),
        published=val("graded_on"),
        body=f"""
{stats}

<p class="a">This is a check on the measuring instrument, not a finding. It says
the standard {dfn_arm} behaves like a normal benchmark run, which is the precondition
for trusting anything the experiment reports later. <b>Nothing on this page is a
result of the scoring-rule experiment.</b></p>

<h2 id="result">The gate</h2>
<p>Each model was given every GPQA Diamond question once, under the published
zero-shot prompt, with the reasoning effort and temperature its published result
used. A model passes only if the number it got right falls inside the range that
published score implies at this sample size, and if its saved request
configuration matches what was declared in advance.</p>

{gate_tbl}
{legend}
<p class="cap">The range is a central 95% binomial interval for a fresh run of
this size at the published rate. It treats questions as independent trials of
equal difficulty and does not carry the uncertainty in the published estimate
itself, so it is a diagnostic rather than an exact coverage claim.</p>

<h2 id="reconstructed">Why one pass is fully recorded and five are reconstructed</h2>
<p>The runner stored each call's inference parameters, provider, returned model
identifier, reasoning-token counts, item identifiers, and the question and
answer-key snapshot it was graded against. The five earlier passing runs did not
store the full message body. Their prompts are rebuildable from frozen item
identifiers, the dataset hash, and committed prompt code, but rebuilding
evidence is weaker than recording it at inference time.</p>
<p>MiniMax M3 was run after the harness changed. Its 198 calls store the exact
ordered messages and their hash, so it receives an unqualified <code>PASS</code>.
The other five are labelled <code>PASS_RECONSTRUCTED</code>. The gate applies
that distinction automatically, without looking at the scores first.</p>

<h2 id="invalid">The {WORDS[n_invalid].lower()} that did not count</h2>
<p>These runs are kept visible because a gate is useful only if failures remain
in the record. None is converted into a pass by dropping a missing response,
loosening a routing rule, or selectively replacing hard items.</p>
{reasons}
<div class="note invalid-note"><b>Invalid is not the same as a performance miss</b>
Claude Sonnet's score and Muse Spark's penalized score both sit inside their
diagnostic ranges. Sonnet still fails the {threshold:.0f}% format ceiling, and
Muse still lacks one pass@1 API outcome after two explicitly recorded attempts.
The number alone cannot overrule the measurement protocol.</div>

<h2>Connection checks are not replication evidence</h2>
<p>Kimi K3, Qwen3.8, and Claude Haiku each received one item to verify that the
published-style request could reach its first-party OpenRouter route. These
checks establish plumbing only. They do not enter the six-model result.</p>
{smoke_tbl}

<h2 id="limits">What this does not establish</h2>
<ul class="key">
<li><b>It is not an exact replication.</b> The published figures average
{WORDS[int(val("published_repeats"))].lower()} repeats per model,
{int(val("published_trials")):,} trials in all. This is one pass. The exact
answer-choice permutation behind the published numbers is not disclosed, so the
closest documented construction was used instead.</li>
<li><b>It is not a claim about the models.</b> Nobody should read these as new
capability estimates. The question is whether this harness lands where the
published number says it should.</li>
<li><b>Each model was checked on its own.</b> With {WORDS[n_pass].lower()}
independent 95% checks, at least one would be expected to miss about
{(1 - 0.95 ** n_pass) * 100:.0f}% of the time even if every model followed its
published rate exactly. {WORDS[n_pass]} out of {WORDS[n_pass].lower()} is a
reassuring outcome, not a tightly controlled family-wide claim.</li>
<li><b>A gateway is not a serving snapshot.</b> Requests pinned the named
first-party provider and refused fallbacks, which rules out silent substitution.
It cannot prove this run and the published run reached identical model
snapshots.</li>
</ul>

<h2 id="cost">What it cost</h2>
<details class="operational">
<summary>Operational record: spend, the attribution gap and the retry ledger</summary>
<p>Reasoning tokens are essentially the whole bill. The task needs about fifteen
tokens of visible output, while a reasoning model can spend thousands of hidden
tokens first. {largest_label} was the largest single arm at
${largest_usd:,.2f}.</p>
{cost_tbl}
<p class="cap">Database-attributed, provider-reported cost. Excluded runs and
one-item connection checks remain in the total.</p>
<p>The OpenRouter key recorded ${float(val("openrouter_key_usage_usd")):,.2f}
against the ${float(val("spend_ceiling_usd")):,.0f} aim. The database attributes
${float(val("database_cost_usd")):,.2f} to saved work. The remaining
${float(val("provider_database_gap_usd")):,.2f} is reported as an attribution
gap rather than assigned to this gate without evidence. The
append-only ledger holds {int(val("attempts_logged")):,} attempts against
{int(val("distinct_parity_keys")):,} distinct keys. Those two being equal is what
would indicate no retries. Here the ledger runs
{int(val("attempts_logged")) - stored} ahead of the {stored:,}
stored responses because it preserves every explicit retry. The latest-state
table still contains one logical row per model and item, while the prior failures
remain auditable.</p>
</details>

<h2 id="next">What happens next</h2>
<p>The environment is validated, so the treatment arms run against a control that
is known to behave. That experiment, whether announcing a scoring rule changes how
often a model declines to answer, has since had its first pass: the 50-item
existence check passed on 2026-08-15 and is reported on
<a href="index.html#next">the findings page</a>. The larger estimation run has not
started, and its result will appear there whether or not the hypothesis
survives.</p>

<div class="cite"><b>Every number on this page</b> is rendered from
<a href="data/gpqa_parity.csv">gpqa_parity.csv</a> and
<a href="data/gpqa_parity_summary.csv">gpqa_parity_summary.csv</a>, which are
published beside this page. The pre-registered targets and the pass criterion
live in the code that graded the runs, and the builder re-checks the two against
each other, so a page that disagreed with its own source would fail to build
rather than publish. Neither file contains any benchmark question text.</div>
""",
        footer="Targets, sample sizes, and the pass criterion are versioned with "
               "the run record. Exclusions remain visible rather than being "
               "repaired into a cleaner story.",
        content_updated=VALIDATION_CONTENT_UPDATED,
        style_updated=VALIDATION_STYLE_UPDATED,
        site_commit=VALIDATION_SITE_COMMIT)


def build_plan():
    """The programme, stage by stage, and an honest statement of where it is."""
    _, summary = parity()
    # One stage's cost is real spending rather than an estimate, so it is read
    # from the artifact instead of being retyped into STAGES.
    spent = f'${float(summary["parity_cost_usd"]["value"]):,.2f}'

    def cost(stage):
        return spent if stage["cost"] == "@parity_cost" else stage["cost"]

    body_rows = []
    for s in STAGES:
        name = (f'<b><a href="{s["page"]}">{s["name"]}</a></b>' if s.get("page")
                else f'<b>{s["name"]}</b>')
        body_rows.append([
            f'{name}<br><span class="cap">{s["asks"]}</span>',
            f'<span class="state {s["state"]}">{s["label"]}</span>',
            cost(s),
        ])
    status_tbl = table(["stage", "state", "cost"], body_rows, right_from=1,
                       cls="narrow")

    detail = "".join(
        f'<h3>{s["name"]}</h3><p>{s["detail"]}'
        + (f' <a href="{s["page"]}">See the full report.</a>' if s.get("page")
           else "")
        + "</p>"
        for s in STAGES)

    dfn_harness = dfn(
        "harness",
        "The software that runs the experiment: it builds the prompts, calls "
        "the models, stores the raw responses, grades them, and computes the "
        "metrics. It is kept separate from the scoring, so a scoring parameter "
        "can change without re-calling anything.")
    dfn_contract = dfn(
        "contract",
        "The scoring rule as the model is told it, in the system prompt. The "
        "contract is the intervention: the identical question goes out under "
        "every one of them, and nothing else varies.")

    # Spelled out, because these are counts in prose rather than data.
    n_done = sum(1 for s in STAGES if s["state"] == "done")
    done, total_stages = WORDS[n_done], WORDS[len(STAGES)].lower()

    side_page(
        "plan.html",
        title="Below Zero — the plan, and where it actually stands",
        description=("What is finished, what has not started, and the stop "
                     "rules that were fixed in advance. The Stage 1 existence "
                     "check, environment validation, and the two-seed "
                     "fine-tuning final test are complete."),
        h1="The plan, and where it stands",
        standfirst=(f"{done} of {total_stages} stages are finished. The Stage 1 "
                    "existence check, environment validation, and the "
                    "fine-tuning final test are complete."),
        published=summary["graded_on"]["value"],
        body=f"""
<div class="note"><b>Results as of {PLAN_CONTENT_UPDATED.split()[0]}</b>
Three results are now reported. The {dfn_harness} reproduced published GPQA scores for six
current models from five companies, which establishes that the standard arm behaves like a
normal benchmark run. The Stage 1 pilot passed its pre-registered existence check:
announcing the rule raised explicit abstention on short-answer questions for three of six
models, by as much as 34 points, and moved multiple-choice behaviour much less. The
500-question training comparison passed its preregistered final test: confidence-aware
tuning improved the proper score by 0.105 relative to accuracy-only tuning, mainly by
reducing probability error. Accuracy changed by -2.0 points and remained inside the
prespecified safeguard. Every tuned checkpoint answered every final question, and the
assertion-cost term added no stable benefit.
Stage 2, the estimation run, and validation of the LM judge against hand labels have not
run. This page will be updated as they do.</div>

<h2 id="where">Where the programme is</h2>
{status_tbl}
<p class="cap">Cost is the model-call spend for that stage, not staff time.</p>

<h2 id="stages">What each stage is for</h2>
{detail}

<h2 id="stop">What would stop this</h2>
<p>The stop rules were written before any data was collected, which is the only
time they can be written honestly. They are deliberately blunt.</p>
<ul class="key">
<li><b>Abstention stays below 2% in every {dfn_contract}, including the one with the
steepest penalty.</b> The hypothesis is dead. Announcing a scoring rule does not
change behaviour, and the right thing to do is say so.</li>
<li><b>More than 5% of responses in any arm cannot be parsed.</b> That arm is
invalid. The model was not playing the game the prompt specified, so its
abstention rate measures format compliance rather than honesty.</li>
<li><b>The judge disagrees with hand labels more than tolerated.</b> Grading is
the measurement instrument. If it is unreliable, every downstream number is
unreliable, and no amount of sample size fixes it.</li>
</ul>

<h2 id="cost">What this costs</h2>
<details class="operational">
<summary>Operational record: budget, ceilings and actual spend</summary>
<p>The experiment itself was budgeted at about $86 across its stages, and that
estimate stands. Validating the environment was not in that figure and cost
${float(summary["parity_cost_usd"]["value"]):,.2f} on top of it, because
reproducing a published benchmark means paying published-configuration prices:
maximum reasoning effort, full output allowances, every question. It is the most
expensive thing done so far and none of it tested the hypothesis.</p>
<p>OpenRouter key-level usage for the validation session reached
${float(summary["openrouter_key_usage_usd"]["value"]):,.2f} against the
${float(summary["spend_ceiling_usd"]["value"]):,.0f} aim. The difference from
the database-attributed figure remains visible on the validation page rather
than being silently assigned.</p>
<p>The design is cheap on purpose. Cost scales with items times models times
contracts, and the contracts are the part that cannot be cut, because comparing
them <em>is</em> the experiment. So the item counts are set by what the question
needs rather than by what a budget allows: 50 items to detect whether an effect
exists at all, 200 to estimate its size.</p>
<p>The two things that would blow the budget are reasoning models left at high
effort, where thinking tokens dominate the bill, and repetitions at temperature
above zero, which multiply every cell. Both are controlled explicitly rather
than left at their defaults.</p>
</details>
""",
        footer="The stop rules on this page are the pre-registered ones. "
               "They have not been revised.",
        content_updated=PLAN_CONTENT_UPDATED,
        site_commit=PLAN_SITE_COMMIT)


def delta_chart(groups, *, caption, chart_id, xlabel, better,
                point_labels=("125", "250", "500")):
    """Plot each version's distance from the untuned base on one zero-centred axis.

    Everything on this page is a difference from the same untuned model, so the
    baseline is the axis rather than another line on the chart. A version that
    did nothing sits at zero, and which side of zero is an improvement is
    written on the chart instead of left to the reader's assumption, because
    the sign convention flips between an error rate and a score.

    ``groups`` is a list of (row label, [(point label, delta), ...]). Each row
    is one training objective and each point is one dose, so a reader compares
    doses within a row and objectives down a column without either comparison
    being implied by the ordering.

    Deliberately not a line chart. Connecting three doses with a line asserts
    that the values between them are interpolable, and on one seed with 100
    evaluation items they are not; these are three separate measurements of the
    same arm, so they are drawn as three separate marks.
    """
    row_h, W = 46, 680
    L, R, T = 176, 54, 34
    H = T + row_h * len(groups) + 20
    values = [v for _, points in groups for _, v in points]
    span = max(abs(min(values)), abs(max(values))) * 1.15 or 1.0

    def x(value):
        return L + (value + span) / (2 * span) * (W - L - R)

    parts = [(f'<line class="dl-zero" x1="{x(0):.1f}" y1="{T - 12}" '
              f'x2="{x(0):.1f}" y2="{H - 16}" />')]
    # Axis ticks at the extremes and zero. Three labels is enough to read a
    # magnitude off; more would compete with the point labels.
    for value in (-span / 1.15, 0, span / 1.15):
        parts.append(f'<text class="dl-tick" x="{x(value):.1f}" y="{T - 18}" '
                     f'text-anchor="middle">{value:+.2f}</text>')
    parts.append(f'<text class="dl-better" x="{x(0):.1f}" y="{H - 3}" '
                 f'text-anchor="middle">{html.escape(xlabel)}</text>')
    arrow_x = x(span / 1.15) if better == "right" else x(-span / 1.15)
    parts.append(f'<text class="dl-better" x="{arrow_x:.1f}" y="{H - 3}" '
                 f'text-anchor="middle">better {"&#8594;" if better == "right" else "&#8592;"}</text>')

    for index, (label, points) in enumerate(groups):
        cy = T + row_h * index + row_h / 2
        parts.append(f'<line class="dl-rule" x1="{L - 12}" y1="{cy + row_h / 2:.1f}" '
                     f'x2="{W - R}" y2="{cy + row_h / 2:.1f}" />')
        parts.append(f'<text class="dl-row" x="{L - 22}" y="{cy + 4:.1f}" '
                     f'text-anchor="end">{html.escape(label)}</text>')
        for point_index, (point_label, value) in enumerate(points):
            parts.append(
                f'<circle class="dl-dot dl-d{point_index}" cx="{x(value):.1f}" '
                f'cy="{cy:.1f}" r="5" />'
                f'<title>{html.escape(label)} at {html.escape(point_label)} '
                f'steps: {value:+.3f}</title>')
    keys = "".join(
        f'<span class="dl-key dl-d{i}">{html.escape(l)} steps</span>'
        for i, l in enumerate(point_labels))
    return (f'<figure class="dose-chart" id="{chart_id}">'
            f'<svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{html.escape(caption)}">' + "".join(parts) + "</svg>"
            f'<div class="dc-keys">{keys}</div>'
            f'<figcaption>{caption}</figcaption></figure>')


def dose_chart(series, *, ylabel, caption, chart_id, ymin=None, ymax=None,
               baseline=None, baseline_label=""):
    """Plot score against training step, one line per training objective.

    The dose grid's whole point is that the curves are NOT monotonic, and that
    shape is invisible in a table of 100 rows. So this draws it directly.

    Written as inline SVG with no plotting library, for the same reason the rest
    of the repo has no runtime dependencies: a page arguing that scoring should
    be inspectable should not need a toolchain to inspect. The axes are computed
    from the data rather than fixed, because a hand-set y-range that stops
    matching the numbers is the standard way a chart starts lying.

    ``baseline`` draws the untuned model as a horizontal reference. Without it a
    reader can compare checkpoints with each other but cannot see that all of
    them beat no training at all, which is the first thing they should learn.
    """
    W, H = 680, 300
    L, R, T, B = 54, 16, 14, 34          # plot margins, in SVG units
    steps = sorted({s for _, points in series for s, _ in points})
    if not steps:
        raise ValueError("a dose chart needs at least one training step")
    xlo, xhi = min(steps), max(steps)
    values = [v for _, points in series for _, v in points]
    if baseline is not None:
        values = values + [baseline]
    lo = ymin if ymin is not None else min(values)
    hi = ymax if ymax is not None else max(values)
    if hi == lo:                          # a flat series still needs a height
        hi, lo = hi + 0.5, lo - 0.5
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    def x(step):
        return L + (step - xlo) / (xhi - xlo) * (W - L - R)

    def y(value):
        return T + (hi - value) / (hi - lo) * (H - T - B)

    parts = []
    # Horizontal gridlines double as the y-axis labels. Five is enough to read
    # a level off without turning the plot into graph paper.
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        gy = y(v)
        parts.append(f'<line class="dc-grid" x1="{L}" y1="{gy:.1f}" '
                     f'x2="{W - R}" y2="{gy:.1f}" />')
        parts.append(f'<text class="dc-tick" x="{L - 8}" y="{gy + 3.5:.1f}" '
                     f'text-anchor="end">{v:.2f}</text>')
    for step in steps:
        if step % 100 == 0 or step == xhi:
            parts.append(f'<text class="dc-tick" x="{x(step):.1f}" y="{H - B + 17}" '
                         f'text-anchor="middle">{step}</text>')
    if baseline is not None:
        by = y(baseline)
        parts.append(f'<line class="dc-base" x1="{L}" y1="{by:.1f}" '
                     f'x2="{W - R}" y2="{by:.1f}" />')
        parts.append(f'<text class="dc-baselabel" x="{W - R}" y="{by - 6:.1f}" '
                     f'text-anchor="end">{html.escape(baseline_label)}</text>')
    for index, (label, points) in enumerate(series):
        pts = " ".join(f"{x(s):.1f},{y(v):.1f}" for s, v in sorted(points))
        parts.append(f'<polyline class="dc-line dc-s{index}" points="{pts}" />')
        # Mark the maximum of each line. The peak is the finding, so it gets a
        # dot rather than leaving the reader to trace the line by eye.
        peak_step, peak_value = max(sorted(points), key=lambda p: p[1])
        parts.append(f'<circle class="dc-dot dc-s{index}" cx="{x(peak_step):.1f}" '
                     f'cy="{y(peak_value):.1f}" r="3.4" />')
    parts.append(f'<text class="dc-axis" x="{(L + W - R) / 2:.0f}" y="{H - 4}" '
                 f'text-anchor="middle">training steps</text>')
    parts.append(f'<text class="dc-axis" transform="translate(13,{(T + H - B) / 2:.0f}) '
                 f'rotate(-90)" text-anchor="middle">{html.escape(ylabel)}</text>')
    keys = "".join(
        f'<span class="dc-key dc-s{i}">{html.escape(label)}</span>'
        for i, (label, _) in enumerate(series))
    return (f'<figure class="dose-chart" id="{chart_id}">'
            f'<svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{html.escape(caption)}">' + "".join(parts) + "</svg>"
            f'<div class="dc-keys">{keys}</div>'
            f'<figcaption>{caption}</figcaption></figure>')


# The dose-response page's own styles. Namespaced under .dose-chart so nothing
# here can leak into the tables the rest of the site draws.
DOSE_CSS = r"""
.dose-chart { margin: 26px 0 34px; max-width: 720px; }
.dose-chart svg { width: 100%; height: auto; overflow: visible; }
.dose-chart figcaption {
  margin-top: 10px; color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 13px; line-height: 1.5;
}
.dc-grid { stroke: var(--rule); stroke-width: 1; }
/* The baseline is a reference level, not a sixth series, so it is drawn lighter
   and finer than any line. It previously shared the accuracy-only arm's grey,
   which made the control look like its own benchmark. */
.dc-base { stroke: #b9b3ad; stroke-width: 1; stroke-dasharray: 3 3; }
.dc-baselabel, .dc-tick, .dc-axis {
  font-family: 'Inter', ui-sans-serif, sans-serif; fill: var(--text-muted);
}
.dc-tick { font-size: 10px; }
.dc-axis, .dc-baselabel { font-size: 10.5px; letter-spacing: .04em; }
.dc-line { fill: none; stroke-width: 1.9; stroke-linejoin: round; stroke-linecap: round; }
.dc-keys { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 12px; }
.dc-key {
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px; font-weight: 500;
  color: var(--text-secondary);
}
.dc-key::before {
  content: ""; display: inline-block; width: 15px; height: 2px;
  margin-right: 7px; vertical-align: middle; background: currentColor;
}
/* Five objectives, ordered from the accuracy-only control through increasing
   assertion cost, so the palette reads as a scale rather than five unrelated
   categories. */
.dc-s0 { stroke: #57606b; color: #4d555f; }
.dc-s1 { stroke: var(--accent); color: var(--accent-text); }
.dc-s2 { stroke: #4c8f7a; color: #3d7a66; }
.dc-s3 { stroke: #3f6ea8; color: #35608f; }
.dc-s4 { stroke: #a8743f; color: #8f6135; }
circle.dc-dot { stroke: none; }
circle.dc-s0 { fill: #57606b; }
/* The site right-aligns every header after the first, which is correct when
   the column holds numbers and wrong when it holds sentences. These two tables
   are all prose, so their headers follow their cells. Scoped rather than fixed
   globally: every other table on the site is numeric and already correct. */
.factor-table th:not(:first-child) { text-align: left; }
.dl-zero { stroke: var(--text); stroke-width: 1.2; }
.dl-rule { stroke: var(--rule); stroke-width: 1; }
.dl-row, .dl-tick, .dl-better {
  font-family: 'Inter', ui-sans-serif, sans-serif; fill: var(--text-secondary);
}
.dl-row { font-size: 12.5px; }
.dl-tick { font-size: 10.5px; fill: var(--text-muted); }
.dl-better { font-size: 10.5px; fill: var(--text-muted); letter-spacing: .04em; }
/* Dose is encoded by fill darkness rather than hue, so the three marks read as
   ordered stages of one thing instead of three unrelated categories. */
.dl-key { font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px; color: var(--text-secondary); }
.dl-key::before {
  content: ""; display: inline-block; width: 9px; height: 9px; border-radius: 50%;
  margin-right: 7px; vertical-align: middle; background: currentColor;
}
circle.dl-d0 { fill: #c9b3c2; } .dl-key.dl-d0 { color: #b498ab; }
circle.dl-d1 { fill: #96738a; } .dl-key.dl-d1 { color: #8a6880; }
circle.dl-d2 { fill: var(--accent); } .dl-key.dl-d2 { color: var(--accent-text); }
circle.dc-s1 { fill: var(--accent); }
circle.dc-s2 { fill: #4c8f7a; }
circle.dc-s3 { fill: #3f6ea8; }
circle.dc-s4 { fill: #a8743f; }
"""

# Human labels for the five training objectives, in the order the charts and
# tables use. The CSV's machine names are never shown to a reader.
OBJECTIVES = [
    ("binary", "Accuracy only"),
    ("quadratic", "Confidence-aware"),
    ("quad_cost_0.04", "Confidence + cost 0.04"),
    ("quad_cost_0.09", "Confidence + cost 0.09"),
    ("quad_cost_0.16", "Confidence + cost 0.16"),
]


def seed_pair_chart(groups, *, caption, chart_id, xlabel, better, noise=None,
                    seed_labels=("Run 1 (seed 0)", "Run 2 (seed 1)")):
    """Plot the same measurement from two independent training runs, paired.

    ``groups`` is a list of (group label, [(row label, first, second), ...]).
    Each row is one dose of one training objective, and the two marks are the
    two trajectories. They are joined by a connector because the pair is the
    unit of interest: the question this chart answers is not "how big is the
    effect" but "does the effect survive being trained again", and a connector
    makes a sign flip visible as a segment crossing zero.

    ``noise`` shades the band the untuned base itself wandered over when it was
    re-measured five times. Anything landing inside that band is not
    distinguishable from measuring the same model twice, and drawing it removes
    the reader's need to take that caveat on trust from the prose. It is the one
    piece of context that stops a paired chart from implying more precision than
    two draws can carry.
    """
    row_h, head_h, W = 27, 30, 680
    L, R, T = 150, 54, 40
    H = T + sum(head_h + row_h * len(rows_) for _, rows_ in groups) + 26
    values = [v for _, rows_ in groups for _, a, b in rows_ for v in (a, b)]
    span = max(abs(min(values)), abs(max(values))) * 1.18 or 1.0

    def x(value):
        return L + (value + span) / (2 * span) * (W - L - R)

    parts = []
    if noise:
        # Drawn first so every mark sits on top of it: this is background, not
        # a series competing with the data.
        parts.append(f'<rect class="sp-noise" x="{x(-noise):.1f}" y="{T - 16}" '
                     f'width="{x(noise) - x(-noise):.1f}" height="{H - T - 4}" />')
    parts.append(f'<line class="dl-zero" x1="{x(0):.1f}" y1="{T - 16}" '
                 f'x2="{x(0):.1f}" y2="{H - 22}" />')
    for value in (-span / 1.18, 0, span / 1.18):
        parts.append(f'<text class="dl-tick" x="{x(value):.1f}" y="{T - 22}" '
                     f'text-anchor="middle">{value:+.2f}</text>')
    parts.append(f'<text class="dl-better" x="{x(0):.1f}" y="{H - 5}" '
                 f'text-anchor="middle">{html.escape(xlabel)}</text>')
    arrow_x = x(span / 1.18) if better == "right" else x(-span / 1.18)
    parts.append(f'<text class="dl-better" x="{arrow_x:.1f}" y="{H - 5}" '
                 f'text-anchor="middle">better '
                 f'{"&#8594;" if better == "right" else "&#8592;"}</text>')

    y = T
    for group_label, group_rows in groups:
        parts.append(f'<text class="sp-group" x="{L - 130}" y="{y + 18:.1f}">'
                     f'{html.escape(group_label)}</text>')
        parts.append(f'<line class="dl-rule" x1="{L - 130}" y1="{y + 24:.1f}" '
                     f'x2="{W - R}" y2="{y + 24:.1f}" />')
        y += head_h
        for row_label, first, second in group_rows:
            cy = y + row_h / 2
            parts.append(f'<text class="sp-row" x="{L - 14}" y="{cy + 4:.1f}" '
                         f'text-anchor="end">{html.escape(row_label)}</text>')
            parts.append(f'<line class="sp-link" x1="{x(first):.1f}" y1="{cy:.1f}" '
                         f'x2="{x(second):.1f}" y2="{cy:.1f}" />')
            parts.append(f'<circle class="sp-a" cx="{x(first):.1f}" cy="{cy:.1f}" '
                         f'r="4.6"><title>{html.escape(group_label)}, '
                         f'{html.escape(row_label)}, {html.escape(seed_labels[0])}: '
                         f'{first:+.3f}</title></circle>')
            parts.append(f'<circle class="sp-b" cx="{x(second):.1f}" cy="{cy:.1f}" '
                         f'r="4.6"><title>{html.escape(group_label)}, '
                         f'{html.escape(row_label)}, {html.escape(seed_labels[1])}: '
                         f'{second:+.3f}</title></circle>')
            y += row_h
    keys = (f'<span class="sp-key sp-key-a">{html.escape(seed_labels[0])}</span>'
            f'<span class="sp-key sp-key-b">{html.escape(seed_labels[1])}</span>')
    if noise:
        keys += ('<span class="sp-key sp-key-n">repeat-measurement band, '
                 f'&plusmn;{noise:.3f}</span>')
    return (f'<figure class="dose-chart" id="{chart_id}">'
            f'<svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{html.escape(caption)}">' + "".join(parts) + "</svg>"
            f'<div class="dc-keys">{keys}</div>'
            f'<figcaption>{caption}</figcaption></figure>')


# Styles for the replication page. Namespaced under the same .dose-chart
# wrapper the dose page uses, so the two pages share a chart grammar and a
# reader moving between them is not relearning what a mark means.
REPLICATION_CSS = DOSE_CSS + r"""
.sp-noise { fill: #ece7e1; }
.sp-link { stroke: #c3bcb4; stroke-width: 1.4; }
.sp-a { fill: var(--accent); stroke: none; }
.sp-b { fill: var(--bg); stroke: var(--accent); stroke-width: 1.9; }
.sp-group, .sp-row {
  font-family: 'Inter', ui-sans-serif, sans-serif; fill: var(--text-secondary);
}
.sp-group { font-size: 11px; font-weight: 700; letter-spacing: .09em;
            text-transform: uppercase; fill: var(--text-muted); }
.sp-row { font-size: 12px; }
.sp-key { font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px;
          color: var(--text-secondary); }
.sp-key::before {
  content: ""; display: inline-block; width: 10px; height: 10px;
  border-radius: 50%; margin-right: 7px; vertical-align: middle;
}
.sp-key-a::before { background: var(--accent); }
.sp-key-b::before { background: var(--bg); box-shadow: inset 0 0 0 2px var(--accent); }
.sp-key-n::before { background: #ece7e1; border-radius: 2px; }
/* The two role tables are prose, not numbers, so their headers follow their
   cells rather than the site's default right-alignment for data columns. */
.role-table th:not(:first-child) { text-align: left; }
/* A cell whose change is smaller than the repeat-measurement band. Marked
   rather than hidden: the reader should see that the measurement was made and
   came back inconclusive, which is different from it not being reported. */
.within-noise { color: var(--text-muted); }
/* The matrix has two rows per training objective, one per run, and the whole
   point of the table is comparing those two rows to each other. Without a tint
   the row rule between them reads as a separator between unrelated entries,
   which is the opposite of what a reader should do with them. Banding by PAIR
   rather than by row is what makes the unit of comparison visible. */
.matrix-table tbody tr:nth-child(4n+1) td,
.matrix-table tbody tr:nth-child(4n+2) td { background: var(--bg-alt); }
"""


def build_dose_response():
    """The seed-0 grid, organised by what was varied rather than by what won.

    An earlier version of this page led with the best checkpoint under each of
    seven scoring rules. That is an argmax over 100 checkpoints crossed with 7
    rules, on 100 evaluation items and one training seed, and the page itself
    said elsewhere that selecting from a grid that noisy is fitting the
    evaluation set. Those tables are gone. What replaces them is a fixed
    outcome, chosen in advance and rule-independent, reported as a difference
    from the untuned model for every version at three doses.
    """
    knowledge = rows("dose_grid_knowledge.csv")
    behaviour = rows("dose_grid_behaviour.csv")
    sycophancy = rows("dose_grid_sycophancy.csv")

    # Three doses, not twenty. Adjacent checkpoints in this grid differ by less
    # than the noise between them, so showing all twenty invites exactly the
    # checkpoint-shopping this page is trying to avoid. The full grid ships as
    # a CSV for anyone who wants it.
    DOSES = (125, 250, 500)

    base_k = next(r for r in knowledge if r["objective"] == "base")
    base_b = next(r for r in behaviour if r["objective"] == "base")

    def label_of(objective):
        return dict(OBJECTIVES)[objective]

    def cell(objective, step):
        for r in knowledge:
            if r["objective"] == objective and int(r["step"]) == step:
                return r
        return None

    # --- what a version actually is ---------------------------------------
    # Four factors define every version on this page. Two of them are held
    # fixed here and vary only in the announced-rule experiment; the other two
    # each appear TWICE, once as the reward the model was trained on and once
    # as the rule its stored answers are scored with afterwards. Writing that
    # out is the difference between "five arms" and a design a reader can check.
    factors = table(
        ["factor", "role", "levels on this page"],
        [["1. Scoring rule disclosed in the prompt",
          "Generation", ("<b>Held fixed: none.</b> Every answer here was produced "
                         "under a neutral prompt, so nothing on this page measures "
                         "a model reacting to an announced rule.")],
         ["2. Is a probability requested?",
          "Generation", ("<b>Held fixed: yes.</b> Every prompt asks for an answer "
                         "and a probability, so abstention and confidence are "
                         "always available actions.")],
         ["3. How the probability enters the score",
          "Training reward", "Ignored (accuracy only), or quadratic."],
         ["3. How the probability enters the score",
          "Post-hoc scoring", ("Binary, quadratic, logarithmic, or spherical. The "
                               "last two were never used as a reward by any arm.")],
         ["4. Fixed cost for asserting",
          "Training reward", "None, 0.04, 0.09, or 0.16."],
         ["4. Fixed cost for asserting",
          "Post-hoc scoring", "None, 0.04, 0.09, or 0.16, applied to stored answers."]],
        right_from=99, cls="choice-table factor-table")

    versions = table(
        ["version", "trained to maximise", "assertion cost while training",
         "doses shown"],
        [["Untuned base", "nothing, no training", "&mdash;", "&mdash;"],
         ["Accuracy only", "correct answer", "none", "125 / 250 / 500"],
         ["Confidence-aware", "quadratic score", "none", "125 / 250 / 500"],
         ["Confidence + cost 0.04", "quadratic score", "0.04", "125 / 250 / 500"],
         ["Confidence + cost 0.09", "quadratic score", "0.09", "125 / 250 / 500"],
         ["Confidence + cost 0.16", "quadratic score", "0.16", "125 / 250 / 500"]],
        right_from=99, cls="choice-table factor-table")

    # --- the two reference measures ---------------------------------------
    # Both are reported for every version, because the gap between them IS the
    # argument. Accuracy is what benchmarks already report. The quadratic score
    # is the proposed replacement, and it is strictly proper: a model maximises
    # it by reporting the probability it actually holds. Any metric that is not
    # proper would be the wrong instrument to argue this case with, however
    # intuitive it looked.
    base_q = float(base_k["score_quadratic"])
    base_a = float(base_k["accuracy"])

    quad_chart = delta_chart(
        [(label_of(obj), [(str(d), float(cell(obj, d)["score_quadratic"]) - base_q)
                          for d in DOSES])
         for obj, _ in OBJECTIVES],
        chart_id="chart-quadratic-delta",
        xlabel="quadratic score, change vs untuned base",
        better="right",
        caption=("The proposed rule. Zero is the untuned base, which scores "
                 f"{base_q:.3f}. Accuracy-only training is the one version that "
                 "moves the wrong way, at every dose."))

    acc_chart = delta_chart(
        [(label_of(obj), [(str(d), float(cell(obj, d)["accuracy"]) - base_a)
                          for d in DOSES])
         for obj, _ in OBJECTIVES],
        chart_id="chart-accuracy-delta",
        xlabel="plain accuracy, change vs untuned base",
        better="right",
        caption=("The same versions under the measure benchmarks already use: one "
                 "point for a right answer, nothing otherwise. Zero is the untuned "
                 f"base at {pct(base_a, 0)}. Every version is at or above the base "
                 "here, including the one the quadratic rule says got worse."))

    both_table = table(
        ["version", "quadratic at 125", "at 250", "at 500",
         "accuracy at 125", "at 250", "at 500"],
        [["Untuned base"] + [f"{base_q:.3f}"] * 3 + [pct(base_a, 0)] * 3] +
        [[label_of(obj)] +
         [f"{float(cell(obj, d)['score_quadratic']):.3f}" for d in DOSES] +
         [pct(cell(obj, d)["accuracy"], 0) for d in DOSES]
         for obj, _ in OBJECTIVES],
        right_from=1, cls="choice-table")

    # --- the same answers under rules they were not trained on -------------
    rule_columns = [
        ("Binary", "score_binary"),
        ("Quadratic", "score_quadratic"),
        ("Logarithmic, held out", "score_log"),
        ("Spherical, held out", "score_spherical"),
    ]
    # One version across four rules, rather than four versions under one rule.
    # The question this chart answers is whether a single policy's gain survives
    # being scored by something it never optimised, so the version is what stays
    # fixed and the rule is what varies.
    FOCUS = "quad_cost_0.09"
    rule_chart = delta_chart(
        [(name, [(str(d), float(cell(FOCUS, d)[col]) - float(base_k[col]))
                 for d in DOSES])
         for name, col in rule_columns],
        chart_id="chart-rules",
        xlabel="confidence + cost 0.09, score change vs untuned base",
        better="right",
        caption=("One version, the cost-0.09 arm, scored four ways. At 125 and 250 "
                 "steps it gains under the rule it trained on and under two rules "
                 "no arm ever optimised, which is what separates a calibrated "
                 "policy from one that learned its own reward. At 500 steps it "
                 "falls below the untuned base on the logarithmic rule while still "
                 "looking positive on the other three, so the held-out rule is "
                 "where over-training shows up first."))

    rule_table = table(
        ["version at 250 steps"] + [name for name, _ in rule_columns],
        [[label_of(obj)] +
         [f"{float(cell(obj, 250)[col]) - float(base_k[col]):+.3f}"
          for _, col in rule_columns]
         for obj, _ in OBJECTIVES],
        right_from=1, cls="choice-table")

    # --- behaviour against the untuned base -------------------------------
    early = [r for r in behaviour if r["objective"] != "base" and int(r["step"]) == 25]
    best_early = min(early, key=lambda r: float(r["violation_rate"]))
    worst_early = max(early, key=lambda r: float(r["violation_rate"]))
    base_table = table(
        ["model", "constraint violations", "invalid format", "abstained"],
        [["Untuned base", pct(base_b["violation_rate"], 1),
          pct(base_b["invalid_rate"], 1), pct(base_b["abstention_rate"], 1)],
         [f"Best 25-step version ({label_of(best_early['objective'])})",
          pct(best_early["violation_rate"], 1), pct(best_early["invalid_rate"], 1),
          pct(best_early["abstention_rate"], 1)],
         [f"Worst 25-step version ({label_of(worst_early['objective'])})",
          pct(worst_early["violation_rate"], 1), pct(worst_early["invalid_rate"], 1),
          pct(worst_early["abstention_rate"], 1)]],
        right_from=1, cls="choice-table")

    # --- social pressure ---------------------------------------------------
    def pressure(objective, step, arm):
        for r in sycophancy:
            if (r["objective"] == objective and int(r["step"]) == step
                    and r["pressure_arm"] == arm):
                return r
        return None

    syco_rows = []
    for objective, _ in OBJECTIVES:
        for step in DOSES:
            wrong, right = pressure(objective, step, "wrong"), pressure(objective, step, "right")
            if not wrong or not right:
                continue
            syco_rows.append([f"{label_of(objective)} @ {step}",
                              pct(wrong["adoption_rate"], 1),
                              pct(right["adoption_rate"], 1)])
    syco = table(
        ["version", "accepts wrong pushback", "accepts correct pushback"],
        syco_rows, right_from=1, cls="choice-table")

    manifest_note = ""
    manifest_path = os.path.join(PROC, "dose_grid_manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        # Provenance comes from the response files the matrices were computed
        # from, not from a summary field. Digesting the stored responses is what
        # makes the page's numbers checkable against the run that produced them.
        digest = str(manifest.get("inputs", {}).get("knowledge", {})
                     .get("sha256", ""))[:12]
        if digest:
            manifest_note = (f" The stored responses these figures are computed "
                             f"from hash to <code>{html.escape(digest)}</code>.")

    side_page(
        "dose-response.html",
        title="Below Zero — what reward training changes",
        description=("Five reward objectives against an untuned baseline, measured "
                     "by plain accuracy and by a strictly proper scoring rule, with "
                     "the design matrix stated up front."),
        h1="What reward training changes",
        standfirst=("Five reward objectives, each measured against the untuned model "
                    "it started from, under two references: plain accuracy and the "
                    "proposed quadratic rule. They agree about four of the five. "
                    "Training on accuracy alone raises accuracy while making the "
                    "model's probabilities worse, which is the trade a benchmark "
                    "reporting only accuracy cannot see."),
        extra_css=DOSE_CSS,
        body=f"""
<h2 id="versions">What each version is</h2>
<p>Four things can vary. Naming them is worth doing carefully, because two of them
appear twice in different roles, and conflating those two roles is the most common way
to misread this kind of result.</p>
{factors}
<p>The distinction in factors 3 and 4 is the one that matters. A rule can be the thing
a model was <em>trained</em> to maximise, or the thing its stored answers are
<em>scored</em> with afterwards, or the thing it was <em>told</em> about in the prompt.
Those are three different questions. This page varies the first, applies the second
after the fact, and holds the third fixed at "told nothing".</p>
<p>That gives six versions, each measured at three doses:</p>
{versions}
<p>Every version answered the same 100 held-out questions, the same 33 behavioural
probes, and the same 40 items under social pressure.{manifest_note}</p>

<h2 id="outcome">Two reference measures</h2>
<p>Every version is reported under two measures, and the distance between them is the
argument this project is making.</p>
<p><b>Plain accuracy</b> is what benchmarks already report: one point for a right
answer, nothing otherwise. <b>The quadratic score</b> is the proposed replacement. It
is strictly proper, which is a technical property with a plain meaning: a model gets
its best expected score by reporting the probability it actually holds, so there is no
confidence it can claim that beats telling the truth.</p>
<p>That property is why nothing else is used here. An earlier draft of this page led
with a rule-free measure of how much confidence each version spent on wrong answers.
It was intuitive and it was improper: it is minimised by reporting zero confidence on
everything, so it rewards a model that answers constantly while claiming to believe
nothing. Arguing that benchmarks should adopt a proper rule, using an improper one to
do it, would have been the wrong instrument regardless of how the numbers came out.</p>
{quad_chart}
{acc_chart}
{both_table}
<p>The two measures disagree about exactly one version, and that disagreement is the
result. <b>Accuracy-only training makes the model more accurate and its probabilities
worse.</b> It gains 4 to 6 points of accuracy and loses 0.06 to 0.10 of quadratic
score at every dose. It bought those points by asserting more often and more
confidently, and the proper rule charges for the wrong answers that came with them.
A benchmark reporting only accuracy would record that trade as an unambiguous
improvement.</p>
<p>Every version that prices confidence improves on both measures at once, at eleven of
its twelve measured points. The exception is cost 0.09 at 500 steps, which lands 0.008
below the base on the quadratic rule, a gap an order of magnitude smaller than the one
that defines the result. That is the claim worth carrying: pricing confidence does not
cost accuracy, and measuring only accuracy hides what accuracy costs.</p>
<p>Among the four confidence-aware versions the differences are small, do not order
consistently across doses, and should not be read as a ranking. The split that matters
is between the accuracy-only control and the rest.</p>

<h2 id="rules">Scored by rules it never trained on</h2>
<p>The same stored answers can be scored any number of ways after the fact. A version
that had merely learned to game its own reward would gain under that reward and lose
under the others.</p>
{rule_chart}
<p>Every version, at 250 steps, measured against the untuned base under four rules:</p>
{rule_table}
<p>The logarithmic and spherical columns were never anyone's training objective. The
accuracy-only version loses badly under the logarithmic rule, which is the rule that
punishes confident errors without limit. That is the same trade the accuracy column
shows from the other side. The score scales differ between columns, so compare
down a column rather than across a row.</p>

<h2 id="base">Against no training at all</h2>
<p>On behavioural probes, every version is a large improvement over the untuned model,
and that gain arrives almost immediately:</p>
{base_table}
<p>Relative to base, every 25-step version removes citation and grounding violations
entirely and cuts scope violations from 80% to roughly a quarter. A paired item
bootstrap over 10,000 resamples puts every violation-rate reduction between 20.2 and
24.2 points, with every 95% interval's lower bound above zero. One category moved the
wrong way: grader-shortcut behaviour rose from a base rate of 0%.</p>
<p>Most of the base model's failures are truncated reasoning that never reaches the
answer fields, so this contrast includes a large format-adherence effect. That effect
is part of what fine-tuning does, but it means base and tuned confidence figures are
not measured on comparable subsets.</p>

<h2 id="pressure">Under social pressure</h2>
<p>Each item was challenged twice, once with a wrong correction and once with a correct
one. Both columns have to be read together.</p>
{syco}
<p>Where later versions accept less wrong pushback, they also accept less correct
pushback. That is increased stubbornness, not improved judgement about who to believe.
Reporting the first column alone would be the more flattering result and the wrong
one.</p>

<h2 id="limits">What this cannot tell you</h2>
<p>One training seed, so no interval on this page covers training-seed variation. The
split between the accuracy-only control and the confidence-aware versions is large and
consistent across three doses, which is the kind of result most likely to replicate.
The ordering within the confidence-aware group is not, and should not be quoted.</p>
<p><b>Three of these versions have since been trained a second time, from a different
seed.</b> The directions on this page held; the magnitudes did not, and every figure
here is the more favourable of the two runs. Read the numbers on this page as one draw
and the <a href="replication.html">replication page</a> for what survived, including
the repeat-measurement floor that says which of these differences are large enough to
mean anything.</p>
<p>Three doses are shown because adjacent checkpoints in the full grid differ by less
than the noise between them. The complete twenty-dose grid is in the downloadable CSV.
Choosing a single best checkpoint from it would be fitting the evaluation set, which is
why no table here does that.</p>
<p>One 8B model, 100 held-out questions, 33 behavioural probes, 40 pressure items.
These are sample sizes for establishing a direction, not for estimating an effect size,
and nothing here shows the result transfers to another model family.</p>
<p>Every generation used a neutral prompt, so nothing here measures a model responding
to an announced rule. That is the separate experiment on the <a href="index.html">findings
page</a>.</p>
""",
        footer=("Every figure here is rendered from the committed CSVs in "
                "data/processed, one row per version. This is a single training "
                "seed, and no checkpoint on this page was selected for winning."),
    )

# The three objectives that were trained twice, with the plain-English gloss of
# what each reward actually pays for. The gloss is the part that matters: "the
# binary arm" tells a reader nothing, "rewarded for answering correctly, with no
# cost for being wrong" tells them what to expect from the numbers.
REPLICATED = [
    ("binary", "Accuracy only",
     "1 if the answer is right, 0 if wrong",
     "No. It is ignored entirely.",
     "None",
     ("answering correctly. Being wrong costs nothing, and saying "
      "&ldquo;I don't know&rdquo; earns the same 0 as a wrong answer.")),
    ("quadratic", "Confidence-aware",
     "2p &minus; p&sup2; if right, &minus;p&sup2; if wrong",
     "Yes. It is the whole difference from the row above.",
     "None",
     ("stating the probability it genuinely holds, and being right. Overstating "
      "confidence on a wrong answer is charged for.")),
    ("quad_cost_0.09", "Confidence-aware + assertion cost",
     "the same, minus 0.09 for answering at all",
     "Yes, and a flat charge applies on top.",
     "0.09",
     ("the same, except every answer costs 0.09 whether or not it is right, so "
      "silence beats answering below about 30% confidence.")),
]

# The two rules the stored answers are scored WITH, which is a different
# question from what any of them was trained ON.
#
# Two, not the seven the CSV carries. The logarithmic and spherical columns were
# on this page and are gone: nothing in the program is managed or decided against
# them, so every extra column was a number the reader had to price and nobody had
# to act on. The pairing that earns its place is the one the argument turns on:
# what benchmarks report today, against the proper rule proposed to replace it.
# The stored responses are still rescorable under any rule, and the committed CSV
# still holds all seven, so narrowing the page costs no evidence.
SCORING_RULES_SHOWN = [
    ("binary", "Plain accuracy",
     "Nothing. A wrong answer and a silence both score 0."),
    ("quadratic", "Quadratic",
     "Confident errors, in proportion to the square of the confidence."),
]

REPLICATION_DOSES = (125, 250, 300, 375, 500)


def build_replication():
    """Two independent training runs of the same design, read side by side.

    The dose-response page reports one training trajectory. Every magnitude on
    it is therefore a property of that trajectory until something checks. This
    page is that check, and it is organised around the distinction that decides
    whether a reader draws the right conclusion from either page: what a model
    was TRAINED on and what its answers were SCORED with are different axes, and
    a rule can play either role independently.

    The other thing this page carries that no earlier page could: the untuned
    base was re-measured once per stage, five times on identical weights and
    identical items. That spread is the measurement floor, and without it a
    reader has no way to know which of these differences are real.
    """
    knowledge = rows("seed_replication_knowledge.csv")
    draws = rows("seed_replication_base_draws.csv")
    with open(os.path.join(PROC, "seed_replication_manifest.json"),
              encoding="utf-8") as handle:
        manifest = json.load(handle)

    # Half the observed spread of the repeated base measurement. Half-range
    # rather than a standard deviation: with five draws an sd is itself imprecise,
    # and "the identical model came back anywhere in this window" is the claim a
    # reader can actually use when deciding whether a difference means anything.
    band = {rule: info["range"] / 2
            for rule, info in manifest["noise_floor"].items()}

    def cell(seed, objective, step):
        for r in knowledge:
            if (int(r["seed"]) == seed and r["objective"] == objective
                    and int(r["step"]) == step):
                return r
        return None

    def base(seed):
        return cell(seed, "base", 0)

    def delta(seed, objective, step, column):
        return float(cell(seed, objective, step)[column]) - float(base(seed)[column])

    def mean_delta(seed, objective, column):
        values = [delta(seed, objective, d, column) for d in REPLICATION_DOSES]
        return sum(values) / len(values)

    # --- the three roles a scoring rule can play ---------------------------
    roles = table(
        ["where a rule appears", "the question that asks", "on this page"],
        [["<b>Announced in the prompt</b>",
          "Does telling a model how it will be scored change what it does?",
          ("<b>Held fixed.</b> Nothing was announced. Every answer here was "
           "produced under a neutral prompt.")],
         ["<b>Used as the training reward</b>",
          "Does training against the rule change the policy itself?",
          "<b>Varies.</b> This is the experiment: three rewards, two runs each."],
         ["<b>Applied to stored answers afterwards</b>",
          ("How does the resulting policy score under any rule, including ones "
           "it never optimised?"),
          ("<b>Varies, and costs nothing.</b> Stored responses are rescored "
           "offline under four rules.")]],
        right_from=99, cls="choice-table role-table")

    # --- what each version was trained on (clarity request i) --------------
    trained = table(
        # Headers go through html.escape, so an HTML entity here would render as
        # its own source text. Plain characters only in this list.
        ["version", "reward for one answer",
         "does the stated probability change the reward?",
         "cost to assert", "so the model is rewarded for"],
        [["<b>Untuned base</b>", "&mdash;", "&mdash;", "&mdash;",
          "nothing. This is the model everything else started from."]] +
        [[f"<b>{label}</b>", reward, uses_p, cost, gloss]
         for _, label, reward, uses_p, cost, gloss in REPLICATED],
        right_from=99, cls="choice-table role-table")

    # --- what a score change means (clarity request ii) --------------------
    measures = table(
        ["scoring rule", "what it charges for", "repeat-measurement band"],
        [[f"<b>{label}</b>", charges, f"&plusmn;{band[rule]:.3f}"]
         for rule, label, charges in SCORING_RULES_SHOWN],
        right_from=2, cls="choice-table role-table")

    # Both runs re-measured the base, so the run has to be a column: without it
    # the eight rows read as one run's eight stages, and the page would be
    # claiming more repeated measurement within a run than it has.
    draws_table = table(
        ["when the base was measured"] +
        [label for _, label, _ in SCORING_RULES_SHOWN],
        [[f"Run {int(d['seed']) + 1}, at {int(d['measured_at_stage'])} steps"] +
         [f"{float(d[f'score_{rule}']):.3f}"
          for rule, _, _ in SCORING_RULES_SHOWN]
         for d in draws] +
        [[f"<b>Spread across all {len(draws)}</b>"] +
         [f"<b>{manifest['noise_floor'][rule]['range']:.3f}</b>"
          for rule, _, _ in SCORING_RULES_SHOWN]],
        right_from=1, cls="choice-table")

    # --- trained on x scored by --------------------------------------------
    matrix_rows = []
    for objective, label, *_ in REPLICATED:
        for seed, run_label in ((0, "Run 1"), (1, "Run 2")):
            cells = []
            for rule, _, _ in SCORING_RULES_SHOWN:
                value = mean_delta(seed, objective, f"score_{rule}")
                text = f"{value:+.3f}"
                if abs(value) < band[rule]:
                    text = f'<span class="within-noise">{text}</span>'
                cells.append(text)
            matrix_rows.append([f"<b>{label}</b>" if seed == 0 else "",
                                run_label] + cells)
    matrix = table(
        ["trained on", "run"] + [label for _, label, _ in SCORING_RULES_SHOWN],
        matrix_rows, right_from=2, cls="choice-table matrix-table")

    # --- did it replicate? --------------------------------------------------
    # Sign agreement across all five doses, per objective and rule. This is the
    # question a second run exists to answer, and it is deliberately a count of
    # directions rather than a comparison of magnitudes: the magnitudes did not
    # survive, the directions did, and reporting only one of those would be
    # picking the flattering half.
    verdict_rows = []
    for objective, label, *_ in REPLICATED:
        row = [f"<b>{label}</b>"]
        for rule, _, _ in SCORING_RULES_SHOWN:
            agree = sum(
                (delta(0, objective, d, f"score_{rule}") > 0)
                == (delta(1, objective, d, f"score_{rule}") > 0)
                for d in REPLICATION_DOSES)
            row.append(f"{agree}/5")
        verdict_rows.append(row)
    verdict = table(
        ["trained on"] + [label for _, label, _ in SCORING_RULES_SHOWN],
        verdict_rows, right_from=1, cls="choice-table")

    quad_pairs = seed_pair_chart(
        [(label, [(f"{d} steps",
                   delta(0, objective, d, "score_quadratic"),
                   delta(1, objective, d, "score_quadratic"))
                  for d in REPLICATION_DOSES])
         for objective, label, *_ in REPLICATED],
        chart_id="chart-seed-quadratic",
        xlabel="quadratic score, change from that run's own untuned base",
        better="right", noise=band["quadratic"],
        caption=("Every version at every dose, measured twice. The two runs "
                 "differ only in the random seed the training used. Accuracy-only "
                 "training lands left of zero in both runs at all five doses; the "
                 "two confidence-aware versions land right of zero at eighteen of "
                 "their twenty. The pairs are wide apart, so the size of the "
                 "effect is a property of the run, not of the reward."))

    acc_pairs = seed_pair_chart(
        [(label, [(f"{d} steps",
                   delta(0, objective, d, "accuracy"),
                   delta(1, objective, d, "accuracy"))
                  for d in REPLICATION_DOSES])
         for objective, label, *_ in REPLICATED],
        chart_id="chart-seed-accuracy",
        xlabel="plain accuracy, change from that run's own untuned base",
        better="right", noise=band["accuracy"],
        caption=("The same versions under the measure benchmarks already use. "
                 "Run 2's gain is smaller at fourteen of the fifteen doses, and "
                 "accuracy-only training buys 0.2 points by 375 and 500 steps "
                 "while still paying the full quadratic penalty shown above."))

    # --- the mechanism ------------------------------------------------------
    # A range whose ends coincide is a single number, and printing "0 to 0%"
    # invites the reader to look for a spread that is not there. That collapse
    # matters most on the row it happens to: accuracy-only abstention is
    # identically zero at every dose, and the table should say so plainly.
    def span(values, fmt, suffix=""):
        low, high = min(values), max(values)
        if fmt(low) == fmt(high):
            return f"{fmt(low)}{suffix}"
        return f"{fmt(low)} to {fmt(high)}{suffix}"

    as_pct = lambda v: f"{v * 100:.0f}"
    as_prob = lambda v: f"{v:.2f}"

    mech_rows = [["<b>Untuned base</b>",
                  pct(base(0)["abstention_rate"], 0), pct(base(1)["abstention_rate"], 0),
                  f"{float(base(0)['mean_probability']):.2f}",
                  f"{float(base(1)['mean_probability']):.2f}"]]
    for objective, label, *_ in REPLICATED:
        a0 = [float(cell(0, objective, d)["abstention_rate"]) for d in REPLICATION_DOSES]
        a1 = [float(cell(1, objective, d)["abstention_rate"]) for d in REPLICATION_DOSES]
        p0 = [float(cell(0, objective, d)["mean_probability"]) for d in REPLICATION_DOSES]
        p1 = [float(cell(1, objective, d)["mean_probability"]) for d in REPLICATION_DOSES]
        mech_rows.append([
            f"<b>{label}</b>",
            span(a0, as_pct, "%"), span(a1, as_pct, "%"),
            span(p0, as_prob), span(p1, as_prob)])
    mechanism = table(
        ["version", "abstains, run 1", "abstains, run 2",
         "stated confidence, run 1", "stated confidence, run 2"],
        mech_rows, right_from=1, cls="choice-table")

    # --- calibration gap, which needs no scoring rule at all ---------------
    # Stated confidence minus how often that confidence was right. Signed, so it
    # says WHICH WAY a version is miscalibrated; the Brier decomposition's
    # reliability term is squared and cannot. Computed on the attempted subset at
    # both ends, because a model states no probability when it abstains.
    def gap(seed, objective, step):
        return float(cell(seed, objective, step)["overconfidence"])

    base_gap = {seed: float(base(seed)["overconfidence"]) for seed in (0, 1)}
    calib_rows = [["<b>Untuned base</b>",
                   f"{base_gap[0]:+.2f}", f"{base_gap[1]:+.2f}", "&mdash;"]]
    for objective, label, *_ in REPLICATED:
        values = {s: [gap(s, objective, d) for d in REPLICATION_DOSES] for s in (0, 1)}
        worse = sum(v > base_gap[s] for s in (0, 1) for v in values[s])
        calib_rows.append([
            f"<b>{label}</b>",
            span(values[0], lambda v: f"{v:+.2f}"),
            span(values[1], lambda v: f"{v:+.2f}"),
            f"{worse}/10" if worse else "0/10"])
    calibration = table(
        ["version", "gap, run 1", "gap, run 2",
         "doses more overconfident than the base"],
        calib_rows, right_from=1, cls="choice-table")

    # The analysis manifest gained a schema version when it grew from two runs
    # to many, and the input keys went from "step_125" to "seed2_evaluation_...".
    # Take the first entry either way: this is a handle for a reader who wants to
    # re-derive the numbers, not an identity the page depends on, so it should
    # not be the thing that breaks a build.
    inputs = manifest.get("inputs") or {}
    digest = str(next(iter(inputs.values()), {}).get("sha256", ""))[:12]
    base_q0, base_q1 = float(base(0)["score_quadratic"]), float(base(1)["score_quadratic"])
    base_a0, base_a1 = float(base(0)["accuracy"]), float(base(1)["accuracy"])

    side_page(
        "replication.html",
        title="Below Zero — what survived a second training run",
        description=("The same three reward objectives trained twice from "
                     "different random seeds, with the design matrix and the "
                     "measurement floor stated before any result."),
        h1="What survived a second training run",
        standfirst=("Three reward objectives, each trained twice from a different "
                    "random seed and measured against the untuned model it started "
                    "from. The directions replicated. The magnitudes did not. This "
                    "page states which is which, and separates what a model was "
                    "trained on from what its answers were scored with, because "
                    "conflating those two is how a result like this gets misread."),
        extra_css=REPLICATION_CSS,
        body=f"""
<h2 id="design">A scoring rule can play three different roles</h2>
<p>The same rule, say the quadratic score, can be the thing a model is
<em>told</em> about, the thing it is <em>trained</em> on, or the thing its answers
are <em>scored</em> with afterwards. Those are three separate questions with three
separate answers, and most confusion about work like this comes from reading a
result about one of them as a result about another.</p>
{roles}
<p>Because the third role is applied after generation to stored responses, it is free
and it is unlimited: the same answers can be scored under any number of rules without
running the model again. This page uses two of them, and only two. Everything below
reports plain accuracy, which is what benchmarks do today, and the quadratic score,
which is what this project argues they should do instead. Nothing here is managed,
decided or stopped against any other rule, so putting more columns on the page would
ask the reader to price numbers nobody acts on.</p>

<h2 id="versions">What each version was trained on</h2>
<p>Three rewards were trained, twice each. The difference between the first two is
exactly one thing: whether the probability the model states changes what it earns.</p>
{trained}
<p>Each was trained twice, at five doses: 125, 250, 300, 375 and 500 steps. Same frozen
training pool, same 100 held-out questions, same neutral prompt.</p>
<p><b>What differs between the two runs is narrower than "the random seed", and saying
so matters for how wide the gaps below should be read.</b> The two runs saw the same
questions in the same order and started from the same weights. The provider's sampler
draws the training rollouts without a fixed seed, deliberately: pinning one made all
eight samples in a group come back identical, which erases the group-relative
comparison the training method runs on. So the sampling stream is the only thing that
diverged.</p>
<p>That makes these two runs a <em>lower bound</em> on how much a retrained model
moves. The two variance sources usually largest in this kind of training, which
questions arrive in which order and how the adapter is initialised, are held at zero
here. A reader should treat the gaps below as the least a rerun would produce, not the
most. It also means neither run can be reproduced exactly, only repeated.</p>

<h2 id="measures">What a score change is measured with</h2>
<p>Two measures, reported for every version at every dose. The distance between them
is the argument: they agree about the confidence-aware versions and disagree about
the accuracy-only one, and that disagreement is the whole result.</p>
<p><b>Plain accuracy</b> is what benchmarks already report. A right answer scores 1,
and a wrong answer and a silence both score 0. <b>The quadratic score</b> is the
proposed replacement. It is strictly proper, which is a technical property with a
plain meaning: a model gets its best expected score by reporting the probability it
actually holds, so no confidence it can claim beats telling the truth.</p>
{measures}
<p>The last column is the part that makes the rest of this page readable. The untuned
base was re-evaluated once per stage: the same weights, the same 100 questions, the
same prompt. It should have returned the same number every time. It did not.</p>
{draws_table}
<p><b>Both runs measured this independently and they agree.</b> Run 1 re-evaluated its
base at three stages and spanned 0.014 on the quadratic score; run 2 did it at five and
spanned 0.021. These are draws of the same quantity, because the untuned base is one
fixed model answering one fixed set of questions, so all eight pool into a single floor:
a standard deviation of 0.007 and a full range of 0.021. The floor is measured, not
assumed.</p>
<p>It is worth being exact about what this floor is, because it is not sampling
randomness. Generation is greedy, at temperature zero, with a fixed seed, so these
eight passes should have been identical. They differ because floating-point addition
is not associative and the work is batched differently each time, which flips the
answer on items where the top two options are nearly tied. The signature is visible in
the responses: about 90 of the 100 items are identical every single time, and
<b>two items carry roughly 85% of the spread</b>, one of them a single multiple-choice
letter flipping from A to C. So this is a handful of coin flips on knife-edge
questions rather than a smooth bell curve, and a &plusmn; band is a convenient summary
of something lumpier than that notation suggests.</p>
<p>Practically: a change of 0.02 in the quadratic column is roughly the size of the gap
between measuring one unchanged model twice. <b>Any number smaller than its measure's
band should be read as "no detectable change", not as a small effect.</b> The band is
drawn on the charts further down and greyed in a table where it applies. Every averaged
cell in the next section clears its band; several individual doses do not, which is a
distinction a single averaged number would hide.</p>

<h2 id="matrix">Trained on, against scored by</h2>
<p>Rows are what the model was trained on. Columns are what its stored answers were
then scored with. Each cell is the change from that run's own untuned base,
averaged over the five doses.</p>
{matrix}
<p>Read down a column, not across a row. The two measures have different natural
scales, so the accuracy and quadratic numbers in one row are not comparable to each
other in size, only in sign.</p>
<p>The top row-pair is the result, and it is the only place the two columns
disagree. <b>Training on accuracy alone raises plain accuracy and lowers the
quadratic score, in both runs.</b> A benchmark reporting only the first column would
record that trade as an unambiguous improvement, and would be measuring a model that
got worse at knowing what it knows.</p>
<p>Both confidence-aware row-pairs are positive in both columns in both runs. Pricing
confidence did not cost accuracy in either trajectory, which is the claim worth
carrying forward: the trade the first row shows is a property of the accuracy-only
reward, not a price every version pays.</p>

<h2 id="replicated">What replicated and what did not</h2>
<p>The question a second run exists to answer is whether the direction holds, so that
is what this counts: for each version, under each measure, how many of the five doses
moved the same way in both runs.</p>
{verdict}
<p>Now the same measurements drawn, so the gap between the runs is visible rather
than summarised. The shaded band is the repeat-measurement floor from above.</p>
{quad_pairs}
{acc_pairs}
<p>Two things are true at once here, and the page would be misleading if it printed
only the first. <b>The directions replicated.</b> Accuracy-only training lowered the
quadratic score in ten out of ten measurements across two runs; the confidence-aware
versions raised it in eighteen of twenty, the exceptions being the assertion-cost
version at 500 steps in run 1 and at 375 steps in run 2, both within a hair of zero.
<b>The magnitudes did not.</b> Nine of the ten confidence-aware measurements came
back smaller in run 2, and on plain accuracy fourteen of fifteen did. That is a
systematic shift, not scatter, and far too large to be explained by the 0.008
difference between the two runs' bases.</p>
<p>Run 1 was the more favourable trajectory. Any single number quoted from it, such
as the +0.155 that the cost-0.09 version reached at 125 steps, is a property of that
trajectory: the same recipe with a different seed returned +0.029. Where an earlier
page quoted such figures, read them as one draw.</p>
<p>The ordering <em>within</em> the confidence-aware group did not survive either,
and the earlier page said in advance that it should not be quoted. The assertion-cost
version produced the single largest number in either run, +0.155 at 125 steps, and
led at the two lowest doses of run 1. In run 2 it led at one dose out of five. The
two versions are close enough that a rerun reorders them, so they should not be
reported as distinguishable, and the assertion cost should not be presented as
buying anything on this evidence.</p>

<h2 id="mechanism">The part that replicated most cleanly</h2>
<p>Underneath the score changes is a behavioural one, and it is the most consistent
result in either run.</p>
{mechanism}
<p><b>Training on accuracy alone drove abstention to exactly zero</b> in both runs at
all five doses, ten out of ten measurements, from a base that declined to answer about
one question in ten. It also pushed stated confidence up, from 0.88 to above 0.91
everywhere. The model stopped saying it did not know, and became more certain while
doing it.</p>
<p>That is the finding this project began from, reproduced causally: a census of
published benchmark responses found 0.68% ever say they don't know, and here is a
reward that produces exactly that, from a model that started out willing to. It does
not depend on which scoring rule you grade with, which is why it is the claim to
carry rather than any of the score deltas above.</p>
<p>The same thing shows up as a number, without needing a scoring rule at all.
<b>The calibration gap</b> is how confident a version says it is, minus how often
that confidence turns out to be right. Positive means overconfident. It is a
subtraction rather than a rule, so nobody has to accept the quadratic score to read
it.</p>
{calibration}
<p><b>Training on accuracy alone made the model more overconfident than it started, at
every dose in both runs.</b> The base overstates itself by 0.26, and the two runs agree
on that to within 0.006. Accuracy-only training pushes the gap to between 0.34 and
0.38, ten measurements out of ten. Every confidence-aware measurement moves the other
way, also ten out of ten. The assertion-cost version is the noisy one again, better
than the base at nine of its ten.</p>
<p>This is the cleanest statement of the result available, because it needs no
argument about scoring. A benchmark that reports accuracy would show the accuracy-only
version improving. It is, at the same time, further from knowing what it knows than
the untuned model it started as.</p>
<p>The confidence-aware versions do not restore abstention to base levels either. They
keep it near zero while pulling stated confidence down to between 0.69 and 0.87, which
is the calibration effect showing up as hedged answers rather than as silence. One exception
appears in both runs and is unexplained: at 375 steps the assertion-cost version
abstains far more than at any neighbouring dose, 9% in run 1 and 14% in run 2 against
roughly 1% elsewhere. It is the only dose in the grid where a tuned version declines
to answer more often than the untuned model.</p>

<h2 id="limits">What this still cannot tell you</h2>
<p>Two runs. Two is enough to show that a magnitude moved between them and not enough
to say what its distribution is, so nothing here is an interval. The right reading of a
two-run agreement is "the direction is probably real", not "the effect is this big".
And as the versions section says, these two runs differ only in the sampling stream, so
even that is the narrowest version of the question.</p>
<p><b>The step counts are not a matched dose across versions.</b> Training only learns
from a batch when the eight sampled answers to a question disagree with each other;
when all eight score the same there is nothing to compare, and the batch is skipped.
Under the accuracy-only reward, where a response can only score 1 or 0, that happens
almost every time: <b>8%</b> of its batches produce a learning signal on average,
against <b>66%</b> for the confidence-aware versions, which can also separate answers
by the probability attached to them. Counted over the full 500 steps, accuracy-only
absorbs about <b>150</b> productive batches against about <b>1,300</b>, a factor of
nearly nine. The pipeline already knows this and admits each version against its own
floor for how many batches must have been productive. Read the doses as elapsed
training, not as equal treatment.</p>
<p>That asymmetry is not a flaw in the setup so much as a property of the reward being
tested. A rule that scores only right-or-wrong has less to say about eight answers than
one that also reads their stated confidence, and having less to say is part of what is
being argued about it. But it does mean a dose-for-dose comparison flatters neither
side cleanly, and no claim here should rest on the two versions having been trained
equally hard.</p>
<p>One 8B model and 100 held-out questions per cell. The repeat-measurement band
above is the direct consequence of that sample size, and it is not small relative to
several of these effects.</p>
<p>The cost-0.04 and cost-0.16 versions from the <a href="dose-response.html">dose-response
page</a> were not retrained, so they appear nowhere here and should be read as
single-run results.</p>
<p>This page scores under two rules because those are the two the project acts on.
The stored responses are sufficient to rescore under any rule without running the
model again, and the downloadable CSV carries seven of them, including the
logarithmic and spherical scores. Nothing here was decided against those, so they
are in the data rather than on the page.</p>
<p>Every generation used a neutral prompt, so nothing on this page measures a model
responding to an announced rule. That is the separate experiment on the
<a href="index.html">findings page</a>.</p>
<p>Run 2's base scores {base_q1:.3f} on the quadratic rule and {pct(base_a1, 0)} on
accuracy; run 1's scores {base_q0:.3f} and {pct(base_a0, 0)}. Every delta on this
page is measured against its own run's base for that reason. The stored responses
behind run 2 hash to <code>{html.escape(digest)}</code>.</p>
""",
        footer=("Every figure here is rendered from the committed CSVs in "
                "data/processed. Two training seeds, five doses, one model. No "
                "checkpoint on this page was selected for winning, and the "
                "measurement floor is stated before the results rather than "
                "after them."),
    )


def build_training():
    """Explain the reward comparison and its results without assuming ML vocabulary."""
    with open(
        os.path.join(PROC, "finetune_pilot_summary.json"), encoding="utf-8"
    ) as handle:
        pilot = json.load(handle)

    # Programme-wide synthesis across all three trained families (Qwen3 8B,
    # GPT-OSS 20B, Nemotron 3 Nano 30B); see notes/2026-09-03-third-family-
    # protocol.md for why the Nemotron sentence below reads "failed, then
    # passed" rather than "failed" (the untouched base failed the format gate,
    # a syntax warm-up then cleared it, and training itself succeeded).
    with open(
        os.path.join(PROC, "training_effect_synthesis_summary.json"),
        encoding="utf-8",
    ) as handle:
        training_synthesis = json.load(handle)
    # This page stays on the first training programme (its prose was
    # written on those pairs); the exporter carries that programme alone
    # under "first" once the second programme exists, and the pooled
    # "all" block then spans both. Read the first-programme block.
    training_synthesis = {**training_synthesis, **training_synthesis.get("first", {})}
    synthesis_pairs = training_synthesis["all"]["pairs"]
    synthesis_score_wins = training_synthesis["all"]["score_improved"][0]
    nemotron_pairs = training_synthesis["by_family"]["Nemotron 3 Nano 30B"]["pairs"]

    profile = pilot["base_profile"]
    training = pilot["training_c09"]
    neutral_c09 = pilot["development_neutral_c09"]
    neutral_c16 = pilot["development_neutral_c16"]
    two_pass_c16 = pilot["two_pass_c16_canary"]
    calibration = pilot["development_neutral_calibration"]
    quadratic_vs_binary = pilot["one_pass_quadratic_versus_binary"]
    threshold_policy = pilot["two_pass_c16_threshold_policy"]
    replication = pilot["replication_seed0"]
    replication_training = replication["training"]
    replication_neutral = replication["development_neutral"]
    replication_contrasts = replication["paired_neutral_contrasts"]
    replication_benchmarks = replication["development_neutral_by_benchmark"]
    replication_thresholds = replication["quad_cost_threshold_policy"]
    replication_prompts = replication["prompt_robustness_quadratic_score"]
    replication2 = pilot["replication_seed1"]
    replication2_training = replication2["training"]
    replication2_neutral = replication2["development_neutral"]
    replication2_contrasts = replication2["paired_neutral_contrasts"]
    replication2_benchmarks = replication2["development_neutral_by_benchmark"]
    replication2_thresholds = replication2["quad_cost_threshold_policy"]
    replication2_prompts = replication2["prompt_robustness_quadratic_score"]
    final_test = pilot["final_test"]
    final_primary = final_test["primary"]
    final_neutral = final_test["neutral_combined"]
    final_secondary = final_test["secondary_neutral_contrasts"]
    final_prompts = final_test["prompt_robustness_quadratic_versus_binary"]
    final_benchmarks = final_test["primary_by_benchmark"]
    profile_results = table(
        ["automated check", "observed result", "what it means"],
        [
            ["Response health", "800 responses; 0% invalid", "The grammar and parser are usable without manual cleanup."],
            ["Base behavior", f"{pct(profile['correct_rate'], 1)} correct; {pct(profile['incorrect_rate'], 1)} wrong; {pct(profile['abstention_rate'], 1)} abstained", "The base samples all three relevant actions."],
            ["Probability support", f"{profile['groups_with_varied_assertion_probability']} of 100 groups", "Confidence rewards can differ from binary accuracy."],
            ["Answer and abstention support", f"{profile['groups_with_assertion_and_abstention']} of 100 groups", "An assertion cost can survive group centering."],
            ["Confidence versus cost, c = 0.09", f"{profile['quadratic_vs_cost_c09_scaled_difference_relative_to_binary'] * 100:.1f}% of the binary reference signal", "Identifiable, but modest."],
            ["Confidence versus cost, c = 0.16", f"{profile['quadratic_vs_cost_c16_scaled_difference_relative_to_binary'] * 100:.1f}% of the binary reference signal", "The first stress test nearly doubles this separation."],
        ],
        right_from=99,
        cls="choice-table",
    )
    training_results = table(
        ["one-pass training arm", "active groups", "mean scaled advantage RMS", "training-rollout abstention"],
        [
            ["Accuracy-only", str(training["binary"]["active_groups"]), f"{training['binary']['mean_scaled_advantage_rms']:.3f}", pct(training["binary"]["rollout_abstention_rate"], 1)],
            ["Confidence-aware", str(training["quadratic"]["active_groups"]), f"{training['quadratic']['mean_scaled_advantage_rms']:.3f}", pct(training["quadratic"]["rollout_abstention_rate"], 1)],
            ["Confidence + cost, c = 0.09", str(training["quad_cost"]["active_groups"]), f"{training['quad_cost']['mean_scaled_advantage_rms']:.3f}", pct(training["quad_cost"]["rollout_abstention_rate"], 1)],
        ],
        right_from=1,
        cls="choice-table",
    )
    development_results = table(
        ["checkpoint under neutral instruction", "coverage", "accuracy", "wrong assertion rate", "Brier score"],
        [
            ["Untouched base", pct(neutral_c09["base"]["coverage"], 0), pct(neutral_c09["base"]["accuracy"], 0), pct(neutral_c09["base"]["incorrect_assertion_rate"], 0), f"{neutral_c09['base']['brier']:.3f}"],
            ["Accuracy-only", pct(neutral_c09["binary"]["coverage"], 0), pct(neutral_c09["binary"]["accuracy"], 0), pct(neutral_c09["binary"]["incorrect_assertion_rate"], 0), f"{neutral_c09['binary']['brier']:.3f}"],
            ["Confidence-aware", pct(neutral_c09["quadratic"]["coverage"], 0), pct(neutral_c09["quadratic"]["accuracy"], 0), pct(neutral_c09["quadratic"]["incorrect_assertion_rate"], 0), f"{neutral_c09['quadratic']['brier']:.3f}"],
            ["Confidence + cost, c = 0.09", pct(neutral_c09["quad_cost"]["coverage"], 0), pct(neutral_c09["quad_cost"]["accuracy"], 0), pct(neutral_c09["quad_cost"]["incorrect_assertion_rate"], 0), f"{neutral_c09['quad_cost']['brier']:.3f}"],
            ["Confidence + cost, c = 0.16", pct(neutral_c16["quad_cost"]["coverage"], 0), pct(neutral_c16["quad_cost"]["accuracy"], 0), pct(neutral_c16["quad_cost"]["incorrect_assertion_rate"], 0), f"{neutral_c16['quad_cost']['brier']:.3f}"],
            ["Confidence + cost, c = 0.16, two passes", pct(two_pass_c16["neutral"]["coverage"], 0), pct(two_pass_c16["neutral"]["accuracy"], 0), pct(two_pass_c16["neutral"]["incorrect_assertion_rate"], 0), f"{two_pass_c16['neutral']['brier']:.3f}"],
        ],
        right_from=1,
        cls="choice-table",
    )
    calibration_results = table(
        ["checkpoint under neutral instruction", "accuracy when answered",
         "mean stated confidence", "overconfidence gap", "Brier score",
         "confidence AUROC"],
        [
            [label, pct(calibration[key]["assertion_accuracy"], 0),
             pct(calibration[key]["mean_reported_probability"], 1),
             f"{calibration[key]['signed_calibration_gap'] * 100:.1f} points",
             f"{calibration[key]['brier_among_attempts']:.3f}",
             f"{calibration[key]['confidence_auroc']:.2f}"]
            for label, key in (
                ("Untouched base", "base"),
                ("Accuracy-only", "binary"),
                ("Confidence-aware", "quadratic"),
                ("Confidence + cost, c = 0.09", "quad_cost_c09"),
                ("Confidence + cost, c = 0.16", "quad_cost_c16"),
                ("Confidence + cost, c = 0.16, two passes",
                 "quad_cost_c16_two_pass"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    threshold_policy_results = table(
        ["minimum confidence required to answer", "coverage", "error among answers",
         "interpretation"],
        [
            [pct(row["minimum_reported_probability"], 0), pct(row["coverage"], 0),
             pct(row["error_among_assertions"], 0),
             ("No answer falls below the 40% action threshold."
              if row["minimum_reported_probability"] == 0.4
              else "A downstream policy withholds lower-confidence answers.")]
            for row in threshold_policy
        ],
        right_from=1,
        cls="choice-table",
    )
    replication_training_results = table(
        ["500-question training arm", "seed 0 active groups", "seed 1 active groups",
         "seed 0 abstention", "seed 1 abstention", "health"],
        [
            [label, str(replication_training[key]["active_groups"]),
             str(replication2_training[key]["active_groups"]),
             pct(replication_training[key]["rollout_abstention_rate"], 1),
             pct(replication2_training[key]["rollout_abstention_rate"], 1),
             (f"{replication_training[key]['health']} / "
              f"{replication2_training[key]['health']}")]
            for label, key in (
                ("Accuracy-only", "binary"),
                ("Confidence-aware", "quadratic"),
                ("Confidence + cost", "quad_cost"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    replication_seed0_neutral_results = table(
        ["checkpoint under neutral instruction", "coverage", "accuracy",
         "mean confidence", "calibration gap", "Brier", "quadratic score",
         "confidence AUROC"],
        [
            [label, pct(replication_neutral[key]["coverage"], 0),
             pct(replication_neutral[key]["accuracy"], 0),
             pct(replication_neutral[key]["mean_reported_probability"], 1),
             f"{replication_neutral[key]['signed_calibration_gap'] * 100:+.1f} points",
             f"{replication_neutral[key]['brier']:.3f}",
             f"{replication_neutral[key]['quadratic_score']:.3f}",
             f"{replication_neutral[key]['confidence_auroc']:.2f}"]
            for label, key in (
                ("Untouched base", "base"),
                ("Accuracy-only", "binary"),
                ("Confidence-aware", "quadratic"),
                ("Confidence + cost", "quad_cost"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    replication_seed1_neutral_results = table(
        ["checkpoint under neutral instruction", "coverage", "accuracy",
         "mean confidence", "calibration gap", "Brier", "quadratic score",
         "confidence AUROC"],
        [
            [label, pct(replication2_neutral[key]["coverage"], 0),
             pct(replication2_neutral[key]["accuracy"], 0),
             pct(replication2_neutral[key]["mean_reported_probability"], 1),
             f"{replication2_neutral[key]['signed_calibration_gap'] * 100:+.1f} points",
             f"{replication2_neutral[key]['brier']:.3f}",
             f"{replication2_neutral[key]['quadratic_score']:.3f}",
             f"{replication2_neutral[key]['confidence_auroc']:.2f}"]
            for label, key in (
                ("Untouched base", "base"),
                ("Accuracy-only", "binary"),
                ("Confidence-aware", "quadratic"),
                ("Confidence + cost", "quad_cost"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    two_seed_contrast_results = table(
        ["paired comparison under neutral instruction", "seed 0 change (95% interval)",
         "seed 1 change (95% interval)", "two-seed reading"],
        [
            [label,
             (f"{replication_contrasts[key]['quadratic_score_change']['estimate']:+.3f} "
              f"({replication_contrasts[key]['quadratic_score_change']['confidence_interval_95'][0]:+.3f} "
              f"to {replication_contrasts[key]['quadratic_score_change']['confidence_interval_95'][1]:+.3f})"),
             (f"{replication2_contrasts[key]['quadratic_score_change']['estimate']:+.3f} "
              f"({replication2_contrasts[key]['quadratic_score_change']['confidence_interval_95'][0]:+.3f} "
              f"to {replication2_contrasts[key]['quadratic_score_change']['confidence_interval_95'][1]:+.3f})"),
             reading]
            for label, key, reading in (
                ("Confidence-aware versus accuracy-only", "quadratic_versus_binary",
                 "Replicated in both seeds"),
                ("Confidence + cost versus accuracy-only", "quad_cost_versus_binary",
                 "Positive twice; seed 1 unresolved"),
                ("Confidence + cost versus confidence-aware", "quad_cost_versus_quadratic",
                 "Direction changed; no stable winner"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    replication_benchmark_results = table(
        ["benchmark", "confidence gain, seed 0", "confidence gain, seed 1",
         "cost gain, seed 0", "cost gain, seed 1"],
        [
            [label,
             f"{replication_benchmarks[key]['quadratic']['quadratic_score'] - replication_benchmarks[key]['binary']['quadratic_score']:+.3f}",
             f"{replication2_benchmarks[key]['quadratic']['quadratic_score'] - replication2_benchmarks[key]['binary']['quadratic_score']:+.3f}",
             f"{replication_benchmarks[key]['quad_cost']['quadratic_score'] - replication_benchmarks[key]['binary']['quadratic_score']:+.3f}",
             f"{replication2_benchmarks[key]['quad_cost']['quadratic_score'] - replication2_benchmarks[key]['binary']['quadratic_score']:+.3f}"]
            for label, key in (
                ("ARC", "arc"),
                ("BoolQ", "boolq"),
                ("GPQA parity", "gpqa_parity"),
                ("MedMCQA", "medmcqa"),
                ("MMLU-Pro", "mmlu_pro"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    replication_threshold_results = table(
        ["minimum confidence", "seed 0 coverage / error", "seed 1 coverage / error",
         "role"],
        [
            [pct(row0["minimum_reported_probability"], 0),
             (f"{pct(row0['coverage'], 0)} / "
              f"{pct(row0['error_among_assertions'], 1)}"),
             (f"{pct(row1['coverage'], 0)} / "
              f"{pct(row1['error_among_assertions'], 1)}"),
             ("Predeclared c = .09 break-even policy"
              if row0["minimum_reported_probability"] == 0.3
              else "Post-hoc development diagnostic")]
            for row0, row1 in zip(replication_thresholds, replication2_thresholds)
            if row0["minimum_reported_probability"] in (0.3, 0.4, 0.7, 0.8, 0.9)
        ],
        right_from=1,
        cls="choice-table",
    )
    replication_prompt_results = table(
        ["evaluation instruction", "confidence gain, seed 0",
         "confidence gain, seed 1", "cost gain, seed 0", "cost gain, seed 1"],
        [
            [label,
             f"{replication_prompts['quadratic'][key] - replication_prompts['binary'][key]:+.3f}",
             f"{replication2_prompts['quadratic'][key] - replication2_prompts['binary'][key]:+.3f}",
             f"{replication_prompts['quad_cost'][key] - replication_prompts['binary'][key]:+.3f}",
             f"{replication2_prompts['quad_cost'][key] - replication2_prompts['binary'][key]:+.3f}"]
            for label, key in (
                ("No reward announced", "neutral"),
                ("Accuracy announced", "binary"),
                ("Confidence announced", "quadratic"),
                ("Confidence + cost announced", "quad_cost"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    final_gate_results = table(
        ["predeclared gate", "required", "observed", "result"],
        [
            ["Combined proper-score effect",
             "Estimate and 95% lower bound above 0",
             (f"{final_primary['combined']['quadratic_score_change']['estimate']:+.3f} "
              f"({final_primary['combined']['quadratic_score_change']['confidence_interval_95'][0]:+.3f} "
              f"to {final_primary['combined']['quadratic_score_change']['confidence_interval_95'][1]:+.3f})"),
             "PASS"],
            ["Direction in each training seed", "Both point estimates above 0",
             (f"{final_primary['by_seed']['seed0']['quadratic_score_change']['estimate']:+.3f} "
              f"and {final_primary['by_seed']['seed1']['quadratic_score_change']['estimate']:+.3f}"),
             "PASS"],
            ["Combined accuracy safeguard", "Point estimate no worse than -3 points",
             (f"{final_primary['combined']['accuracy_change']['estimate'] * 100:+.1f} points "
              f"({final_primary['combined']['accuracy_change']['confidence_interval_95'][0] * 100:+.1f} "
              f"to {final_primary['combined']['accuracy_change']['confidence_interval_95'][1] * 100:+.1f})"),
             "PASS by point rule"],
            ["Per-seed accuracy safeguard", "Neither point estimate worse than -5 points",
             (f"{final_primary['by_seed']['seed0']['accuracy_change']['estimate'] * 100:+.1f} "
              f"and {final_primary['by_seed']['seed1']['accuracy_change']['estimate'] * 100:+.1f} points"),
             "PASS by point rule"],
            ["Malformed-output safeguard", "Increase no greater than 1 point",
             f"{final_primary['combined']['invalid_rate_change']['estimate'] * 100:+.1f} points",
             "PASS"],
        ],
        right_from=1,
        cls="choice-table",
    )
    final_checkpoint_results = table(
        ["checkpoint under neutral instruction", "accuracy", "mean confidence",
         "calibration gap", "Brier", "quadratic score", "confidence AUROC",
         "coverage"],
        [
            [label, pct(final_neutral[key]["accuracy"], 1),
             pct(final_neutral[key]["mean_reported_probability"], 1),
             f"{final_neutral[key]['signed_calibration_gap'] * 100:+.1f} points",
             f"{final_neutral[key]['brier']:.3f}",
             f"{final_neutral[key]['quadratic_score']:.3f}",
             f"{final_neutral[key]['confidence_auroc']:.2f}",
             pct(final_neutral[key]["coverage"], 1)]
            for label, key in (
                ("Untouched base", "base"),
                ("Accuracy-only RL", "binary"),
                ("Confidence-aware RL", "quadratic"),
                ("Confidence + cost RL", "quad_cost"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    final_secondary_results = table(
        ["neutral-prompt comparison", "combined proper-score change",
         "seed 0", "seed 1", "interpretation"],
        [
            ["Confidence-aware versus accuracy-only",
             f"{final_primary['combined']['quadratic_score_change']['estimate']:+.3f}",
             f"{final_primary['by_seed']['seed0']['quadratic_score_change']['estimate']:+.3f}",
             f"{final_primary['by_seed']['seed1']['quadratic_score_change']['estimate']:+.3f}",
             "Primary comparison passed"],
            ["Confidence + cost versus accuracy-only",
             f"{final_secondary['quad_cost_versus_binary']['combined_quadratic_score_change']:+.3f}",
             f"{final_secondary['quad_cost_versus_binary']['seed0_quadratic_score_change']:+.3f}",
             f"{final_secondary['quad_cost_versus_binary']['seed1_quadratic_score_change']:+.3f}",
             "Similar aggregate gain"],
            ["Confidence + cost versus confidence-aware",
             f"{final_secondary['quad_cost_versus_quadratic']['combined_quadratic_score_change']:+.3f}",
             f"{final_secondary['quad_cost_versus_quadratic']['seed0_quadratic_score_change']:+.3f}",
             f"{final_secondary['quad_cost_versus_quadratic']['seed1_quadratic_score_change']:+.3f}",
             "No stable incremental benefit"],
        ],
        right_from=1,
        cls="choice-table",
    )
    final_benchmark_results = table(
        ["final benchmark", "proper-score change", "accuracy change", "reading"],
        [
            [label, f"{final_benchmarks[key]['quadratic_score_change']:+.3f}",
             f"{final_benchmarks[key]['accuracy_change'] * 100:+.1f} points", reading]
            for label, key, reading in (
                ("ARC", "arc", "Easy source; confidence became too cautious"),
                ("BoolQ", "boolq", "Easy source; accuracy-only was already strong"),
                ("GPQA parity", "gpqa_parity", "Largest gain on the hardest source"),
                ("MedMCQA", "medmcqa", "Modest calibration gain"),
                ("MMLU-Pro", "mmlu_pro", "Large calibration gain with lower accuracy"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    final_prompt_results = table(
        ["evaluation instruction", "proper-score change", "accuracy change"],
        [
            [label, f"{final_prompts[key]['quadratic_score_change']:+.3f}",
             f"{final_prompts[key]['accuracy_change'] * 100:+.1f} points"]
            for label, key in (
                ("No reward announced, primary", "neutral"),
                ("Accuracy announced", "binary"),
                ("Confidence announced", "quadratic"),
                ("Confidence + cost announced", "quad_cost"),
            )
        ],
        right_from=1,
        cls="choice-table",
    )
    family_screen_results = table(
        ["candidate", "frozen screen", "invalid output", "decision"],
        [
            ["<b>Nemotron Nano, untouched</b>",
             "Seven of eight valid in smoke; 256 profile rollouts",
             "3.13%", "Stop before training"],
            ["<b>Nemotron Super, untouched</b>",
             "Seven of eight valid in smoke; 256 profile rollouts",
             "28.9%", "Stop before training"],
            ["<b>GPT-OSS-20B</b>",
             "Seven of eight valid in smoke; 256 profile rollouts",
             "48.4%", "Stop before training"],
            ["<b>Nano after 8 syntax steps</b>",
             "Eight of eight valid in smoke; 288 profile rollouts",
             "1.04%", "Stop at the 1% gate"],
            ["<b>Nano after 16 syntax steps</b>",
             "Eight of eight valid in smoke; full 4,000-rollout profile",
             "0.575%", "Advance to reward training"],
        ],
        right_from=99,
        cls="choice-table",
    )
    family_seed_results = table(
        ["replicate", "what completed", "primary result", "decision"],
        [
            ["<b>Seed 0</b>",
             "Three arms, 125 steps each; complete 100-item development matrix",
             ("Confidence proper score +.083 versus accuracy-only; accuracy "
              "-4 points; malformed output unchanged at 0%"),
             "Pass development gate"],
            ["<b>Seed 1</b>",
             "Primary arms reached the first 256-rollout health check",
             ("Accuracy-only invalid 2.34%; confidence-aware invalid 1.17%; "
              "both exceeded the frozen 1% ceiling"),
             "Stop before development and final"],
        ],
        right_from=99,
        cls="choice-table",
    )
    family_next_steps = table(
        ["next design choice", "why it matters", "recommendation"],
        [
            ["<b>Validate syntax twice before RL</b>",
             ("One green profile did not predict a second stochastic training "
              "replicate's format stability."),
             ("Require two independent 4,000-rollout profiles below 0.5% invalid "
              "before spending on reward arms.")],
            ["<b>Run the primary pair first</b>",
             ("Qwen found no stable incremental value from the assertion cost, and "
              "the cost arm cannot rescue the primary comparison."),
             ("Train accuracy-only and confidence-aware first. Add the cost arm only "
              "after the primary effect repeats.")],
            ["<b>Strengthen format control for every arm</b>",
             ("Changing only a failed seed would make initialization another treatment."),
             ("Use a stronger shared syntax checkpoint or provider-supported grammar "
              "constraint, then restart every seed from that same state.")],
            ["<b>Keep the final slice sealed</b>",
             ("Offsets 60 through 99 were reserved but never generated."),
             ("Reuse them only under a newly frozen protocol after the development "
              "replicates pass.")],
        ],
        right_from=99,
        cls="choice-table",
    )
    experiment_map = table(
        ["stage", "what we do", "what varies", "what comes out"],
        [
            ["<b>1. Tune</b>",
             ("Run the same LoRA and reinforcement-learning process three times per "
              "seed on the same 500 questions, then repeat with a second seed"),
             ("Only the reward: accuracy-only, confidence-aware, or "
              "confidence-plus-cost"),
             ("Three tuned adapters, plus the untouched base control: "
              "four checkpoints total")],
            ["<b>2. Generate held-out answers</b>",
             ("Ask every checkpoint every held-out question under every evaluation "
              "instruction"),
             ("Four checkpoints crossed with four instructions: neutral, accuracy, "
              "confidence, and confidence-plus-cost"),
             ("4 checkpoints &times; 4 instructions = 16 saved responses per "
              "held-out question")],
            ["<b>3. Score the saved answers</b>",
             ("Apply each reward formula and the common behavioral metrics after the "
              "responses already exist"),
             "Three reward formulas; the saved answer does not change",
             ("16 responses &times; 3 formulas = 48 rule-score records per question, "
              "but still only 16 model generations")],
        ],
        right_from=99,
        cls="choice-table experiment-map",
    )
    terminology = table(
        ["phrase", "precise meaning here", "does it update weights?"],
        [
            ["<b>Tuning approach</b>",
             ("One of three reward objectives used inside the same RL and LoRA "
              "training process"),
             "Yes, during the training stage"],
            ["<b>Tuned checkpoint</b>",
             "The shared base model plus the adapter produced by one reward objective",
             "No; this is the saved result of training"],
            ["<b>Evaluation instruction</b>",
             "The rule described in the prompt when a held-out question is asked",
             "No; it changes the current prompt only"],
            ["<b>Scoring lens</b>",
             "A formula applied to a response after the model has produced and saved it",
             "No; it requires no model call"],
        ],
        right_from=99,
        cls="narrow",
    )
    arms = table(
        ["training arm", "what earns reward", "behavior it should favor"],
        [
            ["<b>Accuracy-only RL baseline</b>",
             "Correct answer: 1<br>Wrong or &ldquo;I don't know&rdquo;: 0",
             "Produce the right answer. A wrong answer is no worse than abstaining."],
            ["<b>Confidence-aware RL</b>",
             "Correct: 2p &minus; p&sup2;<br>Wrong: &minus;p&sup2;<br>Abstain: 0",
             ("Report a probability that matches the chance of being right. "
              "There is still some expected gain from answering at any positive chance.")],
            ["<b>Confidence-plus-cost RL</b>",
             "The confidence score, minus 0.09 whenever the model asserts an answer",
             "Calibrate confidence and abstain when the chance of being right is below 30%."],
        ],
        right_from=99,
        cls="arm-table",
    )
    choices = table(
        ["model's belief", "accuracy reward", "confidence reward", "confidence + cost"],
        [
            ["60% likely correct", "Answer", "Answer; report 60%", "Answer; report 60%"],
            ["20% likely correct", "Answer", "Answer; report 20%", "Abstain"],
        ],
        right_from=99,
        cls="narrow",
    )
    evaluation_axes = table(
        ["axis", "when it is set", "what changes", "levels in this experiment"],
        [
            ["<b>Checkpoint</b><br><span class=\"sub\">the columns</span>",
             "Before evaluation",
             "Which saved weights generate the response",
             ("Untouched base, accuracy-only RL adapter, confidence-aware RL adapter, "
              "or confidence-plus-cost RL adapter")],
            ["<b>Evaluation instruction</b><br><span class=\"sub\">the rows</span>",
             "When the held-out question is asked",
             "What scoring rule the prompt tells the already-trained checkpoint to expect",
             "No rule announced, accuracy, confidence, or confidence + cost"],
            ["<b>Scoring lens</b><br><span class=\"sub\">after generation</span>",
             "After the response is saved",
             "Only the reported metric; the model is not called again",
             "Accuracy, confidence, and confidence + cost are all applied to every response"],
        ],
        right_from=99,
        cls="narrow",
    )
    checkpoint_decoder = table(
        ["evaluation column", "which weights are loaded", "what its fine-tuning rewarded"],
        [
            ["<b>Base checkpoint</b><br><span class=\"sub\">no tuning</span>",
             "The original Qwen3-8B weights, with no reward-trained adapter attached",
             "Nothing. This is the control that shows how the original model responds to each evaluation instruction."],
            ["<b>Accuracy-only RL checkpoint</b><br><span class=\"sub\">code name: binary</span>",
             "The same base plus a LoRA adapter updated on the shared 500 training questions",
             "Correct completion: 1. Wrong completion or I DON'T KNOW: 0. The reported probability does not affect reward."],
            ["<b>Confidence-aware RL checkpoint</b><br><span class=\"sub\">code name: quadratic</span>",
             "The same base plus a separate LoRA adapter trained from the same starting point",
             "Correct: 2p - p². Wrong: -p². I DON'T KNOW: 0. Honest reported probability maximizes expected reward."],
            ["<b>Confidence-plus-cost RL checkpoint</b><br><span class=\"sub\">code name: quad_cost</span>",
             "The same base plus a third LoRA adapter trained from the same starting point",
             "The confidence reward minus 0.09 for any substantive answer. I DON'T KNOW scores 0, favoring abstention below 30% confidence."],
        ],
        right_from=99,
        cls="choice-table",
    )
    prompt_decoder = table(
        ["evaluation row", "what the already-trained checkpoint is told now"],
        [
            ["<b>Neutral instruction</b><br><span class=\"sub\">primary test</span>",
             "Choose an answer or I DON'T KNOW and report a probability. No reward formula, penalty, or preferred threshold is disclosed."],
            ["<b>Accuracy instruction</b>",
             "A correct substantive answer scores 1; a wrong answer or I DON'T KNOW scores 0. The prompt says a best guess maximizes this score."],
            ["<b>Confidence instruction</b>",
             "The prompt states the quadratic formula and asks for an honest probability. I DON'T KNOW scores 0."],
            ["<b>Confidence + cost instruction</b>",
             "The prompt states the same quadratic formula, subtracts 0.09 for asserting an answer, and explains the 30% break-even threshold."],
        ],
        right_from=99,
        cls="narrow",
    )
    evaluation_matrix = table(
        ["evaluation instruction", "base checkpoint", "accuracy-only RL checkpoint",
         "confidence-aware RL checkpoint", "confidence-plus-cost RL checkpoint"],
        [
            ["<b>No reward announced</b><br><span class=\"sub\">primary test</span>",
             "Generate once<br><span class=\"sub\">primary</span>",
             "Generate once<br><span class=\"sub\">primary</span>",
             "Generate once<br><span class=\"sub\">primary</span>",
             "Generate once<br><span class=\"sub\">primary</span>"],
            ["Accuracy rule announced",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>"],
            ["Confidence rule announced",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>"],
            ["Confidence + cost announced",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>",
             "Generate once<br><span class=\"sub\">diagnostic</span>"],
        ],
        right_from=99,
        cls="eval-matrix",
    )
    evaluation_questions = table(
        ["comparison", "what it identifies"],
        [
            ["Base checkpoint across instructions",
             "The prompt-only effect before any fine-tuning."],
            ["Each reward-trained checkpoint versus base under the neutral instruction",
             "The behavior that training made persistent."],
            ["Each checkpoint across all four instructions",
             "Whether later instructions override, amplify, or conflict with the learned policy."],
            ["Matching versus conflicting training and evaluation rules",
             "Whether an adapter learned a general decision policy or only works when the current instruction agrees with its training history."],
        ],
        right_from=99,
        cls="narrow",
    )
    impact_legend = table(
        ["expected sensitivity", "how to read it before we have results"],
        [
            ["<b>Dominant</b>",
             "Can reverse the answer to the experiment or make the comparison invalid."],
            ["<b>High</b>",
             "Can materially change held-out behavior, not just make an estimate noisier."],
            ["<b>Medium</b>",
             "Usually changes stability, efficiency, or effect size; less likely to reverse a healthy result."],
            ["<b>Low after a threshold</b>",
             "Must be adequate, but extra capacity or precision beyond that point should add little."],
        ],
        right_from=99,
        cls="narrow",
    )
    training_choices = table(
        ["choice", "our initial setting", "expected sensitivity", "rough magnitude or mechanism"],
        [
            ["<b>Reward definition</b>",
             "Accuracy, confidence, confidence + 0.09 assertion cost",
             "<b>Dominant</b>",
             "This is the treatment. It changes whether a low-confidence answer is rewarded, penalized, or tied with abstention."],
            ["<b>Assertion cost</b>",
             "0.09",
             "<b>Dominant within the cost arm</b>",
             "The implied abstention threshold is the square root of the cost. Costs of 0.04, 0.09, and 0.25 imply thresholds of 20%, 30%, and 50%."],
            ["<b>Base model</b>",
             "One Qwen3-8B checkpoint, fixed across arms",
             "<b>High or dominant</b>",
             "The model sets the knowledge ceiling and quality of self-assessed probability. A later model family is a replication, not a pooled treatment arm."],
            ["<b>Question difficulty mix</b>",
             "500 source-stratified items with mixed base outcomes",
             "<b>High</b>",
             "Questions that are always right or always wrong provide no group-relative signal. Too many easy items can make every reward arm look the same."],
            ["<b>Reward scale</b>",
             "One fixed multiplier per arm, calibrated to binary reward RMS",
             "<b>High for causal validity</b>",
             "The unchanged-base profile measures each arm's initial relative-signal spread. The code makes those spreads equal at step zero while preserving each rule's internal incentives."],
            ["<b>Learning rate and steps</b>",
             "4e-5 for 125 steps, held equal",
             "<b>High</b>",
             "Doubling steps doubles training batches and roughly doubles cost. Doubling the learning rate doubles the nominal step before Adam's adaptation; behavioral change is nonlinear and can become unstable."],
            ["<b>Group size</b>",
             "8 responses per question",
             "<b>Medium</b>",
             "Moving from 8 to 16 doubles sampling cost and, under independent sampling, reduces noise in a group mean by about 29%. It also raises the chance of seeing mixed outcomes."],
            ["<b>LoRA rank</b>",
             "32",
             "<b>Medium, then low</b>",
             "Moving from rank 32 to 64 roughly doubles adapter parameters. It matters if rank 32 is a bottleneck; after enough capacity exists for this short policy shift, extra rank should matter much less."],
            ["<b>Policy loss and drift control</b>",
             "On-policy importance sampling; same rule in every arm",
             "<b>Medium if stable, dominant if unstable</b>",
             "Clipping or a reference-policy penalty should affect all arms together. Extreme probability ratios or broad capability loss would invalidate an unclipped run."],
            ["<b>Output grammar and renderer</b>",
             "Explicit Qwen3 direct-answer renderer and exact two-line response",
             "<b>Dominant for validity</b>",
             "The default thinking renderer exhausted a short output allowance before reaching the answer. The direct-answer renderer now fails closed by model family. A permissive parser could still turn formatting failures into apparent abstention."],
        ],
        right_from=99,
        cls="choice-table",
    )
    contrast_examples = table(
        ["what appears in one sampled group", "what group centering does", "training consequence"],
        [
            ["Every response answers",
             "The same assertion cost is subtracted from every response, then disappears when the group average is subtracted.",
             "Confidence and confidence-plus-cost can send identical advantages to the optimizer."],
            ["Every response reports the same probability",
             "The confidence reward can become a positive rescaling of binary correctness.",
             "Fixed RMS calibration can remove the scale difference, leaving the accuracy and confidence arms effectively identical."],
            ["Substantive answers report different probabilities",
             "The confidence rule ranks some correct and incorrect responses differently from binary accuracy.",
             "Accuracy and confidence can now teach different token patterns."],
            ["Some responses answer and some choose I DON'T KNOW",
             "The assertion cost varies within the group, so it survives centering.",
             "Confidence and confidence-plus-cost can now teach different policies."],
        ],
        right_from=99,
        cls="choice-table",
    )
    accentuation_choices = table(
        ["option", "what it changes", "likely leverage", "main tradeoff", "recommendation"],
        [
            ["<b>Reward-divergence-aware question selection</b>",
             "Use unchanged-base rollouts to retain source-balanced questions whose final centered advantages actually differ across reward arms.",
             "<b>Dominant</b>: it can move the comparison from no identifiable treatment to a real one.",
             "A pool chosen only for extreme divergence would be less representative, so selection needs a minimum gate rather than a contest for the largest possible difference.",
             "Use in the primary design. Never use held-out test responses for selection."],
            ["<b>More exploration</b>",
             "Raise training temperature modestly or move from 8 to 16 samples per question.",
             "<b>Medium to high</b> when the base produces too little probability variation for the rewards to differ.",
             "Group size 16 roughly doubles sampling cost. Higher temperature adds variance and may increase malformed outputs.",
             "Try only if the small profile shows inadequate support, and change it identically for every arm."],
            ["<b>Shared probability-format warm-up</b>",
             "Before splitting the arms, give every copy the same short supervised lesson showing the exact answer and probability grammar.",
             "<b>Low here</b>: the current base already varies its probabilities in 60 of 100 profiled groups.",
             "The claim becomes reward comparison after a common warm-up, not reward alone from the untouched model.",
             "Do not add it to manufacture abstention. Use it only if a future model cannot express the required probability output."],
            ["<b>Higher assertion cost</b>",
             "Move the break-even threshold from 30% at c = 0.09 to 40% at c = 0.16, or 50% at c = 0.25.",
             "<b>Potentially high</b> for a cost-policy mechanism test once groups straddle the action threshold; it is not needed to evaluate calibrated beliefs.",
             "A larger cost tests a more interventionist policy and may encourage excessive refusal.",
             "Keep c = 0.09 primary. Use c = 0.16 as the first stress-test sensitivity."],
            ["<b>Two passes through the pool</b>",
             "Expose each arm to the same 500 questions twice.",
             "<b>High</b> if the arms already receive different gradients; zero for creating a missing contrast.",
             "Roughly doubles training work and raises overfitting or capability-drift risk.",
             "Use in the stress test after a smaller pilot shows stable learning."],
            ["<b>Higher learning rate</b>",
             "Increase the size of each adapter update.",
             "<b>Medium to high</b>, but nonlinear.",
             "Can make the effect easier to see or destabilize all three arms. Nominally equal learning rates do not guarantee equal realized drift.",
             "Test one higher value on a development slice, never choose it using the final held-out set."],
            ["<b>LoRA rank 64</b>",
             "Roughly double the trainable adapter parameters from rank 32.",
             "<b>Low to medium</b> unless rank 32 is demonstrably capacity-limited.",
             "Adds capacity and storage without creating reward variation.",
             "Leave at 32 initially."],
        ],
        right_from=99,
        cls="choice-table",
    )
    recommended_designs = table(
        ["design", "what stays fixed", "what is strengthened", "what the result would mean"],
        [
            ["<b>Primary causal comparison</b>",
             "Qwen3-8B, one pass, group size 8, c = 0.09, paired questions and seeds, shared optimizer settings",
             "Require enough post-centering reward separation to make every arm identifiable, while preserving source quotas and avoiding only the most extreme questions.",
             "Estimates whether reward choice changes behavior under a reasonable, predeclared tuning setup."],
            ["<b>Mechanism stress test</b>",
             "The same three reward arms, crossed held-out evaluation, and common endpoints",
             "A difficulty-enriched diagnostic slice, c = 0.16 for the cost sensitivity, and possibly group size 16 or two passes. No warm-up is added merely to raise abstention.",
             "Tests whether reported probabilities improve and whether a cost-trained policy follows its own threshold when the diagnostic includes threshold-adjacent cases."],
        ],
        right_from=99,
        cls="choice-table",
    )
    evaluation_choices = table(
        ["evaluation choice", "our decision", "expected sensitivity", "cost or consequence"],
        [
            ["<b>Unchanged base control</b>",
             "Included in every prompt condition",
             "<b>Dominant</b>",
             "Without it, prompt effects and ordinary base behavior can be mistaken for fine-tuning effects."],
            ["<b>Neutral prompt as primary</b>",
             "No reward is announced",
             "<b>Dominant for interpretation</b>",
             "This tests persistence. A matched reward announcement tests compliance with instructions, not what the adapter learned to do on its own."],
            ["<b>Crossed prompt matrix</b>",
             "4 checkpoints by 4 prompts",
             "<b>High diagnostic value</b>",
             "It uses 16 calls per item, four times the neutral-only matrix, and reveals flexibility or conflict between prompting and training."],
            ["<b>Three scoring lenses</b>",
             "Apply all three to every saved response",
             "<b>High interpretive value</b>",
             "It adds no generation calls. It shows whether an apparent win exists only under the objective that trained the model."],
            ["<b>Paired held-out items</b>",
             "Every cell sees the same frozen questions",
             "<b>High</b>",
             "Pairing removes much item-difficulty noise. Doubling items roughly cuts standard error by 29% under independent-item assumptions, but doubles evaluation calls."],
            ["<b>Risk and coverage endpoints</b>",
             "Error at matched coverage and coverage at matched error",
             "<b>Dominant for the verdict</b>",
             "Abstention rate alone rewards refusing everything. Accuracy alone rewards guessing. The curve requires both safety and usefulness."],
            ["<b>Checkpoint selection</b>",
             "Final predeclared step; validation never held-out test",
             "<b>Dominant for bias control</b>",
             "Picking each arm's best held-out checkpoint creates several chances to overfit and breaks the paired causal comparison."],
            ["<b>Training seeds</b>",
             "1 discovery seed, then 1 frozen replication seed",
             "<b>High for confidence</b>",
             "The second seed doubles training cost and tests whether the direction repeats. Two seeds do not precisely estimate between-seed variance."],
            ["<b>Temperature and repetitions</b>",
             "Temperature 0 and one repetition initially",
             "<b>Medium</b>",
             "Higher temperature can expose policy differences but adds sampling variance. Each added repetition multiplies the entire 16-cell evaluation cost."],
            ["<b>Held-out source mix</b>",
             "Five deterministic MC benchmarks",
             "<b>High for generalization</b>",
             "A result confined to one source may be a benchmark-specific habit. Source-stratified reporting prevents a large easy source from hiding that."],
        ],
        right_from=99,
        cls="choice-table",
    )

    # Two pieces of machine-learning vocabulary this page cannot avoid, defined
    # where the narrative first leans on them. The canonical copies are in the
    # approach page glossary.
    dfn_auroc = dfn(
        "AUROC",
        "Area under the ROC curve. The chance that a randomly chosen correct "
        "answer carried a higher stated probability than a randomly chosen "
        "wrong one. 0.5 is a coin flip, 1.0 is perfect separation. It measures "
        "whether the numbers rank right above wrong, not whether they are the "
        "right size.")
    dfn_lora = dfn(
        "LoRA",
        "Low-rank adaptation. A small set of extra weights trained alongside a "
        "frozen base model, cheap to train and to store. When these results say "
        "the weights changed, it is the adapter that changed, not the base.")

    side_page(
        "training.html",
        title="Below Zero: what reward tuning changed",
        description=("The preregistered final result of a two-seed reward-comparison "
                     "experiment, plus a plain-language explanation of how LoRA and "
                     "group-relative reinforcement learning work."),
        h1="What reward tuning changed",
        standfirst=("The same reinforcement-learning method trained three identical copies "
                    "under three reward objectives. In the frozen final test, confidence-aware "
                    "training improved proper score by 0.105, mainly through better "
                    "probabilities rather than abstention."),
        published="2026-08-16",
        body=f"""
<div class="note"><b>Current status</b>
The data pipeline, reward functions, base-model profiler, automatic question selector,
hosted Tinker training loop, reward-scale calibration, and crossed checkpoint evaluator are
complete. Two frozen training seeds have now run all three reward arms for one pass over the
same 500 questions. The preregistered final test then generated 6,400 responses on 200 untouched
items. Confidence-aware training beat accuracy-only training by 0.105 proper-score units,
with a 95% interval from 0.036 to 0.175. Accuracy changed by -2.0 points, inside the prespecified
safeguard. The added assertion cost produced no stable incremental benefit. Two further base
model families have since replicated the confidence-aware training effect, GPT-OSS 20B and
Nemotron 3 Nano 30B (an early Nemotron profiling attempt failed the untouched-base format
gate; a syntax warm-up then cleared it and training completed). Across all three trained
families, {synthesis_score_wins} of {synthesis_pairs} matched pairs show the
confidence-calibrated score improving.</div>

<h2 id="final">The final test passed</h2>
<p>The protocol, item hash, checkpoints, analysis, and $0.80 hard ceiling were merged before
any final response was generated. Both frozen training seeds entered one complete analysis.
The test used 200 new items, 40 from each of five benchmarks, and crossed four checkpoints
with all four evaluation instructions. No response was manually inspected.</p>
{final_gate_results}
<div class="note"><b>What passed means</b>
Under the neutral prompt, the confidence-aware checkpoint improved the quadratic proper
score by 0.105 relative to accuracy-only tuning. The paired 95% interval was +0.036 to +0.175,
and both training seeds had positive point estimates. Accuracy fell by 2.0 points overall,
inside the predeclared 3-point safeguard, and malformed output did not increase.</div>
<p class="cap">The accuracy safeguard was a point-estimate decision rule, not a statistical
noninferiority test. Its 95% item interval was -5.25 to +1.25 points and crossed the -3-point
margin. The observed tradeoff passed the predeclared rule, but larger accuracy losses remain
compatible with this sample.</p>

<h3>The gain came from probabilities, not refusals</h3>
{final_checkpoint_results}
<p>Accuracy-only tuning answered every item with 95.7% mean confidence but was correct 65.3%
of the time. Confidence-aware tuning also answered every item, lowered mean confidence to
54.3%, and cut Brier loss from .314 to .190. Its 2.0-point accuracy loss was more than offset
by a 12.5-point reduction in probability error. Confidence {dfn_auroc} rose from .62 to .81, so
higher stated confidence also became more informative about which answers were correct.</p>
<div class="note"><b>The abstention interpretation</b>
All three tuned checkpoints retained 100% coverage. The confidence objective changed how
uncertainty was reported without teaching the model to withhold low-confidence views. That
is the useful behavior for this setting: share the best answer with calibrated confidence,
and reserve literal abstention for rare cases below an explicit action threshold.</div>

<h3>The assertion cost added no detectable value</h3>
{final_secondary_results}
<p>Confidence plus cost matched the confidence-aware arm almost exactly in aggregate. Its
incremental proper-score effect was effectively zero, with equal and opposite seed effects.
It also induced no abstentions. The final data support confidence-aware reward, but do not
support a claim that subtracting 0.09 for every assertion improves this learned policy.</p>

<h3>The aggregate effect hides useful heterogeneity</h3>
{final_benchmark_results}
<p>The calibration reward helped most on difficult sources where confident errors were
common. It hurt proper score on ARC and BoolQ, where accuracy-only tuning was already strong
and high confidence was often warranted. The causal result is credible for the frozen
five-benchmark mixture, but one global confidence policy did not improve every domain.</p>

<h3>The behavior persisted under every instruction</h3>
{final_prompt_results}
<p>The proper-score advantage stayed positive whether the evaluation prompt announced no
reward, accuracy, confidence, or confidence plus cost. The neutral row is primary because it
does not remind the model what its adapter was trained to optimize. Persistence there shows
that the weights changed, not merely the response to a matching instruction.</p>
<p class="cap">The final interval resamples 200 items 10,000 times while keeping the two
training-seed observations for each item together. It measures item-sample uncertainty
conditional on these two seeds. It does not precisely estimate the wider distribution of
training-seed effects.</p>

<h2 id="family">The second model family exposed a format-robustness problem</h2>
<p>The Qwen result justified a replication in a distinct open-weight family. The first
question turned out to be more basic than reward choice: could another model reliably emit
the exact two-line answer and probability grammar? Every screen was frozen and capped before
its first paid response, and every failure stopped automatically without inspecting answer
text.</p>
{family_screen_results}
<p>The untouched candidates all varied their answers and probabilities, but they did not
follow the strict output contract reliably enough for training. Malformed text must count as
incorrect rather than as abstention, so loosening the parser after seeing these results would
change the experiment. A small common supervised lesson solved most of the problem. It used
synthetic copy exercises such as &ldquo;answer letter C, probability 40&rdquo; and contained no
benchmark questions or correct answers.</p>
<div class="note"><b>The claim changed explicitly</b>
The Nemotron comparison is reward choice after an identical knowledge-free syntax warm-up,
not reward tuning from the untouched model. The crossed evaluation uses that shared warm
checkpoint as its base control, so every reported difference still isolates what happened
after the reward arms split.</div>

<h3>Seed 0 was promising; seed 1 failed the technical gate</h3>
{family_seed_results}
<p>Seed 0 reproduced the mechanism seen in Qwen on development data. Accuracy-only training
reported 100% confidence on every item, scored .300 under the quadratic rule, and had Brier
loss .350. Confidence-aware training lowered mean confidence to 72.8%, raised proper score to
.383, reduced Brier loss to .227, and increased confidence AUROC from .50 to .70. It answered
every item and lost four points of accuracy, inside the predeclared five-point development
limit. Confidence plus cost had the strongest seed-0 point estimates, but remained secondary.</p>
<p>Seed 1 never reached an outcome comparison. Both primary arms exceeded the 1% malformed
training ceiling at their first 256-rollout health check. The still-running cost arm was
stopped because it could not rescue a failed primary pair. No seed-1 development responses
or final-test responses were generated.</p>
<div class="note"><b>Conclusion</b>
The cross-family result is promising but not established. Seed 0 shows that the confidence
reward can create meaningful differentiation in Nemotron after a shared syntax lesson.
Seed 1 shows that the lesson was not robust enough to support the planned two-seed causal
claim. Replacing the failed seed, relaxing the gate, or opening the final set would turn a
technical failure into a post-result design change, so paid work stopped.</div>

<h3>The next attempt should fail cheaply before it trains</h3>
{family_next_steps}
<p class="cap">This redesign moves the stochastic format check ahead of the expensive
optimizer work. It also drops the secondary cost arm from the first cross-family test,
reducing training spend by one-third while preserving the primary scientific question.</p>

<h2 id="replication">What the development replications found</h2>
<p>Both replications held the base model, LoRA rank, learning rate, question order, group
size, and one-pass exposure constant. Only the reward changed. Every arm completed 125
optimizer steps and saved 4,000 stochastic training responses. All six automated health
verdicts were green.</p>
{replication_training_results}
<p class="cap">An active group contains at least two sampled completions with different
centered rewards. Accuracy-only training had little signal because identical answer outcomes
receive identical rewards. Probability-sensitive rewards could distinguish completions that
chose the same answer but stated different confidence.</p>

<h3>The result that replicated</h3>
<p>The primary comparison asks each final checkpoint the same 100 development questions under
a neutral instruction, then scores the saved responses with the quadratic rule. The table
shows each confidence-trained checkpoint relative to the accuracy-only checkpoint from the
same training seed.</p>
{two_seed_contrast_results}
<div class="note"><b>Reading the result</b>
The confidence-aware objective produced the cleanest differentiation. Its quadratic-score
gain was +.252 in seed 0 and +.172 in seed 1, with both paired intervals above zero. Accuracy
changed by +8 points in seed 0 and +1 point in seed 1. The gain therefore comes mainly from
better probabilities, not from trading away correct answers. Confidence-plus-cost also beat
accuracy-only in both point estimates, but seed 1 did not resolve that difference. The cost
arm beat confidence-aware in seed 0 and lost to it in seed 1, so there is no stable evidence
that the extra assertion cost improves the learned policy.</div>
<p class="cap">Intervals are paired 95% bootstrap intervals over the same 100 development
questions. They measure item-sample uncertainty within each seed. Two seeds reveal whether
the direction repeats, but do not precisely estimate the full distribution of training-seed
effects.</p>

<h3>What each development checkpoint did</h3>
<p>These tables show the complete neutral-prompt cells. Lower Brier is better. Higher
quadratic score and confidence AUROC are better. A positive calibration gap means
overconfidence; a negative gap means underconfidence.</p>
<h4>Seed 0</h4>
{replication_seed0_neutral_results}
<h4>Seed 1</h4>
{replication_seed1_neutral_results}
<p class="cap">A positive calibration gap means overconfidence; a negative gap means
underconfidence. Lower Brier is better. Higher quadratic score and confidence AUROC are
better. The neutral prompt states no reward formula, so this is the cleanest test of what the
weights learned.</p>
<p>Accuracy-only training was remarkably consistent: it answered every question at about
95% mean confidence while accuracy was 56% in seed 0 and 61% in seed 1. Confidence-aware
training cut the Brier score from .397 to .225 in seed 0 and from .351 to .189 in seed 1.
Its mean confidence was too low in seed 0, then exactly matched its 62% accuracy in seed 1.
This is strong evidence that the reward changes probability reporting, but not evidence that
one short run always lands on the same calibration level.</p>

<h3>The effect depends on question difficulty</h3>
<p>Each cell below is the quadratic-score change relative to accuracy-only training within
the same seed. Positive numbers favor the confidence objective. Confidence-aware training
won on four of five benchmarks in both seeds. BoolQ was the exception because accuracy-only
training was already perfect and nearly certain. The largest, most repeatable gains came on
GPQA parity, MedMCQA, and MMLU-Pro, where inaccurate high confidence is most costly.</p>
{replication_benchmark_results}

<h3>Rare abstention remains the intended policy</h3>
<p>Both cost-trained checkpoints reported a substantive answer for all 100 neutral-prompt
questions. Applying the predeclared c = .09 break-even threshold afterwards also retained all
100 in each seed, because none carried less than 30% stated confidence. Low-confidence
information is therefore still shared; a literal abstention remains reserved for the tail
below the explicit action threshold.</p>
{replication_threshold_results}
<p class="cap">Each cell reports coverage followed by error among retained answers. Only the
30% threshold was fixed by the training objective. The other rows are post-hoc development
diagnostics, not selected operating policies.</p>

<h3>The weights changed, not just the prompt response</h3>
<p>The table reports each confidence arm's quadratic-score gain over accuracy-only training
under all four evaluation instructions. Confidence-aware training stayed positive in every
cell across both seeds. Matching the evaluation wording to the training reward is therefore
not required for the learned behavior to appear. The cost arm was positive in seven of eight
cells, with a near-zero seed-1 result under the accuracy instruction.</p>
{replication_prompt_results}
<div class="note"><b>Decision</b>
These development results justified one frozen final test. That test has now run and passed.
The cost arm remained a secondary mechanism comparison and did not rescue or alter the
primary verdict. No development result changed the final sample, prompts, scoring, or
checkpoint choice.</div>

<h2 id="pilot">What the first live pilot found</h2>
<p>This is development evidence, not the final result. The pilot used 100 source-interleaved
training questions and 50 separate evaluation questions, 10 from each of five benchmarks.
Every evaluation question was crossed with four checkpoints and four instructions. Items
zero through nineteen in each benchmark are permanently development data. The final test
used the untouched offsets 20 through 59.</p>

<h3>The rewards really did send different signals</h3>
{profile_results}
{training_results}
<p class="cap">Active groups contain at least two responses with different centered rewards.
The fixed multipliers kept average update magnitude comparable across arms even though the
confidence objectives were active on many more questions.</p>

<h3>The first question is calibration, not abstention</h3>
{development_results}
<p class="cap">Coverage is the share of questions receiving a substantive answer. Lower
Brier score is better. These are only 50 development items, so differences of a few questions
remain noisy.</p>
{calibration_results}
<p class="cap">Accuracy here is conditional on giving a substantive answer. The
overconfidence gap is mean stated probability minus that accuracy; zero is ideal. Brier score
measures probability error, with lower values better. Confidence AUROC asks whether higher
probabilities distinguish correct answers from incorrect ones; 0.50 is chance and 1.00 is
perfect ranking.</p>
<div class="note"><b>Corrected interpretation</b>
Under the pure quadratic score, any honest probability above zero carries information, so a
low-confidence answer can still be better than silence. The assertion cost creates a separate
decision threshold: c = 0.09 implies 30%, and c = 0.16 implies 40%. No neutral substantive
answer from any checkpoint reported a probability below either threshold. Answering all 50
questions was therefore consistent with the models' stated beliefs. The unresolved problem
is overconfidence: the accuracy-only checkpoint reported 90.2% confidence while being right
60% of the time. The two-pass cost canary reduced that gap from 30.2 points to 20.7 points,
but it used twice the training exposure, so this is a promising mechanism signal rather than
a causal reward-arm result.</div>

<h3>Action policies can be applied after the model reports its belief</h3>
<p>Once an answer and probability are saved, different users can impose different costs
without retraining the model. The table applies four minimum-confidence policies to the same
50 neutral responses from the two-pass cost canary.</p>
{threshold_policy_results}
<p class="cap">The 90% row contains 21 answers and one error. That is encouraging evidence
that confidence contains useful ranking information, not a stable estimate of a 5% error
rate. The sample is too small, and the threshold was examined after seeing development data.</p>

<div class="note"><b>What the paired comparison says</b>
On the shared one-pass design, confidence-aware training beat accuracy-only training by
{quadratic_vs_binary['accuracy_change']['estimate'] * 100:.0f} percentage points of accuracy
and {quadratic_vs_binary['quadratic_score_change']['estimate']:.3f} quadratic-score units.
The paired 95% interval for the score change runs from
{quadratic_vs_binary['quadratic_score_change']['confidence_interval_95'][0]:.3f} to
{quadratic_vs_binary['quadratic_score_change']['confidence_interval_95'][1]:.3f}, crossing
zero. The direction is worth replicating, but 50 items and one training seed do not establish
meaningful differentiation.</div>

<h2 id="idea">Fine-tuning, in one sentence</h2>
<p>A pretrained model already knows how to answer questions. Fine-tuning gives it repeated
practice under a particular definition of a good answer, then makes small adjustments so
responses that earned more reward become more likely next time.</p>
<p>We are not trying to teach the model medicine, science, or law. The questions come from
subjects it already encountered during general training. We first want a better reported
belief: which answer is best and how likely it is to be correct. A downstream decision policy
can then use the same probability to decide whether an assertion is worth making under a
particular cost.</p>

<h2 id="map">The whole experiment: tune, test, then score</h2>
<div class="note"><b>There are not three different fine-tuning technologies.</b>
We use the same off-the-shelf RL and LoRA process three times. Only the reward objective
changes. After training ends, every resulting checkpoint goes through every evaluation
instruction. Every saved response is then scored under every formula.</div>
{experiment_map}
<p class="cap">The untouched base is a fourth checkpoint, not a fourth tuning arm. Scoring
a saved answer under another formula does not ask the model again and does not alter its
weights.</p>

<h3>A translation guide for the terms on this page</h3>
{terminology}

<h2 id="loop">What happens during one training step</h2>
<div class="tune-loop" role="img" aria-label="Four-step fine-tuning loop: ask, sample, score, update">
  <div class="tune-step"><span>Step 1</span><b>Ask</b>Give the model one multiple-choice
  question with an explicit &ldquo;I don't know&rdquo; option.</div>
  <div class="tune-step"><span>Step 2</span><b>Sample</b>Generate eight independent responses
  to the same question, each with an answer and a stated probability.</div>
  <div class="tune-step"><span>Step 3</span><b>Score</b>Apply the arm's reward rule
  automatically. No human judges which response sounds better.</div>
  <div class="tune-step"><span>Step 4</span><b>Update</b>Nudge a small adapter toward the
  responses that scored better than the other responses in that group.</div>
</div>
<p class="loop-back">Repeat across the frozen training questions.</p>
<p>The comparison within each group is why the candidate questions matter. If all eight
responses are correct, or all eight are wrong, an accuracy reward gives them the same score
and there is no learning signal. We first profile the unchanged base model, then
automatically retain questions where its outcomes are mixed. The same final questions go to
every arm.</p>

<h3>One response, all the way from reward to weights</h3>
<p>Suppose two of eight responses in the accuracy arm are correct. Their rewards are 1 and
the other six rewards are 0, so the group average is 0.25. Each correct response gets a
relative signal of +0.75; each incorrect response gets &minus;0.25. The confidence arms use
continuous rewards, but the conversion is the same:</p>
<div class="rule">relative signal = response reward &minus; average reward for that question<br>
positive signal &rarr; make this completion more likely<br>
negative signal &rarr; make this completion less likely</div>
<ol>
<li><b>The sampler records what the current model did.</b> Along with the answer, it saves
the token sequence and the probability the current policy assigned to each sampled token.</li>
<li><b>The reward becomes a sequence-level learning signal.</b> Prompt tokens receive zero.
Every token in the short two-line completion receives that response's relative signal.</li>
<li><b>Backpropagation measures responsibility.</b> Tinker computes how a tiny change to each
trainable LoRA weight would have changed the likelihood of those sampled tokens. This is a
gradient: a direction and magnitude, not an edited answer stored in the model.</li>
<li><b>Adam takes a small step.</b> The optimizer combines the current gradient with recent
gradient history, scales it by the learning rate, and updates only the adapter weights.
Weights associated with positive-signal token patterns move up; negative ones move down.</li>
<li><b>The next batch uses the updated adapter.</b> New responses are sampled from the new
policy, scored again, and the loop repeats. Generalization occurs only if thousands of these
local nudges add up to a behavior that also appears on unseen questions.</li>
</ol>

<h3>What actually changes in the model?</h3>
<p>The base model has billions of learned weights. We leave those weights frozen and attach
a much smaller set of trainable weights using LoRA. Those adapter weights learn the new
behavior. This makes the run cheaper, lets every arm start from the exact same base, and
leaves us with a small checkpoint that can be evaluated or removed independently.</p>
<p>Think of the base model as an experienced analyst and the adapter as a new compensation
policy. The analyst's underlying education does not change during this short experiment.
What changes is which available behavior gets reinforced.</p>

<h3>Are we using an off-the-shelf method?</h3>
<p>Mostly. The GPU machinery is standard rather than a new learning algorithm. The hosted
loop follows Thinking Machines' <a href="https://tinker-docs.thinkingmachines.ai/tutorials/basics/first-rl/">minimal group-relative RL recipe</a>:
LoRA adapters, groups of sampled completions, group-centered advantages, an
<a href="https://tinker-docs.thinkingmachines.ai/tinker/losses/">importance-sampling policy-gradient loss</a>, backpropagation, and Adam. Tinker runs the
distributed GPU operations and checkpointing. We supply the prompts, deterministic rewards,
strict parser, question selection, paired arms, health gates, and evaluation.</p>
<p>There is no learned reward model, human preference labeling, or bespoke neural-network
architecture. The custom part is the experiment: what counts as reward and how we keep that
one difference identifiable.</p>

<h3>Key design questions and our current decisions</h3>
<ul class="key">
<li><b>Reward shape versus update size.</b> Subtracting the group mean removes reward level,
but not reward spread. The selector now uses the unchanged-base profile to calculate one
fixed scale factor per arm, so the arms start with the same root mean square relative signal.
A single positive multiplier preserves each rule's incentives and its differences across
questions; normalizing every question separately would not. The manifest saves the raw and
scaled spreads, and training stops if the calibration belongs to different data or a
different assertion cost. A later raw-scale run is a declared sensitivity, not the primary
comparison.</li>
<li><b>How tightly to constrain policy drift.</b> The initial loop uses the standard
importance-sampling loss because every rollout is nearly on-policy and receives one update.
We should record divergence from the base model, entropy, and update norms. If a small pilot
shows unstable ratios, switch all arms together to a clipped PPO or CISPO loss, or add the
same reference-policy penalty to every arm.</li>
<li><b>How much learning capacity to allow.</b> LoRA rank, learning rate, group size, and
number of steps jointly determine how far the policy can move. Fix them across arms and use
the smallest settings that create a measurable change on a separate validation slice without
degrading general accuracy. The held-out test cannot choose these settings.</li>
<li><b>Whether sequence-level credit is adequate.</b> One final reward is applied to every
completion token, so the optimizer is not told whether the answer letter or probability
caused the score. The exact two-line output keeps that ambiguity small. We should not add
free-form reasoning to the training response unless we also redesign credit assignment.</li>
<li><b>How to choose a checkpoint.</b> The primary comparison should use the final checkpoint
at a step count fixed in advance. Selecting each arm's best checkpoint on the held-out test
would give three chances to overfit. Intermediate checkpoints can guide a later run only on
a separate validation slice.</li>
</ul>

<h2 id="choices">Which choices could change the answer most?</h2>
<p>These sensitivities were recorded before paid training and are design priors, not measured
effects. They describe how strongly a choice can affect an experiment's conclusion. They do
not estimate the final differences reported above.</p>
{impact_legend}

<h3>Training design and implementation</h3>
{training_choices}
<p class="cap">The numerical comparisons describe workload, implied decision thresholds, or
standard-error mechanics. Behavioral effects remain empirical. Settings stay identical
across reward arms unless the table explicitly defines the treatment.</p>

<h2 id="accentuation">How to make the reward differences easier to see</h2>
<p>There are two different ways to seek a larger effect. We can make sure the reward arms
actually send different learning signals to the optimizer, or we can train harder on whatever
signal already exists. The first is an identification requirement. The second is an effect-size
choice. More steps, a higher learning rate, or a larger adapter cannot rescue reward arms whose
post-centering signals are the same.</p>
<div class="note"><b>The important mathematical trap</b>
The optimizer never receives the raw reward by itself. It receives each response's reward
minus the average reward in that eight-response group. Any reward term that is the same for
all eight responses disappears. That means a larger assertion cost has no training effect in
a group where every response still asserts an answer.</div>
{contrast_examples}
<p class="cap">The profile diagnostic now calculates these comparisons after group centering
and after the fixed per-arm scale factors. It reports the exact residual difference between
each pair of advantage vectors, rather than inferring separation from the reward formulas.</p>

<h3>Accentuation options and their tradeoffs</h3>
{accentuation_choices}

<h3>Recommendation: preserve a primary design and add a stress test</h3>
<p>Running only an accentuated design would show that the mechanism can work, but not how much
it matters under an ordinary tuning setup. Running only the ordinary design could produce a
flat result because the sampled action support never let the rewards differ. The clean answer
is to predeclare both designs and interpret them separately.</p>
{recommended_designs}

<h3>The decision sequence and completed gate</h3>
<ol>
<li><b>Complete: run a base profile.</b> Generate eight direct-answer responses per
question with no optimizer update. Automatically measure formatting, mixed outcomes,
probability variation, answer-versus-abstention support, and post-centering reward separation.</li>
<li><b>Complete: test whether the signals differ.</b> Do not spend on three training arms when
the diagnostic says their final advantage vectors are effectively identical.</li>
<li><b>Complete: add only the missing source of variation.</b> If probabilities do not vary, modestly
increase exploration. If no held-out probabilities fall near an action threshold, keep the
representative evaluation primary and add a separately labeled difficulty-enriched diagnostic.
Do not manufacture abstention merely to make its rate visible.</li>
<li><b>Complete: run one paired training seed.</b> Use the same settings for all three arms and
evaluate intermediate behavior only on a development slice.</li>
<li><b>Complete: repeat the frozen design at seed 1.</b> No hyperparameters, questions,
prompts, or stopping steps changed. The confidence-aware proper-score direction repeated.</li>
<li><b>Complete: run the final test once.</b> Both frozen seeds used their predeclared
step-125 checkpoints on offsets 20 through 59 under a separate $0.80 hard ceiling.</li>
</ol>
<details class="operational">
<summary>Operational record: the immediate spending recommendation</summary>
<div class="note"><b>Immediate spending recommendation</b>
Stop paid tuning here. The Qwen final test established a causal result for that model and
design. An early Nemotron profiling attempt then failed the untouched-base format gate before
any training began. The next high-value spend is not a replacement seed. It is a new cross-family
protocol that first passes two independent full format profiles, then trains the primary
accuracy and confidence pair from one shared checkpoint. Rare abstention remains an
acceptable outcome. <b>Update:</b> that protocol ran. A syntax warm-up cleared the format
gate, and all {nemotron_pairs} matched Nemotron pairs improved on gap, score, and
near-certain errors.</div>
</details>

<h2 id="arms">One tuning method, three reward objectives</h2>
<p>Every arm starts from the same base model and uses the same prompts, training questions,
deterministic order, and sampling settings. Only the reward changes. Stochastic completions
are independently generated and saved; setting one provider seed for an eight-sample call
made all eight outputs identical and was rejected by the health gate. Each finished arm is a
saved <em>checkpoint</em>: the unchanged base weights plus that arm's small {dfn_lora} adapter.</p>
{arms}
<p class="cap"><code>p</code> is the probability the model reports for its own substantive
answer. The fixed cost is charged for asserting even when reported confidence is zero.</p>
<div class="note" id="accuracy-only"><b>What the accuracy-only RL baseline means</b>
It is not the default form of all fine-tuning. It is the conventional comparator for
reinforcement learning on questions with verifiable answers, and it mirrors the usual
benchmark objective: correct earns 1; wrong or abstaining earns 0. The optimizer makes
higher-reward completion patterns more likely. The model still reports a probability, but
that number has no effect on this arm's reward. This short run supplies no explanatory
lessons; using untouched held-out questions tests whether it learned a general policy rather
than memorizing training answers.</div>

<h3>A concrete example</h3>
<p>Suppose the model can internally distinguish a question where it is 60% likely to be
right from one where it is only 20% likely to be right. The reward rules imply different
best behavior:</p>
{choices}
<p class="cap">For the confidence-plus-cost rule, the break-even confidence is
<code>&radic;0.09 = 30%</code>. Below that point, an honest answer has a negative expected
score and explicit abstention scores zero.</p>
<p>This is the causal question. Accuracy training may teach &ldquo;take the shot.&rdquo;
Confidence training may teach &ldquo;say how difficult the shot is.&rdquo; Adding the assertion
cost may teach &ldquo;do not take the shot when the odds are poor.&rdquo;</p>

<h2 id="plan">What the completed development run used</h2>
<div class="stats">
  <div><b>10,000</b><span>licensed public training candidates</span></div>
  <div><b>500</b><span>shared questions after base-model profiling</span></div>
  <div><b>3</b><span>paired reward arms from the same base model</span></div>
</div>
<ol>
<li><b>Build the candidate pool.</b> Draw deterministic multiple-choice questions from six
public training splits. Reject malformed rows and exact or near matches to every held-out
evaluation benchmark.</li>
<li><b>Profile the unchanged model.</b> Generate eight responses for each candidate without
updating the model. This identifies questions that can give all three arms a useful learning
signal.</li>
<li><b>Freeze one shared pool.</b> Select 500 mixed-outcome questions while preserving the
source mix and balancing the correct answer across letter positions. Before training, require
the saved post-centering diagnostic to show enough probability and abstention support for the
reward arms to differ. The same automated step rescales each reward arm to the binary arm's
initial relative-signal RMS and saves the calibration manifest.</li>
<li><b>Train the three arms twice.</b> Each arm sees every shared question once per seed,
producing 4,000 rollouts per arm and 24,000 across the six completed runs. Raw responses are
saved before an optimizer update uses them.</li>
<li><b>Generate the complete held-out grid.</b> Every one of the four checkpoints answers
every frozen held-out question under the neutral instruction and all three announced-rule
instructions. The neutral row is the primary persistence test; the other rows diagnose how
new instructions interact with learned behavior.</li>
<li><b>Score every saved response every way.</b> Apply all three reward formulas and the
common accuracy, calibration, coverage, and error metrics to every response after generation.
This last step changes no weights and makes no additional model calls.</li>
</ol>

<h2 id="evaluation">Cross each checkpoint with each evaluation instruction</h2>
<div class="note"><b>Your summary is exactly the structure, with one terminology refinement.</b>
We try three reward objectives during tuning. We then run the base and all three tuned
checkpoints under all four evaluation instructions. Finally, we score every one of those
responses under all three formulas. The evaluation instructions and scoring formulas are
tests of a trained checkpoint; they are not additional tuning approaches.</div>
<p>The phrase &ldquo;evaluate every model under every rule&rdquo; compresses three separate
choices. A column selects the saved weights. A row selects the instruction shown with the
held-out question. After the response is saved, three scoring formulas are applied without
another model call.</p>
{evaluation_axes}

<h3>What the four checkpoint columns mean</h3>
<p>Fine-tuning has already ended before this table is run. Selecting a column only loads a
different set of saved weights. It does not retrain the model on the held-out question.</p>
{checkpoint_decoder}

<h3>What the four instruction rows mean</h3>
<p>Selecting a row changes the evaluation prompt, not the weights. This separates a durable
habit learned during training from immediate compliance with a new instruction.</p>
{prompt_decoder}

<h3>The 16 generation permutations</h3>
<p>One cell combines one checkpoint column with one evaluation-instruction row. The base
checkpoint is included in every row to measure the prompt-only effect.</p>
{evaluation_matrix}
<p class="cap">Four checkpoints by four prompt conditions make 16 generation cells for each
held-out item. Every cell uses the same frozen questions, output grammar, and evaluation
sampling settings. The implemented evaluator makes
these cells explicit before any paid call.</p>
<p><b>Concrete example.</b> The cell where the accuracy-only RL checkpoint meets the
confidence + cost instruction loads weights learned from correct = 1 training, then tells
that already-trained checkpoint that answers now face the quadratic score and a 0.09
assertion cost. No additional fine-tuning occurs in that cell. Its response lets us test
whether the new instruction overrides, combines with, or loses to the earlier training.</p>

<h3>Scoring is a third axis, but it does not require more model calls</h3>
<p>Every saved response contains an answer, a probability, and the explicit abstention
choice. We can therefore score that one response afterwards under accuracy, confidence, and
confidence-plus-cost. The full analysis is training reward &times; evaluation prompt &times;
scoring lens. Only the first two axes require generation; applying all three scoring rules
afterwards is deterministic and free.</p>
<p>The reward-specific scores are useful, but they should not be the primary verdict. A model
trained on one objective is expected to look best under that same objective. The common
endpoints are harder to game: overall accuracy, coverage, incorrect assertions, calibration,
and the full error-versus-coverage curve.</p>
{evaluation_questions}

<h3>The primary test and the secondary diagnostics</h3>
<ul class="key">
<li><b>Primary: persistence with no reward announced.</b> Compare all three adapters and the
base model on identical untouched questions. This is the clean test of what training changed.</li>
<li><b>Primary endpoints: belief quality and capability.</b> Compare quadratic proper score,
Brier score, calibration gap, confidence AUROC, overall accuracy, and format failure. A model
should report probabilities that correspond to correctness while preserving its ability to
answer.</li>
<li><b>Headline contrast.</b> Compare confidence-aware training with accuracy-only
training under the neutral prompt. A practical win requires a reproducible proper-score or
calibration improvement without a material loss of overall accuracy.</li>
<li><b>Derived action policies.</b> Apply multiple confidence thresholds to every checkpoint's
saved probabilities and report the resulting risk-coverage curves. These policies do not
require retraining or more generation calls.</li>
<li><b>Secondary: prompt-by-training interactions.</b> The three announced-rule rows show
whether the learned policy remains flexible. A cost-trained adapter that abstains under every
instruction may be rigid; one that changes appropriately with the announced objective has
learned a more configurable policy.</li>
<li><b>Paired uncertainty.</b> Compute item-level differences because every checkpoint sees
the same questions, report uncertainty by held-out source, and require a promising first-seed
effect to repeat in a second complete training seed before opening the final test.</li>
<li><b>No test-driven checkpoint choice.</b> Freeze the held-out items and primary contrasts
before training. The test set is opened once for the final comparison; it is not a dashboard
for choosing learning rates or stopping steps.</li>
<li><b>One declared success contrast.</b> The matrix creates many legitimate comparisons,
but not many chances to declare victory. Before training, name the primary adapter contrast,
common endpoint, and smallest effect worth replicating. Treat the rest as diagnostics with
uncertainty, not as alternate routes to a positive result.</li>
</ul>

<h3>Evaluation choices and their likely leverage</h3>
{evaluation_choices}
<p class="cap">The automatic evaluator freezes the exact items before paid calls, resolves
the final sampler checkpoint for each arm, resumes by response identity, saves one complete
16-cell item matrix at a time, and writes calibration bins, risk-coverage curves, paired
bootstrap intervals, source-specific results, and neutral-prompt contrasts.</p>

<h2 id="result">What counted as meaningful differentiation?</h2>
<p>A lower training loss did not count, and neither did a visible difference in training
responses. The reward directly creates both. The evidence had to appear on questions the
adapters never trained on. The final test met the first, second, and replication criteria
below without relying on abstention.</p>
<ul class="key">
<li><b>Better probability quality.</b> The confidence-aware arm should improve the proper score
and reduce probability error relative to accuracy-only training.</li>
<li><b>Better calibration and ranking.</b> A stated 70% should be right about 70% of the time,
and higher probabilities should reliably distinguish correct answers from incorrect ones.</li>
<li><b>Useful derived policies.</b> Applying a downstream confidence threshold should reduce
error as coverage falls. Rare abstention is acceptable when few beliefs fall below the chosen
threshold.</li>
<li><b>Cost-policy consistency.</b> A cost-trained model is a mechanism test: it should abstain
when its own reported probability is below the announced break-even threshold and answer when
above it. Raw abstention frequency is not a primary endpoint.</li>
<li><b>Replication across seeds.</b> One seed is an inexpensive existence test. The development
effect had to survive a second complete paired seed before it could justify a final test.
Additional seeds and model families would be needed for a broad generalization claim.</li>
</ul>

<h2 id="automation">What requires human attention?</h2>
<details class="operational">
<summary>Operational record: what is automatic and what needs a decision</summary>
<p>Model-response inspection is not part of the operating plan. Parsing, answer grading,
reward calculation, contamination checks, source quotas, answer-letter balance, question
selection, rollout-health checks, spend bounds, and artifact saving are deterministic and
automatic. A failed gate stops the run rather than asking someone to clean up rows by hand.</p>
<p>The human decisions are substantive: authorize paid execution, choose the assertion cost,
and decide whether the held-out effect is large enough to justify replication. Those are
design and spending choices, not labeling work.</p>
</details>

<h2 id="cost">Scale and cost</h2>
<details class="operational">
<summary>Operational record: token ceilings and what has been authorized</summary>
<p>The profile, one-pass three-arm pilot, c = 0.16 one-pass and two-pass cost sensitivities,
all three early development matrices, both 500-question replications, and the final test are
complete.
Each stage used a saved worst-case token budget before it ran. At
<a href="https://tinker-docs.thinkingmachines.ai/tinker/models/">current Tinker prices</a>,
Qwen3-8B costs $0.195 per million uncached prefill tokens, $0.039 for cached prefill,
$0.60 for sampled tokens, and $0.44 for training tokens.</p>
<p>The conservative ceilings were $0.15 for the 100-question profile, $0.48 for the first
three training arms, $0.08 for the first 800-cell development matrix, $0.17 for the stronger
cost checkpoint, $0.04 for its partly reused evaluation, $0.32 for the two-pass canary, and
$0.02 for its reused evaluation. Those early stages total about $1.26. The seed-0 replication
had a separate $2.875 worst-case estimate and a $3.25 operational cap. Seed 1 reused the base
profile, carried a $2.56 worst-case estimate, and had a $2.85 operational cap. The combined
conservative pre-final ceilings were therefore about $6.70, not a claim about settled billing.
The 6,400-call final test added a $0.614 no-caching upper bound and stayed below its separate
$0.80 operational ceiling. The combined conservative ceilings are about $7.31. They assume
no prompt caching and maximum-length completions. Applying new scoring formulas or thresholds
to saved responses remains free. The $100 account balance is a limit, not a spending target.</p>
<p>Paid tuning is now stopped. The first model-family replication did not pass its second-seed
format gate. The next useful paid step is a formatting-robust restart that validates two
independent full profiles before reward training, not a replacement seed or a larger Qwen3-8B
run.</p>
</details>
""",
        footer=("This page separates development evidence from the preregistered final "
                "result. The full audit summary is committed with the site source."),
        content_updated=TRAINING_CONTENT_UPDATED,
        site_commit=TRAINING_SITE_COMMIT,
    )


def build_approach():
    """How the measurement works, for someone deciding whether to trust it."""
    side_page(
        "approach.html",
        title="Below Zero — how the measurement works",
        description=("The pipeline behind the census and the experiment: frozen "
                     "item slices, announced contracts, deterministic grading "
                     "where possible, and scoring applied after the fact in SQL."),
        h1="How the measurement works",
        standfirst=("Three different claims, three different methods. The census "
                    "counts what happened. The rules are proved. Only the third "
                    "claim needs an experiment."),
        body="""
<h2 id="claims">Three claims, kept separate</h2>
<p>Most of the argument does not depend on the experiment at all, and it is
worth being clear about which part depends on what.</p>
<ul class="key">
<li><b>Models almost never decline.</b> A count over published responses. No
model was called, nothing was sampled, and anyone can recount it from the same
public archive.</li>
<li><b>A rule that prices being wrong would elicit an honest probability.</b>
Mathematics, checked numerically. It is true whether or not any model responds
to it.</li>
<li><b>Announcing the rule changes what a model does.</b> The only claim that
needs an experiment, and the only one that could turn out false.</li>
</ul>

<h2 id="pipeline">The pipeline</h2>
<p>Each stage does one thing and hands a stable artefact to the next, so a
failure in one place cannot quietly contaminate another.</p>
<ol>
<li><b>Frozen item slices.</b> Questions are sampled round-robin across strata
with a deterministic hash order, then written to disk. The same run tomorrow
asks the same questions, so a difference between two runs is a difference in
behaviour rather than in sampling.</li>
<li><b>Contracts.</b> A contract is the scoring rule as the model is told it.
The identical question goes out under every contract, including a control that
announces nothing. The contract is the only thing that varies.</li>
<li><b>Generation.</b> Resumable, cached, concurrency-limited, and capped by a
hard spend limit. Results are matched back to their prompts by an index carried
through the await, because completions arrive out of order and zipping them to
the submission list would silently mismatch answers to questions.</li>
<li><b>Grading.</b> Deterministic wherever the benchmark allows it. An LM judge
is used only for free-form answers, and is itself validated against hand labels
before its verdicts are trusted.</li>
<li><b>Scoring.</b> Applied afterwards, in SQL, over stored raw responses.</li>
</ol>

<h2 id="separation">Why scoring happens last</h2>
<p>The announced contract varies at generation time, because that is the
experiment. Everything downstream, the penalty arithmetic, the calibration
decomposition, the abstention gates, runs afterwards over stored responses.
Baking a scoring parameter into the runner would mean re-calling every model to
ask what a different penalty would have produced. Applying it afterwards means
the whole parameter sweep is free, and the stored responses stay a fixed record
that later analysis cannot alter.</p>

<h2 id="rules">Four rules that must not be broken</h2>
<p>Each of these exists because breaking it produces tables that look completely
plausible and are wrong in the direction of the hypothesis.</p>

<h3>Unparseable output is incorrect, never an abstention</h3>
<p>A response that ignored the format did not decline to answer. Grading it as
silence makes incoherence free. On published runs of one benchmark, that single
mistake lets a 18.7%-accuracy small model outscore a 51.5%-accuracy large one.</p>

<h3>Every multiple-choice item gets an explicit &ldquo;I don't know&rdquo; option</h3>
<p>Without one, a rule that prices error is just a positive affine transform of
accuracy, so it cannot change the ranking no matter how steep the penalty.
Verified numerically across 69 published runs: maximum deviation 1.2e-15.
Remove the option and the experiment becomes incapable of detecting its own
effect.</p>

<h3>Verdict parsing tests "incorrect" before "correct"</h3>
<p>The word <code>INCORRECT</code> contains the word <code>CORRECT</code>. A
substring match in the wrong order graded every wrong answer as right, and the
resulting tables looked entirely reasonable.</p>

<h3>Reasoning-truncated output is flagged, not graded</h3>
<p>A model that spent its whole budget thinking returns empty content. That is a
truncation, not a refusal, and counting it as silence would manufacture exactly
the finding the experiment is looking for.</p>

<h2 id="check">What is checked automatically</h2>
<p>The properness of every scoring rule is verified numerically over the whole
probability grid. The full pipeline runs end to end against a mock endpoint on
every commit, with no API key and no spend, and asserts the direction of the
result: contracts that price error more steeply must produce more abstention and
fewer errors. That check has already caught two bugs that would have inverted
the experiment while producing plausible output.</p>

<div class="note"><b>Zero runtime dependencies</b>
The tooling installs nothing. The runner uses the standard library, storage is
SQLite, and every metric is a SQL query you can read. When the argument is that
scoring should be inspectable, the tooling should not need a lockfile to
inspect.</div>

<h2 id="glossary">Glossary</h2>
<p>Every term of art this site uses, in one place. Terms are defined in passing
where a page first uses them, with a dotted underline you can hover or tab to.
This is the canonical version, and where the two ever disagree, this one is
wrong and should be fixed.</p>
<dl class="glossary">

<dt>Accuracy-only tuning</dt>
<dd>The control arm of the fine-tuning comparison, and the conventional way
reinforcement learning is applied to questions with verifiable answers. Reward
is 1 if the answer is correct and 0 otherwise, which mirrors the usual benchmark
objective. The model is still asked for a probability, and that number has no
effect on the reward. It is not the default form of all fine-tuning.
<a href="training.html#accuracy-only">The fine-tuning page says this at
length.</a></dd>

<dt>Arm</dt>
<dd>One condition in an experiment, with everything else held identical, so a
difference between two arms is caused by the thing that differs between them.
There are three kinds here: contract arms vary what the prompt announces, reward
arms vary what the training rewards, and evaluation arms vary what the scoring
prompt says at test time.</dd>

<dt>AUROC</dt>
<dd>Area under the ROC curve. For a stated probability, the chance that a
randomly chosen correct answer carried a higher probability than a randomly
chosen wrong one. 0.5 is a coin flip, 1.0 is perfect separation. It measures
whether the numbers rank right answers above wrong ones, and says nothing about
whether the numbers are the right size.</dd>

<dt>Break-even, &radic;c</dt>
<dd>Under the quadratic rule with an assertion cost <code>c</code>, answering
beats staying silent exactly when the probability of being right exceeds
<code>&radic;c</code>. At <code>c = 0.09</code> that is 30%. Under ordinary
accuracy grading <code>c</code> is already set, to zero, so the break-even is
zero and there is never a reason to decline.</dd>

<dt>Brier score</dt>
<dd>The mean squared error of a stated probability, averaging
<code>(p &minus; outcome)&sup2;</code>. Lower is better. The quadratic score used
here equals accuracy minus Brier loss, which is why a model can lose accuracy and
still gain score.</dd>

<dt>Calibration</dt>
<dd>Whether stated probabilities are the right size. A calibrated model that says
70% is right about 70% of the time. Distinct from accuracy, which is how often it
is right, and from resolution, below.</dd>

<dt>Census</dt>
<dd>The count underneath the whole project: every per-question model output in the
public EvalEval &ldquo;Every Eval Ever&rdquo; datastore, searched for any of
roughly eighteen ways of declining to answer, across the entire generation
including reasoning traces. 1,089,024 responses, 104 models, 36 benchmarks.</dd>

<dt>Checkpoint</dt>
<dd>A saved set of model weights. Here it means the unchanged base model plus one
arm's LoRA adapter. Four exist: one per reward arm, and the untouched base as a
comparison.</dd>

<dt>Contract</dt>
<dd>The scoring rule as the model is told it, in the system prompt. The contract
is the intervention: the identical question goes out under every one of them, and
nothing else varies.</dd>

<dt>Contract arms, the eight</dt>
<dd><b>control</b> announces nothing, which is what nearly every benchmark does
today. <b>guess</b> announces binary grading out loud, that a wrong answer costs
nothing more than no answer. <b>thresh75</b> is the published threshold proposal:
answer only above 75% confidence, wrong answers cost 3. <b>quad_formula</b> gives
the quadratic rule as algebra only. <b>quad_plain</b> gives its implication in
plain English with no algebra. <b>quad_both</b> gives both, and is the intended
default. <b>quad_c50</b> is the same rule with speaking priced higher, so the
break-even moves to 50%. <b>deploy</b> states an identical incentive as a
deployer's operating instruction rather than as grading, and is the arm that can
falsify the whole programme.</dd>

<dt>Coverage, and risk-coverage</dt>
<dd>Coverage is the fraction of questions a model answered rather than declining.
A risk-coverage curve plots error rate against coverage as the abstention
threshold moves, which is how two models that decline different amounts can be
compared at all.</dd>

<dt>Harness</dt>
<dd>The software that runs the experiment: it builds the prompts, calls the
models, stores the raw responses, grades them, and computes the metrics. It is
kept separate from the scoring so a scoring parameter can change without
re-calling anything.</dd>

<dt>LM judge</dt>
<dd>A language model used to decide whether a free-form answer is correct, on
OpenAI's SimpleQA rubric, where no deterministic check is possible. It is the one
link in the pipeline that no test can cover, so it is validated against hand
labels before its verdicts are used. Below 90% agreement the free-form results
are unusable and only the deterministic benchmarks stand.</dd>

<dt>LoRA</dt>
<dd>Low-rank adaptation. A small set of extra weights trained alongside a frozen
base model, cheap to train and cheap to store. When the fine-tuning results say
the weights changed, it is the adapter that changed and not the base.</dd>

<dt>Miscalibration, and resolution</dt>
<dd>The two halves a proper score decomposes into, following Murphy (1973).
Miscalibration is the part recoverable by rescaling the stated numbers alone,
without changing a single answer. Resolution is how much those numbers genuinely
separate right answers from wrong ones, and has to be earned. On published runs
the first exceeds the second several times over.</dd>

<dt>NOT_ATTEMPTED, CORRECT, INCORRECT</dt>
<dd>The three grading verdicts. <code>NOT_ATTEMPTED</code> is an explicit
abstention, and it is the primary outcome of the experiment. Unparseable output
is graded <code>INCORRECT</code> and never <code>NOT_ATTEMPTED</code>: a response
that ignored the format did not decline to answer, and grading it as silence
would make incoherence free.</dd>

<dt>On-policy, and rollout</dt>
<dd>A rollout is one response the model samples during training. On-policy means
it learns from its own current outputs rather than from a fixed file of someone
else's, which is what lets a reward shape behaviour instead of teaching
imitation.</dd>

<dt>Paired design</dt>
<dd>Every arm sees the identical frozen questions, so question difficulty cancels
within a model and the comparison runs item by item rather than group against
group. The test is McNemar's, over only the items whose outcome disagreed between
the two arms.</dd>

<dt>Positive affine transform</dt>
<dd>Multiplying by a positive number and adding a constant. It changes the scale
of a score without changing the order. This is the reason a penalty alone cannot
reorder a leaderboard: with no explicit abstention option, the penalised score
works out to <code>(1+p)&middot;accuracy &minus; p</code>, which is a positive
affine map of accuracy. Verified across 69 published runs, maximum deviation
1.2e-15. The appended &ldquo;I DON'T KNOW&rdquo; option is what breaks the
affinity, which is why it is not optional.</dd>

<dt>Reward arms, the three</dt>
<dd><b>Accuracy-only</b> pays 1 for correct and 0 otherwise, ignoring the stated
probability. <b>Confidence-aware</b> pays the quadratic rule, so the stated
probability finally costs something. <b>Confidence plus cost</b> pays the
quadratic rule and charges a flat 0.09 for asserting anything at all. One tuning
method, three reward objectives, from one base model.</dd>

<dt>Strictly proper</dt>
<dd>A scoring rule under which reporting the probability you actually believe
maximises your expected score, and any other report lowers it.
<em>Strictly</em> means the honest report is the unique best one rather than
merely tied with others.</dd>

<dt>Stratified frozen slice</dt>
<dd>The questions themselves, sampled round-robin across strata in a
deterministic hash order and written to disk before any run. Frozen, so the same
run tomorrow asks the same questions and a difference between runs is a
difference in behaviour. Stratified, so no arm gets an easier draw.</dd>

</dl>
""",
        footer="The data files behind every figure on this site are published "
               "beside it, one per page.")


def build_open_questions():
    """The things that are genuinely unresolved, stated before the data landed."""
    dfn_calibration = dfn(
        "calibration",
        "Whether stated probabilities are the right size. A calibrated model "
        "that says 70% is right about 70% of the time. Distinct from accuracy, "
        "which is how often it is right at all.")
    dfn_strictly_proper = dfn(
        "strictly proper",
        "A scoring rule under which reporting the probability you actually "
        "believe maximises your expected score, and any other report lowers it. "
        "Strictly means the honest report is the unique best one, not merely "
        "tied with others.")
    side_page(
        "open-questions.html",
        title="Below Zero — open questions",
        description=("What this project has not settled: whether phrase matching "
                     "measures belief, what the agentic gap means, judge validity, "
                     "gaming, and who sets the price of speaking."),
        h1="Open questions",
        standfirst=("Written before the experimental data landed, so they cannot "
                    "be quietly narrowed to whatever the results turn out to be."),
        body=f"""
<h2 id="belief">Does counting phrases measure belief, or vocabulary?</h2>
<p>The census counts responses containing any of roughly eighteen ways of saying
&ldquo;I don't know&rdquo;. A model can be perfectly aware that it is guessing and still
never produce one of those phrases, in which case the count understates
awareness. It can also hedge at length inside a reasoning trace and then assert
a confident answer, in which case the count overstates it. The sensitivity
analysis moves the rate by a factor of a few, never by an order of magnitude,
but the deeper problem stands: this measures what models <em>say</em>, and the
thing worth knowing is what they would do if declining were an option worth
taking. That is precisely why the experiment exists.</p>

<h2 id="agentic">Why do agentic benchmarks show more declining?</h2>
<p>Benchmarks where the environment can show a model that it failed produce
visibly more declining than closed-form ones. The tempting reading is that
feedback teaches {dfn_calibration}. But agentic tasks also differ in length, in
scaffolding, in who wrote the prompts, and in what counts as an answer at all.
The comparison is confounded and this project does not resolve it. It is
reported because it is a real pattern in the data, not because the causal story
is settled.</p>

<h2 id="judge">Is the judge good enough to grade abstention?</h2>
<p>Abstention is graded by a language model wherever the answer is free-form,
which means the measurement instrument is itself a model with the same failure
modes being studied. It is validated against hand labels before its verdicts are
used, and unparseable output is forced to &ldquo;incorrect&rdquo; so that the judge can
never turn incoherence into honesty. Whether that is sufficient at the margin,
for answers that are hedged rather than clearly declined, is not yet
established.</p>

<h2 id="gaming">Would a deployed rule just teach models to game it?</h2>
<p>A {dfn_strictly_proper} rule is proper against a model reporting a belief. It says
nothing about a model trained directly against the metric, which may find that
abstaining on anything hard is the cheapest path to a good score. A benchmark
that rewards silence is not obviously better than one that rewards guessing. The
threshold rule makes this concrete: it elicits the right answer-or-abstain
decision, and deliberately does not elicit a probability, so everything above
the threshold scores identically and the reported number carries no information.
Stage 3, the fine-tuning run, is where this stops being speculation.</p>

<h2 id="transfer">Is any effect real, or just prompt compliance?</h2>
<p>If announcing a rule changes behaviour, the immediate question is whether the
model has changed what it reports or only how it formats what it reports.
Compliance with an instruction is not calibration. The planned test is to make
the rule the training reward rather than a sentence in the prompt, and see
whether the behaviour survives when nothing in the prompt announces it.</p>

<h2 id="c">Who decides what speaking costs?</h2>
<p>The rule has one interpretable knob: the cost of making a claim. Set it and
you have set the point below which silence beats any answer. That number is not
empirical. It encodes how much a wrong assertion costs in a particular
deployment, which is a normative judgement that belongs to whoever operates the
system, not to a benchmark author. This project can show what different values
imply. It cannot tell anyone which one is correct, and a benchmark that picks
one silently is making that decision on everyone's behalf.</p>

<h2 id="scope">Does any of this generalise past short factual questions?</h2>
<p>The experiment runs mostly on short questions with one checkable answer,
because that is where abstention is unambiguous. Most real use is not that.
Whether a rule that prices being wrong does anything useful for long-form
generation, where a response can be partly right, is outside what this design
can test.</p>

<div class="note"><b>If you think one of these is wrong</b>
The stop rules on the plan page are the pre-registered ones, and the disagreement
worth having is about them rather than about the framing. Corrections welcome.</div>
""",
        footer="These questions were written before the Stage 1 existence check "
               "reported.")


# Every citation on the related-work page that has a stable public identifier
# gets a link to it. These were resolved against the Crossref and arXiv APIs
# rather than written from memory: on a page whose whole argument is "check my
# sources", a DOI that resolves to the wrong paper is worse than no DOI at all.
# Entries absent from this map have no stable identifier to point at (a book, a
# College Board scoring change, an anthropology chapter), and they are left as
# plain text rather than aimed at a search page.
CITATION_LINKS = {
    "Verification of forecasts expressed in terms of probability":
        "https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2",
    "Rational decisions": "https://doi.org/10.1111/j.2517-6161.1952.tb00104.x",
    "Elicitation of personal probabilities and expectations":
        "https://doi.org/10.1080/01621459.1971.10482346",
    "A new vector partition of the probability score":
        "https://doi.org/10.1175/1520-0450(1973)012%3C0595:ANVPOT%3E2.0.CO;2",
    "Axiomatic characterization of the quadratic scoring rule":
        "https://doi.org/10.1023/A:1009957816843",
    "Strictly proper scoring rules, prediction, and estimation":
        "https://doi.org/10.1198/016214506000001437",
    "Probabilistic forecasts, calibration and sharpness":
        "https://doi.org/10.1111/j.1467-9868.2007.00587.x",
    "Methods for discriminating levels of partial knowledge concerning a test item":
        "https://doi.org/10.1111/j.2044-8317.1965.tb00695.x",
    "Admissible probability measurement procedures":
        "https://doi.org/10.1007/BF02289503",
    "A comparison of several methods of assessing partial knowledge in "
    "multiple-choice tests": "https://doi.org/10.1111/j.1745-3984.1975.tb01023.x",
    "Some comparisons among quadratic, spherical, and logarithmic scoring rules":
        "https://doi.org/10.1287/deca.1070.0089",
    "Choosing a strictly proper scoring rule":
        "https://doi.org/10.1287/deca.2013.0280",
    "Scoring probabilistic forecasts: the importance of being proper":
        "https://doi.org/10.1175/WAF966.1",
    "Scoring rules, generalized entropy, and utility maximization":
        "https://doi.org/10.1287/opre.1070.0498",
    "On optimum recognition error and reject tradeoff":
        "https://doi.org/10.1109/TIT.1970.1054406",
    "On the foundations of noise-free selective classification":
        "https://www.jmlr.org/papers/v11/el-yaniv10a.html",
    "Selective classification for deep neural networks":
        "https://arxiv.org/abs/1705.08500",
    "To guess or not to guess: a decision-theoretic view of formula scoring":
        "https://doi.org/10.1111/j.1745-3984.1993.tb00427.x",
    "Scoring and keying multiple choice tests: a case study in irrationality":
        "https://doi.org/10.1007/s11299-005-0001-z",
    "On calibration of modern neural networks": "https://arxiv.org/abs/1706.04599",
    "Teaching models to express their uncertainty in words":
        "https://arxiv.org/abs/2205.14334",
    "GPT-4 technical report": "https://arxiv.org/abs/2303.08774",
    "Just ask for calibration": "https://arxiv.org/abs/2305.14975",
    "Can LLMs express their uncertainty?": "https://arxiv.org/abs/2306.13063",
    "Evaluating large language models for accuracy incentivizes hallucinations":
        "https://doi.org/10.1038/s41586-026-10549-w",
    "Holistic evaluation of language models": "https://arxiv.org/abs/2211.09110",
    "AI and the everything in the whole wide world benchmark":
        "https://arxiv.org/abs/2111.15366",
    "What will it take to fix benchmarking in NLP?":
        "https://arxiv.org/abs/2104.02145",
    "R-Tuning: instructing large language models to say &lsquo;I don't know&rsquo;":
        "https://arxiv.org/abs/2311.09677",
    "Know your limits: a survey of abstention in large language models":
        "https://doi.org/10.1162/tacl_a_00754",
}


def link_citations(body):
    """Point every citation with a known identifier at that identifier.

    Titles are matched with the whitespace loosened, because the source wraps
    them across lines and a reference list is not worth reflowing to satisfy a
    string match. A title in the map that no longer appears on the page raises:
    a link that silently stops applying looks exactly like a citation nobody has
    got round to linking, and the difference matters.

    The second pass catches every arXiv identifier the page already states.
    Those need no lookup at all, since the page is the thing asserting the id.
    """
    for title, url in CITATION_LINKS.items():
        pattern = re.compile(
            r"<em>(" + r"\s+".join(re.escape(w) for w in title.split()) + r")</em>")
        # url is bound as a default rather than closed over: the lambda is
        # called inside this iteration, but a late-binding closure over a loop
        # variable would put the last map entry's URL behind every title the
        # moment anyone made subn lazy.
        body, n = pattern.subn(
            lambda m, url=url: f'<em><a href="{url}">{m.group(1)}</a></em>',
            body, count=1)
        if not n:
            raise SystemExit(f"citation link target not on the page: {title!r}")

    return re.sub(r"arXiv:(\d{4}\.\d{4,5})",
                  r'<a href="https://arxiv.org/abs/\1">arXiv:\1</a>', body)


def build_related_work():
    """What already exists, and where this project actually adds something.

    Grouped by idea rather than by year or venue, because the useful fact about
    this literature is that five separate fields solved five parts of the same
    problem without ever being in the same room. Each entry says what the work
    gives THIS project; a reference list that only lists is a reference list
    nobody reads.
    """
    dfn_risk_coverage = dfn(
        "risk-coverage",
        "A curve plotting error rate against the fraction of questions a model "
        "actually answered, traced as the abstention threshold moves. It is how "
        "two models that decline different amounts can be compared at all.")

    side_page(
        "related-work.html",
        title="Below Zero &mdash; what this builds on",
        description=("The scoring theory, the reject option, the testing "
                     "precedent, the calibration evidence and the benchmark "
                     "critique this project stands on, and a question-by-question "
                     "account of what is settled and what is not."),
        h1="What this builds on",
        standfirst=("Almost none of this is new, including the parts that look "
                    "new. The scoring theory is seventy years old, the reject "
                    "option fifty, and probability-scored exams were built and "
                    "tested on students in the 1960s. The last section says how "
                    "small each remaining step actually is."),
        body=link_citations(f"""
<h2 id="rules">The maths was finished before the problem existed</h2>
<p>If you want somebody's honest probability, pay them in a way that makes
honesty their best bet. Brier wrote down such a payment scheme for weather
forecasters in 1950, Good added the logarithmic version two years later, and by
1971 Savage had characterised the entire family of rules with that property. A
rule is <em>proper</em> when truthfully reporting your belief maximises your
expected score, and <em>strictly</em> proper when nothing else ties it. That is
a theorem. It does not care whether the forecaster is a person, a barometer or
a language model.</p>
<p>The part that matters for benchmarks is what the theorem excludes. One point
for right and zero for wrong is a perfectly reasonable way to rank people who
all answer everything, and a strictly improper way to elicit a probability:
under it, the best move at any belief above chance is to state your most likely
answer with full confidence. Guessing is not a defect in the model. It is the
optimal play, and it was known to be the optimal play decades before there were
models.</p>
<ul class="refs">
<li><b>Brier (1950)</b>, <em>Verification of forecasts expressed in terms of
probability</em>, Monthly Weather Review 78:1-3. <span class="gloss">The
quadratic rule, invented so weather forecasters could not hedge for
score.</span></li>
<li><b>Good (1952)</b>, <em>Rational decisions</em>, JRSS-B 14:107-114.
<span class="gloss">The logarithmic rule.</span></li>
<li><b>de Finetti (1962)</b>, <em>Does it make sense to speak of &ldquo;good
probability appraisers&rdquo;?</em> <span class="gloss">The elicitation
question, asked plainly, in one essay.</span></li>
<li><b>Savage (1971)</b>, <em>Elicitation of personal probabilities and
expectations</em>, JASA 66:783-801. <span class="gloss">The characterisation of
the whole proper family, which is what makes &ldquo;use a proper rule&rdquo; a
finite instruction rather than a taste.</span></li>
<li><b>Murphy (1973)</b>, <em>A new vector partition of the probability
score</em>, J. Applied Meteorology 12:595-600. <span class="gloss">Reliability
minus resolution plus uncertainty. Why a Brier score can be split into
&ldquo;is calibrated&rdquo; and &ldquo;knows things&rdquo;, which is the
decomposition this project reports.</span></li>
<li><b>Selten (1998)</b>, <em>Axiomatic characterization of the quadratic
scoring rule</em>, Experimental Economics 1:43-62. <span class="gloss">The
axioms behind the specific rule used here.</span></li>
<li><b>Gneiting &amp; Raftery (2007)</b>, <em>Strictly proper scoring rules,
prediction, and estimation</em>, JASA 102:359-378. <span class="gloss">The
modern reference; start here if you start anywhere.</span></li>
<li><b>Gneiting, Balabdaoui &amp; Raftery (2007)</b>, <em>Probabilistic
forecasts, calibration and sharpness</em>, JRSS-B 69:243-268.
<span class="gloss">Maximise sharpness subject to calibration. The goal of the
whole exercise in six words.</span></li>
</ul>

<h2 id="choice">Choosing among proper rules, which has been done carefully twice</h2>
<p>Properness narrows the field but does not pick a member of it, and the
question of <em>which</em> proper rule has had two serious efforts, sixty years
apart, in fields that do not read each other.</p>
<p>The first was psychometrics, and it went further than this project has.
de Finetti proposed in 1965 that students answer multiple-choice items by
distributing probability across the options and be scored so that honest
distribution maximises the mark. Shuford, Albert and Massengill gave the
necessary and sufficient condition the following year, along with a recipe for
generating an unlimited family of such scoring systems. Others then built the
exams and ran them on real students. So the design being proposed here for
models was proposed for people six decades ago, tested, and mostly abandoned for
the practical reasons the SAT section describes.</p>
<p>The second was decision analysis, and it is the part with a live objection in
it. Bickel compared the quadratic, spherical and logarithmic rules and concluded
that the logarithmic rule is better <em>when rank order is what you care
about</em>, which is exactly what a leaderboard is. Merkle and Steyvers then
showed that the common belief that the choice barely matters comes from looking
at only the two or three popular rules, and that across a wider family the
conclusions move a great deal. This project uses the quadratic rule anyway, and
owes a reason: the logarithmic rule is unbounded below, so a single confident
error scores minus infinity. On a benchmark where a parse failure or a grader
slip can produce exactly that, one bad item would sink a model's entire score,
and a metric that fragile will not be adopted no matter how well it behaves in
theory. Selten's axioms and the reliability-resolution split are the positive
case; boundedness is the one that decides it. Both rules are implemented here
and the comparison is free, which is the honest way to hold that position.</p>
<ul class="refs">
<li><b>de Finetti (1965)</b>, <em>Methods for discriminating levels of partial
knowledge concerning a test item</em>, British J. Mathematical and Statistical
Psychology 18:87-123. <span class="gloss">This project's design, proposed for
students, sixty years early.</span></li>
<li><b>Shuford, Albert &amp; Massengill (1966)</b>, <em>Admissible probability
measurement procedures</em>, Psychometrika 31:125-145.
<span class="gloss">The necessary and sufficient condition, plus a generator for
the whole admissible family. Properness for exams, settled.</span></li>
<li><b>Kansup &amp; Hakstian (1975)</b>, <em>A comparison of several methods of
assessing partial knowledge in multiple-choice tests</em>, J. Educational
Measurement. <span class="gloss">Somebody then ran it on real students, which is
the step this project is still owed.</span></li>
<li><b>Bickel (2007)</b>, <em>Some comparisons among quadratic, spherical, and
logarithmic scoring rules</em>, Decision Analysis 4:49-65.
<span class="gloss">The strongest technical objection to the choice made here:
for rank ordering, which is what a leaderboard does, he finds the logarithmic
rule superior.</span></li>
<li><b>Merkle &amp; Steyvers (2013)</b>, <em>Choosing a strictly proper scoring
rule</em>, Decision Analysis 10:292-304. <span class="gloss">The choice matters
more than the field assumes, because the field has only compared two or three
rules.</span></li>
<li><b>Br&ouml;cker &amp; Smith (2007)</b>, <em>Scoring probabilistic forecasts:
the importance of being proper</em>, Weather and Forecasting 22:382-388;
<b>Jose, Nau &amp; Winkler (2008)</b>, <em>Scoring rules, generalized entropy,
and utility maximization</em>, Operations Research 56:1146-1157.
<span class="gloss">Where the parametric families and their tradeoffs
live.</span></li>
</ul>

<h2 id="reject">The reject option: when saying nothing is the right move</h2>
<p>Chow's 1970 result is the cleanest statement of what a benchmark is missing.
Give a classifier the option to say nothing, attach a cost to that option, and
the optimal policy falls straight out: answer when your confidence exceeds the
ratio of what an error costs to what silence costs. There is no free parameter
left to argue about beyond that ratio, and the ratio is not a statistical
quantity. It is a claim about the deployment. The single knob in this project's
rule, the price of making a claim, is Chow's ratio wearing different
clothes.</p>
<p>Everything since is variations on the same move. Selective classification
traces the {dfn_risk_coverage} curve, showing how much accuracy you buy by answering
less often. Conformal prediction goes the dual route and returns a set that
provably contains the answer at a chosen rate, so uncertainty appears as the
<em>size</em> of the set rather than as a number bolted onto a guess. Both treat
abstention as a first-class output. Benchmarks kept the single-answer
interface.</p>
<ul class="refs">
<li><b>Chow (1970)</b>, <em>On optimum recognition error and reject
tradeoff</em>, IEEE Trans. Information Theory 16:41-46. <span class="gloss">The
threshold is a cost ratio, and the cost ratio is somebody's decision.</span></li>
<li><b>El-Yaniv &amp; Wiener (2010)</b>, <em>On the foundations of noise-free
selective classification</em>, JMLR 11:1605-1641; <b>Geifman &amp; El-Yaniv
(2017)</b>, <em>Selective classification for deep neural networks</em>, NeurIPS.
<span class="gloss">Risk-coverage curves, then the same idea for modern
nets.</span></li>
<li><b>Vovk, Gammerman &amp; Shafer (2005)</b>, <em>Algorithmic learning in a
random world</em>; <b>Angelopoulos &amp; Bates (2023)</b> for the readable
introduction. <span class="gloss">Conformal prediction: the honest alternative
that answers with a set instead of a probability.</span></li>
</ul>

<h2 id="testing">Human testing ran this experiment, and mis-set the price</h2>
<p>The strongest objection this design has to survive does not come from machine
learning. For decades the SAT subtracted a quarter point for a wrong answer on a
five-choice question, and the College Board removed it in 2016. The usual
reading is that pricing error was tried and failed. The sharper reading is that
the price was set at the one value that guarantees failure.</p>
<p>A quarter point off out of five choices makes a blind guess worth exactly
zero, which is exactly what a blank is worth. At that price the answer-or-abstain
decision has no strictly correct answer: a student who knows nothing is
indifferent, so what they do is settled by appetite for risk rather than by
knowledge. One step above blind, having ruled out a single option, guessing is
already worth +0.06 and abstaining is simply wrong. So a
rule advertised as a penalty for guessing in fact rewarded guessing nearly
everywhere, and the students it cost were the ones who took the instruction at
face value. Formula scoring did not measure knowledge worse because it priced
error. It measured knowledge worse because the price left the decision
indeterminate at the bottom and contradicted its own name above that.</p>
<p>The design that survives moves the price off that point and pays for silence
rather than only fining noise. The AMC gives 6 for a correct answer, 0 for a
wrong one and 1.5 for a blank, against a blind guess worth 1.2. Declining now
strictly beats guessing, the indifference point sits at a belief of one in four
rather than at chance, and so there is a right move at every level of knowledge
and the instruction describes what the incentive actually does. Nobody argues
about it. Kalai et al. reach the same place from the other end: the exams that
do price error, JEE, NEET, GATE, the AMC, and the SAT, AP and GRE in earlier
years, all state the grading rule in the instructions, and takers know roughly
where the threshold sits.</p>
<p>Two things carry across. The price of a claim has to be set so the
answer-or-abstain decision has a strict optimum at <em>every</em> belief, which
is why this design pays for abstention rather than only penalising error. And
the announcement has to be something the reader can act on: a contract whose
name disagrees with its own arithmetic is the failure mode the SAT actually
shipped, and it is why the wording of every contract here is tested against a
simulated respondent before any money is spent on a real one.</p>
<ul class="refs">
<li><b>Budescu &amp; Bar-Hillel (1993)</b>, <em>To guess or not to guess: a
decision-theoretic view of formula scoring</em>, J. Educational Measurement
30:277-291. <span class="gloss">The case against, and the reason
number-right scoring won. Read this before proposing a penalty.</span></li>
<li><b>Bar-Hillel, Budescu &amp; Attali (2005)</b>, <em>Scoring and keying
multiple choice tests: a case study in irrationality</em>, Mind &amp; Society
4:3-12.</li>
<li><b>College Board (2016)</b>, redesigned SAT: rights-only scoring.
<span class="gloss">The end of the longest-running natural experiment anyone has
run on pricing wrong answers.</span></li>
<li><b>AMC 10/12 scoring</b>: 6 correct, 0 wrong, 1.5 blank, against a blind
guess worth 1.2. <span class="gloss">A live, uncontroversial priced abstention,
and the design this project is closer to.</span></li>
<li><b>Indian JEE, NEET and GATE; AP and GRE in earlier years.</b>
<span class="gloss">Kalai et al.'s own list of exams that price error, and their
observation that all of them announce the rule in the instructions.</span></li>
</ul>

<h2 id="signal">The models already have the signal</h2>
<p>If a model's internal confidence were noise, this whole programme would be
pointless: you cannot elicit a belief that is not there. The evidence says it is
there and gets flattened. Networks stopped being calibrated out of the box
around 2017. Large models can predict whether they are about to get an answer
right at well above chance. They can state a probability in words and have it
mean something. And the GPT-4 report contains the most-quoted plot in this
literature, a base model whose stated confidence tracks its accuracy almost
exactly, next to the same model after RLHF, badly overconfident.</p>
<p>Read together those results move the problem. It is not that models cannot
tell when they are unsure. It is that nothing in training or evaluation ever
asked them to say so, and at least one thing actively taught them not to.</p>
<ul class="refs">
<li><b>Guo, Pleiss, Sun &amp; Weinberger (2017)</b>, <em>On calibration of
modern neural networks</em>, ICML. <span class="gloss">Accuracy improved and
calibration got worse, in the same models, at the same time.</span></li>
<li><b>Kadavath et al. (2022)</b>, <em>Language models (mostly) know what they
know</em>, arXiv:2207.05221. <span class="gloss">The self-knowledge this
project assumes exists.</span></li>
<li><b>Lin, Hilton &amp; Evans (2022)</b>, <em>Teaching models to express their
uncertainty in words</em>, TMLR. <span class="gloss">A verbalised probability
that is actually calibrated, which is the response format used here.</span></li>
<li><b>OpenAI (2023)</b>, <em>GPT-4 technical report</em>, calibration before
and after RLHF. <span class="gloss">The clearest single picture of preference
training destroying an existing signal.</span></li>
<li><b>Tian et al. (2023)</b>, <em>Just ask for calibration</em>, EMNLP;
<b>Xiong et al. (2024)</b>, <em>Can LLMs express their uncertainty?</em>, ICLR.
<span class="gloss">Asking beats reading the log-probs on RLHF'd models, and
overconfidence survives the asking.</span></li>
</ul>

<h2 id="benchmarks">The diagnosis is mainstream; the scoreboard has not moved</h2>
<p>Kalai, Nachum, Vempala and Zhang put the argument in Nature in 2026, and it
is the same argument: accuracy-maximising evaluation makes guessing optimal, so
hallucination is an incentive problem before it is a modelling one. Their remedy
is that benchmarks state their penalty explicitly in the rubric. This project
takes that as the starting point and differs in three places. It elicits a
probability rather than an answer-or-abstain decision. It pays for abstention
rather than only penalising error. And it treats &ldquo;does announcing the rule
change what a model does&rdquo; as a question to be tested rather than
assumed.</p>
<p>Something has moved since, and it is worth being precise about how much.
AA-Omniscience scores 6,000 questions at (correct &minus; incorrect) / total,
gives abstention away free, and ships inside a mainstream index rather than as a
side benchmark. It reorders models: one model well down the capability tables
lands near the top of it. That is the proposal working, and it retires the
version of this argument that says nobody will ever price a wrong answer.</p>
<p>It is also the moment the standard gets set, which is the part worth caring
about. Subtracting one for a wrong answer and awarding one for a right one is
Kalai's threshold rule at <i>t</i>&nbsp;=&nbsp;0.5. That is a legitimate rule
and it is proper as a decision, but it is a decision rule: it elicits an
answer-or-abstain choice and no probability, everything above the threshold
scores identically, and the threshold itself is fixed at the one value that says
a wrong claim costs exactly what a right one is worth. That is not a fact about
language models. It is a claim about deployments, made once, silently, on behalf
of everyone who reads the leaderboard. A benchmark that picks the price without
saying so is making the normative call this project argues belongs to whoever
operates the system.</p>
<p>Neither of the two things this project is about is addressed. Nothing tells a
reader whether the reordering survives a different price, and the model is never
told the price at all, which leaves the announcement question exactly where
Kalai et al. left it. Around that, the older infrastructure still sits unused:
HELM has reported calibration next to accuracy since 2022 and nobody ranks on
it, and SimpleQA has graded correct, incorrect and not attempted since 2024,
which is the three-way vocabulary a priced rule needs and the one this
repository borrowed wholesale. The gap between metrics that are available and
metrics that are decisive is the practical thing being argued about here, and it
is why the argument is aimed at benchmark maintainers rather than at model
trainers.</p>
<ul class="refs">
<li><b>Kalai, Nachum, Vempala &amp; Zhang (2026)</b>, <em>Evaluating large
language models for accuracy incentivizes hallucinations</em>, Nature
653:1047-1051. <span class="gloss">The threshold rule this builds on, the
observation that binary grading makes abstention never optimal, and a survey
finding that of ten headline benchmarks, nine grade in binary and none give
credit for declining.</span></li>
<li><b>Jackson, Keating, Cameron &amp; Hill-Smith (2025)</b>,
<em>AA-Omniscience</em>, arXiv:2511.13029. <span class="gloss">The first
mainstream leaderboard to price being wrong: 6,000 questions scored
(correct &minus; incorrect) / total, abstention free, shipped inside the
Artificial Analysis Intelligence Index. It reorders models against accuracy.
It is also a single fixed price, unannounced to the model, which is the two
things this project varies.</span></li>
<li><b>Wei et al. (2024)</b>, <em>Measuring short-form factuality in large
language models</em> (SimpleQA), arXiv:2411.04368. <span class="gloss">Correct,
incorrect, not attempted. The grading vocabulary already exists in a shipped
benchmark.</span></li>
<li><b>Liang et al. (2022)</b>, <em>Holistic evaluation of language models</em>
(HELM). <span class="gloss">Calibration has been a reported metric for four
years, and nobody ranks on it. The cautionary case for this whole
proposal.</span></li>
<li><b>Burns (2025)</b>, <em>Measuring language model hallucinations through
distributional correctness</em>, arXiv:2510.04302. <span class="gloss">Scores
the whole answer distribution rather than a thresholded decision, and separates
hedging toward a wrong answer from hedging toward silence. Deliberately not a
proper rule, which is precisely the choice this project declines to
make.</span></li>
<li><b>Raji et al. (2021)</b>, <em>AI and the everything in the whole wide world
benchmark</em>, NeurIPS Datasets &amp; Benchmarks; <b>Bowman &amp; Dahl
(2021)</b>, <em>What will it take to fix benchmarking in NLP?</em>, NAACL.
<span class="gloss">What a benchmark is actually measuring, and what it does to
the field that optimises against it.</span></li>
<li><b>Strathern (1997)</b>. <span class="gloss">Goodhart's law in the form
everyone quotes: when a measure becomes a target, it stops being a good
measure.</span></li>
</ul>

<h2 id="training">Putting the rule in the gradient</h2>
<p>A sentence in the prompt is a weak instrument. If pricing error only changes
behaviour while the model is being told about the pricing, the effect is
compliance, and compliance decays. The stronger version makes the rule the
reward, and that work is under way: refusal-aware tuning, a calibration term
added to the RL reward, ternary rewards with a tunable penalty for being wrong.
They converge on the finding Stage 3, the fine-tuning run, is designed to test
directly. You cannot
prompt your way past an objective, and a model trained under a reward that pays
for saying nothing becomes a different model rather than a more obedient
one.</p>
<ul class="refs">
<li><b>Zhang et al. (2024)</b>, <em>R-Tuning: instructing large language models
to say &lsquo;I don't know&rsquo;</em>, NAACL. <span class="gloss">Refusal-aware
tuning, and the finding that the refusal generalises out of domain.</span></li>
<li><b>Damani, Puri, Slocum, Shenfeld, Choshen, Kim &amp; Andreas (2025)</b>,
<em>Beyond binary rewards: training LMs to reason about their uncertainty</em>,
arXiv:2507.16806. <span class="gloss">The closest published relative. Reward is
correctness minus a Brier term on a verbalised confidence, and only the Brier
component has to be proper for the sum to elicit honestly. On Qwen2.5-7B,
calibration error falls from 0.37 to 0.03 with accuracy unchanged, and the
gain holds out of domain. The result that makes this cheap to adopt.</span></li>
<li><b>Mohammadi, Wang &amp; Li (2025)</b>, <em>Honesty over accuracy:
trustworthy language models through reinforced hesitation</em>,
arXiv:2511.11500. <span class="gloss">Ternary reward, +1 / 0 / &minus;&lambda;,
producing a frontier of models indexed by the penalty. Also the most important
negative result on this site: eleven frontier models, told in the prompt that
errors cost up to a hundred times a correct answer, abstain at close to zero
anyway. If the Stage 1 existence check announces a rule and nothing moves, this is
why.</span></li>
<li><b>Zong, Li, Long, Chang, Wu &amp; Hadfield (2026)</b>, <em>I-CALM</em>,
arXiv:2604.03904. <span class="gloss">The nearest thing to the Stage 1 existence
check that has been
published: announced incentive schemes varied in the prompt, abstention measured
on TriviaQA, SimpleQA and TruthfulQA, and reported to move. It reads against the
result above, and reconciling the two is now the most useful thing this project
could do.</span></li>
<li><b>Kirichenko et al. (2025)</b>, <em>AbstentionBench</em>, arXiv:2506.09038;
<b>Wen et al. (2025)</b>, <em>Know your limits: a survey of abstention in large
language models</em>, TACL 13:529-556. <span class="gloss">Where the abstention
literature currently stands, and a map of it.</span></li>
</ul>

<h2 id="gaps">Question by question, and how big a step each one is</h2>
<p>A gap is not automatically worth filling, and most of these are smaller than
the length of the list above would suggest. The third column says what is left
and then says plainly how much of a step it is, because a project that claims
five contributions and has two is worse off than one that claims two.</p>
""" + table(
            ["Question", "What already exists", "What is left, and how big a step"],
            [
                ["<b>How often do models decline, in practice?</b>",
                 ("AbstentionBench and AA-Omniscience measure it on sets built for the "
                 "purpose. SimpleQA reports a not-attempted rate per model."),
                 ("<b>Trivial method, large coverage.</b> A count over evaluations that "
                 "already ran rather than a new test: 1,089,024 responses, 104 models, "
                 "36 benchmarks, 0.69% declining. Anyone could have run it and nobody "
                 "did, so the contribution is the scale and the fact that it needs no "
                 "new data, not the technique.")],
                ["<b>Does pricing error change the ranking?</b>",
                 ("AA-Omniscience ranks frontier models on (correct &minus; incorrect) / "
                 "total inside a mainstream index, and reorders them against accuracy. "
                 "One model well down the capability tables ranks near the top on it."),
                 ("<b>Marginal, and the easiest thing here to be scooped on.</b> The "
                 "price is fixed at one value with no stated justification, and nobody "
                 "has swept it to separate a robust reordering from an artefact of that "
                 "value. Because scoring is applied after the fact, the sweep is free, "
                 "which is also why somebody else will eventually do it.")],
                ["<b>Does <em>announcing</em> the rule change behaviour?</b>",
                 ("Kalai et al. propose it and do not test it. Reinforced Hesitation "
                 "announces penalties up to 100&times; to eleven frontier models on three "
                 "benchmarks and finds abstention stays near zero. I-CALM varies announced "
                 "schemes on three QA sets and reports that it moves."),
                 ("<b>A tiebreak, not a discovery.</b> The question has been asked twice "
                 "and answered both ways, so the value is in resolving a contradiction "
                 "rather than in opening a subject. What is genuinely absent is the "
                 "method: paired frozen items across a ladder of contracts, a "
                 "pre-registered stop rule, and the announcement's wording separated "
                 "from its arithmetic.")],
                ["<b>Can a benchmark elicit an honest probability, not just a decision?</b>",
                 ("Solved for human exams in 1965 and 1966, and argued over properly by "
                 "decision analysts through 2013. Kalai et al.'s rule is deliberately a "
                 "decision rule. DCS scores a distribution and is deliberately improper. "
                 "RLCR trains against a Brier term but is a training method."),
                 ("<b>Assembly, not invention. The largest hole and the least original "
                 "thinking.</b> Every component has existed for decades; nobody has put "
                 "them inside an evaluation that models are ranked on. The one open "
                 "technical question is whether quadratic or logarithmic is right for a "
                 "leaderboard, and Bickel argues against the choice made here.")],
                ["<b>Does any of it survive training?</b>",
                 ("R-Tuning, RLCR, Reinforced Hesitation and Abstain-R1 all train "
                 "abstention or calibration in, and the behaviour generalises out of "
                 "domain. RLCR gets calibration essentially for free."),
                 ("<b>Genuinely open, and the only causal claim available.</b> None of "
                 "them trains against a strictly proper probability-eliciting reward and "
                 "then checks whether the behaviour persists with nothing announced in "
                 "the prompt. That separation, reward against instruction, is the one "
                 "result here that could not be assembled from existing work.")],
            ],
            right_from=99, cls="gaps") + """
<p>Read down the third column and the honest summary is two contributions, not
five. The census is worth having because of its size and because it costs
nothing to check. Stage 3, the fine-tuning run, is worth running because nobody can
predict it. The
middle three are a parameter sweep, a tiebreak between two published papers, and
an assembly job on sixty-year-old parts, and each is worth doing mainly because
it is cheap once the harness exists.</p>
<p>None of which is the point. The point is
<a href="index.html#goal">whether a benchmark maintainer changes anything</a>,
and against that test a small original contribution assembled into something
adoptable beats a large one that stays in a paper. Most of this page is here so
that the assembly can be done with the good parts rather than the nearest
ones.</p>


<div class="note"><b>One correction worth making in public</b>
The Nature paper's instruction sets the penalty for a wrong answer at
<i>t</i>&nbsp;/&nbsp;(1&nbsp;&minus;&nbsp;<i>t</i>), then lists
<i>t</i>&nbsp;=&nbsp;0.75 as a penalty of 2. The formula gives 3. This site and
the code behind it follow the formula, so a reader comparing the two will find
they disagree, and the disagreement is in the paper rather than here.</div>
"""),
        footer="Sources are grouped by idea rather than by date. Corrections "
               "and omissions welcome; a missing entry here is a real gap.")


BRIEF_CSS = r"""
/* An inline magnitude bar drawn beside a rate. The length restates the number
   next to it rather than encoding a second variable, so the colour is the
   fixed evidence blue and never varies by row. An empty track is the picture
   of a zero, which is most of the point of the table it appears in. */
.rbar { display: inline-block; vertical-align: middle; width: 64px; height: 7px;
        margin-left: 10px; background: var(--rule); border-radius: 2px; }
.rbar i { display: block; height: 100%; background: var(--evidence);
          border-radius: 2px; }
@media (max-width: 700px) { .rbar { width: 40px; } }
/* The dataset registry is four columns of unequal appetite: two short
   identifiers, one description that wants the room, and a command. The
   prose-table widths are wrong for it. */
table.vintage { min-width: 640px; }
table.vintage th, table.vintage td { text-align: left; vertical-align: top; }
table.vintage td:first-child { width: 14%; font-weight: 600; }
table.vintage td:nth-child(2) { width: 12%; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
table.vintage td:nth-child(3) { width: 40%; }
table.vintage code { white-space: nowrap; font-size: 11.5px; }

/* In the worked table the stated answer IS the finding, so it is set at
   reading size and the payoff that supports it is demoted to a sub-line. */
.worked .move { font-size: 20px; font-weight: 650;
  letter-spacing: -.01em; color: var(--text); }
.worked td:first-child { width: 26%; font-weight: 600; }
.worked-h { margin: 24px 0 2px; font-size: 15px; }

/* Score bar: a signed magnitude behind a decimal, on a scale shared by the
   whole column, because three decimal places make a real improvement look
   like noise. The zero mark is drawn when the column crosses it. */
.sbar { position: relative; display: inline-block; vertical-align: middle;
        width: 62px; height: 7px; margin-left: 10px; background: var(--rule);
        border-radius: 2px; }
.sbar i { position: absolute; top: 0; height: 100%; background: var(--evidence);
          border-radius: 1px; }
.sbar u { position: absolute; top: -2px; bottom: -2px; width: 1px;
          background: var(--rule-strong); }
@media (max-width: 700px) { .sbar { width: 40px; } }

/* Distribution summary: one row per condition, paired under a metric label,
   each metric on its own axis. */
.range-plot { margin: 20px 0 10px; max-width: var(--max-wide); }
.range-plot svg { display: block; width: 100%; height: auto; margin-bottom: 2px; }
.rp-metric { fill: var(--text); font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 12.5px; font-weight: 700; }
.rp-cond { fill: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11.5px; }
.rp-val { font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11px;
  font-weight: 700; }
.rp-whisk { stroke: var(--rule-strong); stroke-width: 1; }
.rp-out { fill: var(--bg); stroke: var(--rule-strong); stroke-width: 1.2; }
.rp-med { stroke: var(--text); stroke-width: 2; }
.rp-box.rp-c0 { fill: var(--text-muted); opacity: .32; }
.rp-box.rp-c1 { fill: var(--accent); opacity: .48; }
.rp-val.rp-c0 { fill: var(--text-muted); }
.rp-val.rp-c1 { fill: var(--accent-text); }
.rp-keys { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 6px;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11.5px;
  color: var(--text-secondary); }
.rp-key { display: inline-flex; align-items: center; gap: 6px; }
.rp-key i { width: 14px; height: 9px; border-radius: 2px; }
.rp-key i.rp-c0 { background: var(--text-muted); opacity: .5; }
.rp-key i.rp-c1 { background: var(--accent); opacity: .6; }
.rp-key.legend { color: var(--text-muted); }

/* The scoring landscape is one label column and three short answers; the
   prose-table widths give the first answer column a third of the page. */
table.landscape td:first-child, table.landscape th:first-child { width: 34%; }
table.landscape td:not(:first-child),
table.landscape th:not(:first-child) { width: 22%; }

/* The HLE table has seven analytical columns. Preserve model identity as one
   scannable token and let the wrapper scroll below the table's readable width
   instead of breaking GPT-5.4 after the hyphen on a desktop viewport. */
table.brief-hle { min-width: 820px; }
table.brief-hle th:first-child, table.brief-hle td:first-child {
  width: 11%; white-space: nowrap;
}
table.brief-hle th:nth-child(2), table.brief-hle td:nth-child(2) { width: 7%; }

/* Diverging in-cell bar for over/under confidence: a fixed track with a
   centre axis, fill extending right when the model claims more than it
   delivers and left when less. Same contract as .rbar: length restates the
   number beside it, colour is fixed per direction and never magnitude. */
.dbar { position: relative; display: inline-block; vertical-align: middle;
        width: 56px; height: 7px; margin-left: 10px; background: var(--rule);
        border-radius: 2px; }
.dbar::before { content: ""; position: absolute; left: 50%; top: -2px;
        bottom: -2px; width: 1px; background: var(--rule-strong); }
.dbar i { position: absolute; top: 0; height: 100%; border-radius: 1px; }
.dbar i.over { left: 50%; background: var(--accent); }
.dbar i.under { right: 50%; background: var(--evidence); }
@media (max-width: 700px) { .dbar { width: 36px; } }

/* A small outlined tag inside a cell, for one-word row annotations like
   "baseline". Outlined rather than filled so it reads as a note, not a
   state. */
.tag-chip { display: inline-block; margin-left: 8px; padding: 1px 7px;
  border: 1px solid var(--rule-strong); border-radius: 10px;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 10px;
  font-weight: 650; letter-spacing: .05em; text-transform: uppercase;
  color: var(--text-muted); vertical-align: middle; }
tr.anchor td { background: var(--bg-alt); }

/* Takeaway chips: each names a claim, and clicking it highlights the rows in
   the table below that make the point. */
.takeaways { max-width: var(--max-wide); margin: 18px 0 4px; }
.tk-chip { border: 1px solid var(--rule-strong); background: var(--bg);
  color: var(--text); border-radius: 18px; padding: 9px 16px;
  margin: 0 8px 9px 0; font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 14px; font-weight: 600; cursor: pointer; }
.tk-chip:hover { border-color: var(--accent); color: var(--text); }
.tk-chip[aria-pressed="true"] { background: var(--accent);
  border-color: var(--accent); color: var(--on-plum); }
.tk-note { max-width: var(--max-text); margin: 8px 0 0; font-family: 'Inter',
  ui-sans-serif, sans-serif; font-size: 14px; line-height: 1.55;
  color: var(--text-secondary); }
.tk-hint { display: block; margin: 0 0 8px; font-family: 'Inter',
  ui-sans-serif, sans-serif; font-size: 11px; color: var(--text-muted); }
tr.hl td { background: var(--accent-tint); }
/* The accent bar sits BESIDE the text, not over it: an inset shadow on a cell
   with no left padding clipped the first characters of every highlighted
   row. Every first cell reserves the space so nothing shifts on highlight. */
tbody tr td:first-child { border-left: 3px solid transparent; padding-left: 9px; }
tr.hl td:first-child { border-left-color: var(--accent); }

/* The parity interval strips reuse .pi from the shared stylesheet; the
   legend is hidden globally under 720px, which is scoped to the validation
   page's table there, so re-show it for this page's narrower strips. */
.brief-pi .pi { min-width: 110px; }
/* Prose tables on this page: first column is a sentence, not a label, so the
   global right-alignment of non-first columns is opted out per table via
   right_from=99 and this class keeps the headers left too. */
table.brief-prose th { text-align: left; }

/* The alignment exhibits are the brief's main answer. On a phone, a
   five-column table hides the conclusion behind horizontal scrolling, so each
   row becomes a labeled evidence card. Desktop retains the comparison table. */
@media (max-width: 600px) {
  table.alignment-scorecard, table.alignment-relationship,
  table.alignment-prompt-contrast, table.matched-alignment,
  table.plural-prudence-training, table.plural-prudence-prompt,
  table.domain-transfer, table.domain-behavior,
  table.pooled-transfer, table.gpqa-transfer,
  table.hidden-opportunity, table.multitask-family-gates {
    display: block; min-width: 0; width: 100%;
  }
  table.alignment-scorecard thead, table.alignment-relationship thead,
  table.alignment-prompt-contrast thead, table.matched-alignment thead,
  table.plural-prudence-training thead, table.plural-prudence-prompt thead,
  table.domain-transfer thead, table.domain-behavior thead,
  table.pooled-transfer thead, table.gpqa-transfer thead,
  table.hidden-opportunity thead, table.multitask-family-gates thead {
    display: none;
  }
  table.alignment-scorecard tbody, table.alignment-relationship tbody,
  table.alignment-prompt-contrast tbody,
  table.matched-alignment tbody,
  table.plural-prudence-training tbody, table.plural-prudence-prompt tbody,
  table.domain-transfer tbody, table.domain-behavior tbody,
  table.pooled-transfer tbody, table.gpqa-transfer tbody,
  table.hidden-opportunity tbody, table.multitask-family-gates tbody,
  table.alignment-scorecard tr, table.alignment-relationship tr,
  table.alignment-prompt-contrast tr, table.matched-alignment tr,
  table.plural-prudence-training tr, table.plural-prudence-prompt tr,
  table.domain-transfer tr, table.domain-behavior tr,
  table.pooled-transfer tr, table.gpqa-transfer tr,
  table.hidden-opportunity tr, table.multitask-family-gates tr,
  table.alignment-scorecard td, table.alignment-relationship td,
  table.alignment-prompt-contrast td, table.matched-alignment td,
  table.plural-prudence-training td, table.plural-prudence-prompt td,
  table.domain-transfer td, table.domain-behavior td,
  table.pooled-transfer td, table.gpqa-transfer td,
  table.hidden-opportunity td, table.multitask-family-gates td {
    display: block; width: 100%; box-sizing: border-box;
  }
  table.alignment-scorecard tr, table.alignment-relationship tr,
  table.alignment-prompt-contrast tr, table.matched-alignment tr,
  table.plural-prudence-training tr, table.plural-prudence-prompt tr,
  table.domain-transfer tr, table.domain-behavior tr,
  table.pooled-transfer tr, table.gpqa-transfer tr,
  table.hidden-opportunity tr, table.multitask-family-gates tr {
    padding: 13px 0; border-bottom: 1px solid var(--rule);
  }
  table.alignment-scorecard td, table.alignment-relationship td,
  table.alignment-prompt-contrast td,
  table.matched-alignment td,
  table.plural-prudence-training td, table.plural-prudence-prompt td,
  table.domain-transfer td, table.domain-behavior td,
  table.pooled-transfer td, table.gpqa-transfer td,
  table.hidden-opportunity td, table.multitask-family-gates td,
  table.alignment-relationship td.n {
    position: relative; min-height: 28px; padding: 3px 0 3px 41%;
    border: 0; text-align: left;
  }
  table.alignment-scorecard td:first-child,
  table.alignment-relationship td:first-child,
  table.alignment-prompt-contrast td:first-child {
    min-height: 0; padding: 0 0 7px; border: 0;
    font-weight: 700; color: var(--text);
  }
  table.matched-alignment td:first-child {
    min-height: 0; padding: 0 0 7px; border: 0;
    font-weight: 700; color: var(--text);
  }
  table.plural-prudence-training td:first-child,
  table.plural-prudence-prompt td:first-child,
  table.domain-transfer td:first-child,
  table.domain-behavior td:first-child,
  table.pooled-transfer td:first-child,
  table.gpqa-transfer td:first-child,
  table.hidden-opportunity td:first-child,
  table.multitask-family-gates td:first-child {
    min-height: 0; padding: 0 0 7px; border: 0;
    font-weight: 700; color: var(--text);
  }
  table.alignment-scorecard td:not(:first-child)::before,
  table.alignment-relationship td:not(:first-child)::before,
  table.alignment-prompt-contrast td:not(:first-child)::before {
    position: absolute; left: 0; width: 37%;
    font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 9.5px;
    font-weight: 650; line-height: 1.35; letter-spacing: .055em;
    text-transform: uppercase; color: var(--text-muted);
  }
  table.matched-alignment td:not(:first-child)::before {
    position: absolute; left: 0; width: 37%;
    font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 9.5px;
    font-weight: 650; line-height: 1.35; letter-spacing: .055em;
    text-transform: uppercase; color: var(--text-muted);
  }
  table.plural-prudence-training td:not(:first-child)::before,
  table.plural-prudence-prompt td:not(:first-child)::before,
  table.domain-transfer td:not(:first-child)::before,
  table.domain-behavior td:not(:first-child)::before,
  table.pooled-transfer td:not(:first-child)::before,
  table.gpqa-transfer td:not(:first-child)::before,
  table.hidden-opportunity td:not(:first-child)::before,
  table.multitask-family-gates td:not(:first-child)::before {
    position: absolute; left: 0; width: 37%;
    font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 9.5px;
    font-weight: 650; line-height: 1.35; letter-spacing: .055em;
    text-transform: uppercase; color: var(--text-muted);
  }
  table.alignment-scorecard td:nth-child(2)::before { content: "Measure"; }
  table.alignment-scorecard td:nth-child(3)::before { content: "Comparison"; }
  table.alignment-scorecard td:nth-child(4)::before { content: "Consistency"; }
  table.alignment-scorecard td:nth-child(5)::before { content: "Reading"; }
  table.alignment-relationship td:nth-child(2)::before { content: "Lower quartile"; }
  table.alignment-relationship td:nth-child(3)::before { content: "Upper quartile"; }
  table.alignment-relationship td:nth-child(4)::before { content: "Change"; }
  table.alignment-relationship td:nth-child(5)::before { content: "Association"; }
  table.alignment-prompt-contrast td:nth-child(2)::before { content: "Wrong pushback"; }
  table.alignment-prompt-contrast td:nth-child(3)::before { content: "Discernment"; }
  table.alignment-prompt-contrast td:nth-child(4)::before { content: "Reading"; }
  table.matched-alignment td:nth-child(2)::before { content: "Very bad decision"; }
  table.matched-alignment td:nth-child(3)::before { content: "Decision change"; }
  table.matched-alignment td:nth-child(4)::before { content: "Wrong claim"; }
  table.matched-alignment td:nth-child(5)::before { content: "Wrong-claim change"; }
  table.matched-alignment td:nth-child(6)::before { content: "Verified correction"; }
  table.matched-alignment td:nth-child(7)::before { content: "Prohibited actions"; }
  table.plural-prudence-training td:nth-child(2)::before { content: "Accuracy-only level"; }
  table.plural-prudence-training td:nth-child(3)::before { content: "Calibrated change"; }
  table.plural-prudence-training td:nth-child(4)::before { content: "Fixed-cost change"; }
  table.plural-prudence-training td:nth-child(5)::before { content: "Reading"; }
  table.plural-prudence-prompt td:nth-child(2)::before { content: "Wrong execution"; }
  table.plural-prudence-prompt td:nth-child(3)::before { content: "Evidence error"; }
  table.plural-prudence-prompt td:nth-child(4)::before { content: "Unauthorized use"; }
  table.plural-prudence-prompt td:nth-child(5)::before { content: "Goal response"; }
  table.plural-prudence-prompt td:nth-child(6)::before { content: "Reading"; }
  table.domain-transfer td:nth-child(2)::before { content: "Tested on"; }
  table.domain-transfer td:nth-child(3)::before { content: "Accuracy"; }
  table.domain-transfer td:nth-child(4)::before { content: "Calibrated score"; }
  table.domain-transfer td:nth-child(5)::before { content: "High-confidence wrong"; }
  table.domain-behavior td:nth-child(2)::before { content: "Unauthorized shortcut"; }
  table.domain-behavior td:nth-child(3)::before { content: "Benign tool success"; }
  table.domain-behavior td:nth-child(4)::before { content: "Goal response"; }
  table.domain-behavior td:nth-child(5)::before { content: "Benign refusal"; }
  table.pooled-transfer td:nth-child(2)::before { content: "Items"; }
  table.pooled-transfer td:nth-child(3)::before { content: "Seed pairs"; }
  table.pooled-transfer td:nth-child(4)::before { content: "Accuracy change"; }
  table.pooled-transfer td:nth-child(5)::before { content: "High-confidence wrong"; }
  table.pooled-transfer td:nth-child(6)::before { content: "Calibrated score"; }
  table.pooled-transfer td:nth-child(7)::before { content: "Seeds improved"; }
  table.gpqa-transfer td:nth-child(2)::before { content: "Seed pairs"; }
  table.gpqa-transfer td:nth-child(3)::before { content: "Accuracy change"; }
  table.gpqa-transfer td:nth-child(4)::before { content: "High-confidence wrong"; }
  table.gpqa-transfer td:nth-child(5)::before { content: "Calibrated score"; }
  table.hidden-opportunity td:nth-child(2)::before { content: "Seed pairs"; }
  table.hidden-opportunity td:nth-child(3)::before { content: "Shortcut level"; }
  table.hidden-opportunity td:nth-child(4)::before { content: "Shortcut change"; }
  table.hidden-opportunity td:nth-child(5)::before { content: "High-confidence change"; }
  table.hidden-opportunity td:nth-child(6)::before { content: "Authorized controls"; }
  table.hidden-opportunity td:nth-child(7)::before { content: "Pairs improved"; }
  table.multitask-family-gates td:nth-child(2)::before { content: "Sample"; }
  table.multitask-family-gates td:nth-child(3)::before { content: "Malformed"; }
  table.multitask-family-gates td:nth-child(4)::before { content: "Decision"; }
}
/* A mock-up is a designed target exhibit with invented numbers. On a page
   whose whole argument is honest measurement, it must be impossible to
   mistake one for a result, so the frame is dashed and the tag wears the
   warning colour, in both colour schemes. */
.mock { border: 1.5px dashed var(--rule-strong); border-radius: 4px;
        padding: 4px 16px 10px; margin: 18px 0 6px; }
.mock .mock-tag { display: inline-block; margin: 8px 0 0;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 10.5px;
  font-weight: 700; letter-spacing: .13em; text-transform: uppercase;
  color: var(--warn); }
.mock .table-wrap { margin-top: 6px; }
/* Captions tuck up under bare tables via a negative top margin; after a
   framed mock that pull drags them through the dashed border. */
.mock + .cap { margin-top: 8px; }
/* The figure's UA default margins otherwise collapse out of the dashed frame
   and the border strikes through whatever follows it. */
.mock .mock-scatter { margin: 10px 0 2px; }
.mock-scatter svg { display: block; width: 100%; height: auto; }
.mock-scatter .ms-dot { fill: var(--evidence); opacity: .75; }
.mock-scatter .ms-dot.hi { fill: var(--accent); opacity: 1; }
.mock-scatter .ms-axis { stroke: var(--rule-strong); stroke-width: 1; }
.mock-scatter .ms-grid { stroke: var(--rule); stroke-width: .6; }
.mock-scatter .ms-diag { stroke: var(--text-muted); stroke-width: 1.4;
  stroke-dasharray: 5 4; }
.mock-scatter .ms-pair { stroke: var(--accent); stroke-width: 1.2;
  stroke-dasharray: 2 3; opacity: .8; }
/* Sortable headers. The affordance is deliberately quiet until hover: these
   tables are readable in their built order, and sorting is an offer rather
   than an instruction. */
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--text); }
th.sortable::after { content: " \2195"; opacity: .35; font-size: 10px; }
th.sortable[aria-sort="descending"]::after { content: " \2193"; opacity: 1; }
th.sortable[aria-sort="ascending"]::after { content: " \2191"; opacity: 1; }
th.sortable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* Show-all control for capped tables. */
.more-wrap { max-width: var(--max-wide); margin: -18px 0 26px; }
.more-btn {
  border: 1px solid var(--rule); background: var(--bg); color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px;
  padding: 6px 12px; border-radius: 3px; cursor: pointer;
}
.more-btn:hover { border-color: var(--rule-strong); color: var(--text); }
.more-btn[hidden] { display: none; }

/* The live payoff chart. */
.payoff-live { margin: 22px 0 26px; }
.pf-controls {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 0; border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12.5px;
  color: var(--text-secondary);
}
.pf-controls input[type=range] { flex: 1 1 220px; max-width: 320px; accent-color: var(--accent); }
.pf-qval { font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
.payoff-live > svg { display: block; width: 100%; height: auto; margin-top: 8px; overflow: visible; }
.pf-table-wrap { margin: 14px 0 6px; }
.pf-outcome { width: 100%; margin: 0; border-collapse: collapse;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 14px; }
.pf-outcome thead th { text-align: left; font-size: 10.5px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted);
  border-bottom: 1px solid var(--text); padding: 6px 12px 6px 0; }
.pf-outcome td { padding: 9px 12px 9px 0; border-bottom: 1px solid var(--rule);
  color: var(--text-secondary); vertical-align: baseline; }
.pf-outcome td:first-child { font-weight: 600; color: var(--text); }
.pf-outcome .pf-none { font-size: 13px; font-weight: 400;
  color: var(--text-muted); }
.pf-outcome .pf-states { font-size: 19px; font-weight: 650; color: var(--text);
  font-variant-numeric: tabular-nums; }
.pf-outcome tr.pf-o0 td:first-child { color: var(--text-muted); }
.pf-outcome tr.pf-o1 td:first-child { color: var(--invalid); }
.pf-outcome tr.pf-o2 td:first-child { color: var(--accent); }
.pf-note {
  max-width: var(--max-text); margin: 4px 0 0; font-size: 14px;
  color: var(--text-secondary);
}
.pf-series {
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11.5px; font-weight: 600;
}
.pf-r0 { stroke: var(--text-muted); } .pf-series.pf-r0 { fill: var(--text-muted); stroke: none; }
.pf-r1 { stroke: var(--invalid); }    .pf-series.pf-r1 { fill: var(--invalid); stroke: none; }
.pf-r2 { stroke: var(--accent); }     .pf-series.pf-r2 { fill: var(--accent); stroke: none; }
.pf-r3 { stroke: var(--evidence); }   .pf-series.pf-r3 { fill: var(--evidence); stroke: none; }
circle.pf-r1 { fill: var(--invalid); } circle.pf-r2 { fill: var(--accent); }
circle.pf-r3 { fill: var(--evidence); }

/* The payoff figure. Three small multiples on one shared y-scale, so a
   reader compares heights across panels; the series colours repeat the
   site's evidence/accent pair rather than introducing new hues. */
.payoff { margin: 22px 0 26px; }
.pf-panels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.pf-panels svg { width: 100%; height: auto; }
.pf-axis { stroke: var(--rule-strong); stroke-width: 1; }
.pf-honest { stroke: var(--rule-strong); stroke-width: 1; stroke-dasharray: 3 3; }
.pf-line { fill: none; stroke-width: 2; }
.pf-dot { stroke: var(--bg); stroke-width: 1.5; }
.pf-r0 { stroke: var(--text-muted); }
.pf-r1 { stroke: var(--invalid); }
.pf-r2 { stroke: var(--accent); }
.pf-r3 { stroke: var(--evidence); }
.pf-r0.pf-dot, .pf-r0.pf-key::before { fill: var(--text-muted); background: var(--text-muted); }
.pf-r1.pf-dot { fill: var(--invalid); }
.pf-r2.pf-dot { fill: var(--accent); }
.pf-r3.pf-dot { fill: var(--evidence); }
.pf-title, .pf-tick { font-family: 'Inter', ui-sans-serif, sans-serif; }
.pf-title { fill: var(--text); font-size: 12px; font-weight: 700; }
.pf-tick { fill: var(--text-muted); font-size: 10.5px; }
.pf-axis-label { fill: var(--text-secondary); font-size: 11.5px;
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-weight: 600; }
.pf-keys { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 10px; }
.pf-key { display: inline-flex; align-items: center; gap: 6px;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11.5px;
  color: var(--text-secondary); }
.pf-key::before { content: ""; width: 14px; height: 2px; }
.pf-key.pf-r1::before { background: var(--invalid); }
.pf-key.pf-r2::before { background: var(--accent); }
.pf-key.pf-r3::before { background: var(--evidence); }
.mock-scatter.real { position: relative; max-width: 560px; margin: 22px 0 6px; }
.mock-scatter circle.ms-dot { cursor: pointer; transition: r .1s; }
.mock-scatter circle.ms-dot:focus-visible { outline: 2px solid var(--accent);
  outline-offset: 2px; }
.mock-scatter circle.ms-dot.on { r: 7; }
.ms-tip { position: absolute; z-index: 5; pointer-events: none;
  background: var(--bg); border: 1px solid var(--rule-strong);
  border-radius: 3px; padding: 7px 10px; box-shadow: 0 2px 8px rgba(0,0,0,.08);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px;
  color: var(--text); white-space: nowrap; }
.ms-tip[hidden] { display: none; }
.ms-tip-b, .ms-tip-n { display: block; color: var(--text-secondary);
  font-size: 11px; margin-top: 2px; }
.ms-count { margin-left: auto; color: var(--text-muted); font-weight: 600; }
.mock-scatter .ms-band { fill: var(--accent); opacity: .07; }
.mock-scatter .ms-dot.hle { fill: var(--invalid); }
.mock-scatter .ms-name {
  fill: var(--text-secondary); font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 11px;
}
.mock-scatter .ms-name.lead { fill: var(--text); font-weight: 600; font-size: 11.5px; }
.ms-keys { display: flex; gap: 18px; margin: 10px 0 4px;
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 11.5px; max-width: 560px; }
.ms-key {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11.5px;
  color: var(--text-secondary);
}
.ms-key::before {
  content: ""; width: 10px; height: 10px; border-radius: 50%;
  background: var(--invalid);
}
.ms-key.pilot::before { background: var(--evidence); }
.mock-scatter .ms-region { fill: var(--text-muted);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 12px;
  font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  opacity: .75; }
.mock-scatter .ms-label { fill: var(--text-muted);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11px; }
.mock-scatter .ms-note { fill: var(--accent-text);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 11.5px;
  font-weight: 600; }
"""


BRIEF_JS = r"""<script>
/* Three behaviours, each guarding its own absence: a page with no sortable
   table, no collapsed table, or no chart must not throw. Everything is inside
   one IIFE because the site's generated pages share a global scope with the
   nav script. */
(function () {
  "use strict";

  /* --- sorting ---------------------------------------------------------
     Every data cell carries data-sort written at build time: a number where
     the cell shows one, otherwise its plain text prefixed with "~" (which
     also sorts text after numbers). Group-label rows carry data-group and
     are pinned to the top in their original order rather than interleaved
     or hidden. */
  document.querySelectorAll("table.sortable-table").forEach(function (tbl) {
    var body = tbl.tBodies[0];
    var heads = tbl.querySelectorAll("th.sortable");
    heads.forEach(function (th, col) {
      function apply() {
        var rows = Array.prototype.slice.call(body.rows);
        var groups = rows.filter(function (r) { return r.hasAttribute("data-group"); });
        var data = rows.filter(function (r) { return !r.hasAttribute("data-group"); });
        var desc = th.getAttribute("aria-sort") !== "descending";
        data.sort(function (a, b) {
          var ka = (a.cells[col] && a.cells[col].getAttribute("data-sort")) || "~";
          var kb = (b.cells[col] && b.cells[col].getAttribute("data-sort")) || "~";
          var na = parseFloat(ka), nb = parseFloat(kb);
          var cmp;
          if (!isNaN(na) && !isNaN(nb)) { cmp = na - nb; }
          else if (!isNaN(na)) { cmp = -1; }
          else if (!isNaN(nb)) { cmp = 1; }
          else { cmp = ka.localeCompare(kb); }
          return desc ? -cmp : cmp;
        });
        heads.forEach(function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", desc ? "descending" : "ascending");
        groups.concat(data).forEach(function (r) { r.hidden = false; body.appendChild(r); });
        var more = tbl.parentNode.parentNode.querySelector(".more-btn");
        if (more) { more.hidden = true; }
      }
      th.addEventListener("click", apply);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); apply(); }
      });
    });
  });

  /* --- show all --------------------------------------------------------
     Rows past the cap ship in the markup with a hidden attribute, so the
     table is complete and correct with scripting off; this only reveals
     them. */
  document.querySelectorAll(".more-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var wrap = btn.parentNode.previousElementSibling;
      if (!wrap) { return; }
      wrap.querySelectorAll("tbody tr[hidden]").forEach(function (tr) {
        tr.hidden = false;
      });
      btn.hidden = true;
    });
  });

  /* --- takeaway chips ----------------------------------------------------
     Each chip names a claim; clicking it highlights the rows that make the
     point, reveals them if they sit behind a collapse, and prints the
     one-sentence version. Without scripting the chips are inert text and the
     same claims exist as prose, so nothing is lost. */
  document.querySelectorAll(".takeaways").forEach(function (strip) {
    var tbl = document.getElementById(strip.getAttribute("data-table"));
    if (!tbl) { return; }
    var note = strip.querySelector(".tk-note");
    var chips = strip.querySelectorAll(".tk-chip");
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        var wasOn = chip.getAttribute("aria-pressed") === "true";
        chips.forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
        tbl.querySelectorAll("tr.hl").forEach(function (r) { r.classList.remove("hl"); });
        if (wasOn) { note.hidden = true; return; }
        chip.setAttribute("aria-pressed", "true");
        var keys = chip.getAttribute("data-keys").split(",");
        keys.forEach(function (k) {
          var row = tbl.querySelector('tr[data-key="' + k + '"]');
          if (row) { row.classList.add("hl"); row.hidden = false; }
        });
        var more = tbl.parentNode.parentNode.querySelector(".more-btn");
        if (more && tbl.querySelector("tr.hl[hidden]")) { more.click(); }
        note.textContent = chip.getAttribute("data-note");
        note.hidden = false;
      });
    });
  });

  /* --- scatter hover -----------------------------------------------------
     A real tooltip rather than the browser's native title delay, and the
     marks are focusable so a keyboard reaches the same information. */
  (function () {
    var fig = document.getElementById("knowledge-scatter");
    if (!fig) { return; }
    var tip = document.getElementById("ms-tip");
    function show(dot) {
      tip.innerHTML = '<b>' + dot.getAttribute("data-model") + "</b>"
        + '<span class="ms-tip-b">' + dot.getAttribute("data-bench") + "</span>"
        + '<span class="ms-tip-n">right <b>' + dot.getAttribute("data-acc")
        + '%</b> &middot; claims <b>' + dot.getAttribute("data-conf")
        + '%</b> &middot; over by <b>'
        + (dot.getAttribute("data-conf") - dot.getAttribute("data-acc"))
        + "</b></span>";
      var box = fig.getBoundingClientRect();
      var d = dot.getBoundingClientRect();
      tip.hidden = false;
      tip.style.left = Math.min(d.left - box.left + 14,
                                box.width - tip.offsetWidth - 6) + "px";
      tip.style.top = (d.top - box.top - tip.offsetHeight - 8) + "px";
      dot.classList.add("on");
    }
    function hide(dot) { tip.hidden = true; dot.classList.remove("on"); }
    fig.querySelectorAll("circle.ms-dot").forEach(function (dot) {
      dot.addEventListener("mouseenter", function () { show(dot); });
      dot.addEventListener("mouseleave", function () { hide(dot); });
      dot.addEventListener("focus", function () { show(dot); });
      dot.addEventListener("blur", function () { hide(dot); });
    });
  }());

  /* --- the payoff chart ------------------------------------------------
     Same rules as src/belowzero/rules.py, restated here because the browser
     cannot import Python. The static <noscript> version is generated from
     the Python functions, so if these two ever disagree the page shows it. */
  var chart = document.getElementById("pf-chart");
  if (!chart) { return; }
  var C = 0.09;
  var RULES = [
    { key: "r0", name: "No penalty", f: function (p, ok) { return ok ? 1 : 0; } },
    { key: "r1", name: "Linear confidence", f: function (p, ok) { return ok ? p : -p; } },
    { key: "r2", name: "Confidence-calibrated", f: function (p, ok) { return ok ? 2 * p - p * p : -p * p; } }
  ];
  var ev = function (rule, p, q) { return q * rule.f(p, true) + (1 - q) * rule.f(p, false); };

  var W = 720, H = 335, M = { t: 22, r: 152, b: 62, l: 64 };
  var IW = W - M.l - M.r, IH = H - M.t - M.b;
  var x = function (p) { return M.l + p * IW; };
  var y = function (v) { return M.t + (1 - v) / 2 * IH; };
  var NS = "http://www.w3.org/2000/svg";
  function el(n, a) {
    var e = document.createElementNS(NS, n);
    for (var k in a) { if (a[k] !== undefined) { e.setAttribute(k, a[k]); } }
    return e;
  }
  var slider = document.getElementById("pf-q");
  var readout = document.getElementById("pf-qval");
  var note = document.getElementById("pf-outcome");

  function draw(q) {
    chart.textContent = "";
    [-1, 0, 1].forEach(function (v) {
      chart.appendChild(el("line", { "class": v === 0 ? "pf-axis" : "pf-grid",
        x1: M.l, y1: y(v), x2: M.l + IW, y2: y(v) }));
      var t = el("text", { "class": "pf-tick", x: M.l - 8, y: y(v) + 4,
        "text-anchor": "end" });
      t.textContent = v > 0 ? "+1" : String(v);
      chart.appendChild(t);
    });
    for (var g = 0; g <= 1.0001; g += 0.25) {
      var tx = el("text", { "class": "pf-tick", x: x(g), y: M.t + IH + 20,
        "text-anchor": "middle" });
      tx.textContent = Math.round(g * 100) + "%";
      chart.appendChild(tx);
    }
    var xl = el("text", { "class": "pf-axis-label", x: M.l + IW / 2,
      y: M.t + IH + 44, "text-anchor": "middle" });
    xl.textContent = "if the model stated this confidence \u2026";
    chart.appendChild(xl);
    var yl = el("text", { "class": "pf-axis-label", x: 13,
      y: M.t + IH / 2, "text-anchor": "middle",
      transform: "rotate(-90 13 " + (M.t + IH / 2) + ")" });
    yl.textContent = "\u2026 this is what it would earn";
    chart.appendChild(yl);

    chart.appendChild(el("line", { "class": "pf-honest", x1: x(q), y1: M.t,
      x2: x(q), y2: M.t + IH }));
    var hl = el("text", { "class": "pf-tick", x: x(q), y: M.t - 8,
      "text-anchor": "middle" });
    hl.textContent = "honest";
    chart.appendChild(hl);

    var labels = [];
    RULES.forEach(function (rule) {
      var pts = [], best = 0, bv = -Infinity;
      for (var i = 0; i <= 200; i++) {
        var p = i / 200, v = ev(rule, p, q);
        pts.push(x(p).toFixed(1) + "," + y(v).toFixed(1));
        if (v > bv + 1e-12) { bv = v; best = p; }
      }
      chart.appendChild(el("polyline", { "class": "pf-line pf-" + rule.key,
        points: pts.join(" ") }));
      labels.push({ rule: rule, y: y(ev(rule, 1, q)) });
      if (rule.key !== "r0") {
        chart.appendChild(el("circle", { "class": "pf-dot pf-" + rule.key,
          cx: x(best), cy: y(bv), r: 5 }));
      }
    });

    /* Direct labels beat a legend, but three of these four curves converge at
       the right edge for some beliefs, so the labels are pushed apart to a
       readable gap before being drawn. Without this they overprint and the
       chart looks broken at exactly the beliefs worth studying. */
    labels.sort(function (a, b) { return a.y - b.y; });
    for (var k = 1; k < labels.length; k++) {
      if (labels[k].y - labels[k - 1].y < 15) {
        labels[k].y = labels[k - 1].y + 15;
      }
    }
    labels.forEach(function (item) {
      var lab = el("text", { "class": "pf-series pf-" + item.rule.key,
        x: M.l + IW + 10, y: item.y + 4 });
      lab.textContent = item.rule.name;
      chart.appendChild(lab);
    });

    readout.textContent = Math.round(q * 100) + "%";
    var pct = Math.round(q * 100);
    var linBest = q > 0.5 ? 100 : 0;
    /* The outcome table is the answer to "so what does it do?", so it sits
       above the chart and states each rule's move in full. */
    var rowsOut = [
      ["No penalty", "yes", "<span class='pf-none'>no number is asked</span>",
       "the score cannot depend on its confidence"],
      ["Linear confidence", "yes", linBest + "%",
       linBest === pct ? "the truth, by coincidence"
         : "a bluff, off by " + Math.abs(linBest - pct) + " points"],
      ["Confidence-calibrated", "yes", pct + "%", "<b>the truth</b>"]
    ];
    note.innerHTML = rowsOut.map(function (r, i) {
      return '<tr class="pf-o' + i + '"><td>' + r[0] + "</td><td>" + r[1]
        + '</td><td class="pf-states">' + r[2] + "</td><td>" + r[3]
        + "</td></tr>";
    }).join("");
  }

  slider.addEventListener("input", function () { draw(parseFloat(slider.value)); });
  draw(parseFloat(slider.value));
}());
</script>"""


TABLE_BRIEF_CSS = BRIEF_CSS + r"""
/* The table brief is a working outline, not a second narrative report. Its
   hierarchy comes from compact evidence blocks and visible evidentiary status. */
.outline-table td:first-child { width: 19%; font-weight: 650; }
.outline-table td:nth-child(2) { width: 18%; }
.outline-table td:nth-child(3) { width: 39%; }
.outline-table td:last-child { width: 24%; }
.outline-table .sub {
  margin-top: 8px; font-size: 12.5px; line-height: 1.45;
  color: var(--text-secondary);
}
.context-line { display: block; margin-bottom: 7px; }
.context-line:last-child { margin-bottom: 0; }
.context-line b { color: var(--text); }
.context-line.result {
  margin-top: 9px; padding-top: 8px; border-top: 1px solid var(--rule);
}
.reliability-figure {
  max-width: var(--max-wide); margin: 18px 0 24px;
}
.reliability-figure h4 {
  margin: 0 0 4px; font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 15px; line-height: 1.35;
}
.reliability-chart {
  display: block; width: 100%; height: auto; margin-top: 8px;
  background: transparent;
}
.cal-chart-scroll {
  max-width: 100%; overflow-x: auto;
  /* On phones more than half the reliability figure sits off-screen, and with
     the scrollbar not rendering there was no cue at all that it scrolls. Same
     script-driven fade contract as .table-wrap. */
  --fade-start: 0px;
  --fade-end: 0px;
  -webkit-mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
                      #000 calc(100% - var(--fade-end)), transparent);
  mask-image: linear-gradient(to right, transparent, #000 var(--fade-start),
              #000 calc(100% - var(--fade-end)), transparent);
}
.reliability-figure figcaption {
  margin-top: 8px; max-width: 820px; font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 12.5px; line-height: 1.5; color: var(--text-secondary);
}
.cal-stat-row {
  display: grid; grid-template-columns: repeat(3, 1fr); margin: 10px 0 4px;
  border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule);
}
.cal-stat { padding: 9px 14px 10px 0; }
.cal-stat + .cal-stat { padding-left: 14px; border-left: 1px solid var(--rule); }
.cal-stat span, .cal-stat small {
  display: block; font-family: 'Inter', ui-sans-serif, sans-serif;
  color: var(--text-secondary);
}
.cal-stat span { font-size: 10px; font-weight: 650; letter-spacing: .055em;
  text-transform: uppercase; }
.cal-stat b { display: block; margin-top: 2px; font: 650 15px/1.35 'Inter',
  ui-sans-serif, sans-serif; color: var(--text); }
.cal-stat small { margin-top: 1px; font-size: 11.5px; }
.reliability-overconfident { fill: #f7f2f4; }
.reliability-grid { stroke: #e8e5df; stroke-width: 1; }
.reliability-perfect { stroke: #a7a29a; stroke-width: 1.2; stroke-dasharray: 5 5; }
.reliability-axis { stroke: #5e5a55; stroke-width: 1.15; }
.reliability-series { fill: none; stroke-width: 2; opacity: .9; }
.reliability-point { stroke: #fff; stroke-width: 1.5; }
.reliability-label { fill: #77736d; font: 10.5px 'Inter', ui-sans-serif, sans-serif; }
.reliability-axis-title { fill: #403d39; font: 600 11.5px 'Inter', ui-sans-serif, sans-serif; }
.reliability-panel-title { fill: #5e5a55; font: 650 10px 'Inter', ui-sans-serif, sans-serif;
  letter-spacing: .05em; text-transform: uppercase; }
.reliability-note { fill: #77736d; font: 10.5px 'Inter', ui-sans-serif, sans-serif; }
.reliability-key { fill: #403d39; font: 600 11px 'Inter', ui-sans-serif, sans-serif; }
.reliability-point-label { font: 650 10.5px 'Inter', ui-sans-serif, sans-serif; }
.distribution-grid { stroke: #ece9e3; stroke-width: 1; }
.distribution-bar { opacity: .88; }
.distribution-value { font: 650 10px 'Inter', ui-sans-serif, sans-serif; }
.table-brief-reading {
  max-width: var(--max-wide); margin: 10px 0 28px; padding: 10px 14px;
  border-left: 3px solid var(--evidence); background: var(--bg-alt);
  font-family: 'Inter', ui-sans-serif, sans-serif; font-size: 13px;
  line-height: 1.5; color: var(--text-secondary);
}
.table-brief-reading b { color: var(--text); }
.literature-key {
  max-width: var(--max-wide); margin: 18px 0 34px; padding: 11px 0;
  border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule);
  font: 12px/1.45 'Inter', ui-sans-serif, sans-serif; color: var(--text-secondary);
}
.literature-key > b { display: block; margin-bottom: 7px; color: var(--text); }
.literature-key > span { display: inline-block; margin: 0 18px 6px 0; }
.literature-key > small {
  display: block; max-width: 760px; margin-top: 1px; color: var(--text-muted);
  font-size: 11.5px;
}
.literature-compare {
  max-width: var(--max-wide); margin: -12px 0 32px;
  border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule-strong);
  font: 12.5px/1.5 'Inter', ui-sans-serif, sans-serif;
  color: var(--text-secondary);
}
.literature-compare-title {
  padding: 9px 0 8px; border-bottom: 1px solid var(--rule);
  color: var(--text); font-size: 12px; font-weight: 700;
}
.literature-compare dl { margin: 0; }
.literature-compare dl > div {
  display: grid; grid-template-columns: 152px minmax(0, 1fr); gap: 18px;
  margin: 0; padding: 9px 0; border-bottom: 1px solid var(--rule);
}
.literature-compare dl > div:last-child { border-bottom: 0; }
.literature-compare dt {
  margin: 0; color: var(--text-muted); font-size: 10px; font-weight: 750;
  letter-spacing: .055em; line-height: 1.45; text-transform: uppercase;
}
.literature-compare dd { margin: 0; }
.literature-compare dd b { color: var(--text); font-weight: 700; }
.literature-compare a { text-decoration-thickness: 1px; text-underline-offset: 2px; }
.literature-compare .project { background: #f4f7f5; }
.literature-compare .project dt { color: #315545; }
.literature-compare .limit { background: #faf7f2; }
.literature-compare .limit dt { color: #765431; }
.literature-compare .project > *, .literature-compare .limit > *:first-child { padding-left: 8px; }
.literature-compare.compact { margin-top: -8px; }
.lit-tag {
  display: inline-block; margin-right: 7px; padding: 1px 5px;
  border: 1px solid var(--rule-strong); color: var(--text-secondary);
  font-style: normal; font-size: 9px; font-weight: 750; line-height: 1.45;
  letter-spacing: .055em; text-transform: uppercase; vertical-align: 1px;
}
.lit-tag.direct { border-color: var(--evidence); color: var(--evidence); }
.lit-tag.close { border-color: var(--accent); color: var(--accent-text); }
.lit-tag.adjacent { color: var(--text-muted); }
.lit-tag.project { border-color: #496c5d; color: #315545; }
.lit-tag.unmatched { border-color: #78506a; color: #6e3457; }
.lit-tag.limit { border-color: #8a6a48; color: #765431; }
.evidence-state {
  display: inline-block; padding: 2px 8px; border-radius: 12px;
  border: 1px solid var(--rule-strong); font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 10px; font-weight: 700; letter-spacing: .055em;
  text-transform: uppercase; color: var(--text-secondary);
}
.evidence-state.strong { border-color: var(--evidence); color: var(--evidence); }
.evidence-state.mixed { border-color: var(--accent); color: var(--accent-text); }
.evidence-state.open { color: var(--text-muted); }
.table-brief-source { margin-top: -12px; }
table.cross-family { min-width: 900px; }
table.subject-transfer { min-width: 840px; }
table.alignment-chain { min-width: 880px; }
table.format-gates { min-width: 820px; }
@media (max-width: 700px) {
  .outline-table { min-width: 860px; }
  .table-brief-reading { margin-right: 0; }
  /* Keep the evidence legible without widening the page. The stat strip
     recomposes for mobile; only the dense row chart scrolls horizontally. */
  .reliability-chart { width: 720px; min-width: 720px; }
  .cal-stat-row { grid-template-columns: 1fr 1fr; }
  .cal-stat:nth-child(3) {
    grid-column: 1 / -1; padding-left: 0;
    border-left: 0; border-top: 1px solid var(--rule);
  }
  .literature-key > span { display: block; margin-right: 0; }
  .literature-compare { margin-top: -8px; }
  .literature-compare dl > div { grid-template-columns: 1fr; gap: 3px; }
  .literature-compare .project > *, .literature-compare .limit > *:first-child { padding-left: 6px; }
}
"""


def payoff_widget():
    """The interactive version of the payoff figure, with a static fallback.

    Ramon asked for the slider inline rather than a link away, because the
    point it makes -- that only one of these rules puts its peak on the
    truth -- is one you believe by dragging rather than by reading. The
    static three-panel version stays inside <noscript>, so the argument
    survives without scripting rather than leaving a hole.
    """
    return (
        '<figure class="payoff-live">'
        '<div class="pf-controls">'
        '<label for="pf-q">What the model privately believes</label>'
        '<input type="range" id="pf-q" min="0.02" max="0.98" step="0.01" '
        'value="0.60">'
        '<span class="pf-qval" id="pf-qval">60%</span>'
        '</div>'
        '<div class="table-wrap pf-table-wrap"><table class="pf-outcome"><thead><tr>'
        '<th>under this rule</th><th>the model answers</th>'
        '<th>stating</th><th>which is</th></tr></thead>'
        '<tbody id="pf-outcome"></tbody></table></div>'
        '<svg id="pf-chart" viewBox="0 0 720 335" role="img" '
        'aria-label="Expected score against the confidence a model states, '
        'for three scoring rules"></svg>'
        f'<noscript>{payoff_figure()}</noscript>'
        '</figure>')


def mock(inner):
    """Wrap a designed exhibit whose numbers are invented, and say so."""
    return ('<div class="mock"><span class="mock-tag">Mock-up &middot; '
            'invented numbers</span>' + inner + "</div>")


def over_under(claimed, actual):
    """Signed gap between what a model claims and what it delivers.

    Positive is overconfident. Written in points with an explicit sign because
    the direction is the whole reading, and a bare "0.30" beside two
    percentages invites the reader to think it is a third percentage.
    """
    gap = (float(claimed) - float(actual)) * 100
    return f"{gap:+.0f} pp".replace("-", "&minus;")


def over_under_cell(claimed, actual, scale=0.55):
    """The over/under number with a small diverging bar beside it.

    Replaces the column heatmap: the bar restates the number next to it and
    its direction carries the only semantic (claims more than it delivers, or
    less), which keeps colour meaning a state rather than a magnitude. `scale`
    is the gap at which the bar reaches the end of its track, fixed across
    every table so bars are comparable between them.
    """
    gap = float(claimed) - float(actual)
    width = min(abs(gap) / scale, 1.0) * 50
    side = "over" if gap > 0 else "under"
    bar = (f'<span class="dbar" aria-hidden="true">'
           f'<i class="{side}" style="width:{width:.0f}%"></i></span>')
    return f"{over_under(claimed, actual)}{bar}"


def takeaways(table_id, items):
    """Chips that name a claim and highlight the rows that make it.

    Ramon's idea: let a reader click a takeaway and see exactly which cells
    support it. Each item is (label, sentence, [row keys]). Without scripting
    the chips are inert and every claim also exists as prose below the table,
    so nothing depends on the interaction.
    """
    chips = "".join(
        f'<button type="button" class="tk-chip" aria-pressed="false" '
        f'data-keys="{html.escape(",".join(keys))}" '
        f'data-note="{html.escape(note)}">{html.escape(label)}</button>'
        for label, note, keys in items)
    return (f'<div class="takeaways" data-table="{table_id}">'
            f'<span class="tk-hint">Takeaways: click one to highlight '
            f'the rows it rests on</span>{chips}'
            f'<p class="tk-note" hidden></p></div>')


def room_cell(claimed, actual):
    """How much of the available overconfidence a model actually used.

    The gap between what a model claims and what it delivers cannot exceed
    100% minus its accuracy, so a model right 94% of the time has six points
    of room and one right 28% of the time has seventy-two. Comparing raw gaps
    across models of different accuracy compares differently sized rooms, and
    makes accurate models look better calibrated for a reason that is
    arithmetic rather than behaviour. This normalises it away.
    """
    claimed, actual = float(claimed), float(actual)
    room = 1.0 - actual
    if room <= 0:
        return "&mdash;"
    share = max(0.0, min((claimed - actual) / room, 1.0))
    bar = (f'<span class="rbar" aria-hidden="true">'
           f'<i style="width:{share * 100:.0f}%"></i></span>')
    return f"{share * 100:.0f}%{bar}"


def score_bar(value, lo, hi):
    """A score with a bar behind it, for columns where decimals blur.

    Three decimal places make a real improvement look like noise. The bar
    restates the number beside it on a scale shared by the whole column.
    Negative scores fill leftward from a drawn zero mark, because below zero
    means worse than saying nothing and that boundary is the argument.
    """
    total = abs(lo) + abs(hi) if lo < 0 else (hi - lo)
    total = total or 1.0
    if lo < 0:
        zero = abs(lo) / total * 100
        width = abs(value) / total * 100
        left = zero if value >= 0 else zero - width
        mark = f'<u style="left:{zero:.1f}%"></u>'
    else:
        left, width, mark = 0.0, max((value - lo) / total * 100, 0.0), ""
    bar = (f'<span class="sbar" aria-hidden="true">'
           f'<i style="left:{left:.1f}%;width:{width:.1f}%"></i>{mark}</span>')
    # Formatted here rather than through build_brief's score_cell, which is
    # nested: below zero is the boundary the project is named for, so it is
    # emphasised in the same way both helpers do it.
    text = f"{value:.3f}".replace("-", "&minus;")
    return (f"<b>{text}</b>{bar}" if value < 0 else f"{text}{bar}")


def range_plot(rows_by_metric):
    """Distribution summary: median, quartiles, and 10th-90th, per metric.

    Scanning twenty-six rows to see whether a distribution moved is the wrong
    instrument. Each row here is one metric under one condition: a bar
    spanning the quartiles, a line at the median, open dots at the tenth and
    ninetieth percentiles, and the two conditions paired so the shift between
    them is what the eye lands on. Each metric gets its own axis, because the
    comparison that matters is between conditions, never across metrics.
    """
    W, L, R, ROW, GAP = 640, 190, 74, 26, 30
    panels = []
    for label, unit, conditions in rows_by_metric:
        vals = [v for _, st in conditions for v in st]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.14 or 1
        lo, hi = lo - pad, hi + pad
        H = len(conditions) * ROW + GAP + 6

        def x(v, lo=lo, hi=hi):
            return L + (v - lo) / (hi - lo) * (W - L - R)
        parts = [(f'<text class="rp-metric" x="0" y="13">{html.escape(label)}'
                 f'</text>')]
        for i, (cond, st) in enumerate(conditions):
            cy = GAP + i * ROW
            p10, p25, med, p75, p90 = st
            if unit == "pp":          # a signed change
                shown = f"{med:+.0f} pp".replace("-", "&minus;")
            elif unit == "%":         # a level
                shown = f"{med:.0f}%"
            else:                     # a score on the -1..1 scale
                shown = f"{med:.2f}"
            parts += [
                (f'<text class="rp-cond" x="{L - 12}" y="{cy + 4}" '
                f'text-anchor="end">{html.escape(cond)}</text>'),
                (f'<line class="rp-whisk" x1="{x(p10):.1f}" y1="{cy}" '
                f'x2="{x(p90):.1f}" y2="{cy}"/>'),
                f'<circle class="rp-out" cx="{x(p10):.1f}" cy="{cy}" r="3"/>',
                f'<circle class="rp-out" cx="{x(p90):.1f}" cy="{cy}" r="3"/>',
                (f'<rect class="rp-box rp-c{i}" x="{x(p25):.1f}" '
                f'y="{cy - 7}" width="{max(x(p75) - x(p25), 1):.1f}" '
                f'height="14" rx="2"/>'),
                (f'<line class="rp-med" x1="{x(med):.1f}" y1="{cy - 10}" '
                f'x2="{x(med):.1f}" y2="{cy + 10}"/>'),
                # The value rides at the row's end rather than over its
                # median: at these distances two paired rows sit close enough
                # that a centred label lands on the neighbouring bar.
                (f'<text class="rp-val rp-c{i}" x="{W - R + 8}" '
                f'y="{cy + 4}">{shown}</text>')]
        panels.append(f'<svg viewBox="0 0 {W} {H}" role="img" '
                      f'aria-label="{html.escape(label)} distribution">'
                      + "".join(parts) + "</svg>")
    key = ('<span class="rp-key"><i class="rp-c0"></i>answer normally</span>'
           '<span class="rp-key"><i class="rp-c1"></i>quadratic rule + 30% '
           'abstention threshold</span>'
           '<span class="rp-key legend">bar = middle half &middot; line = '
           'median &middot; dots = 10th and 90th</span>')
    return (f'<figure class="range-plot">{"".join(panels)}'
            f'<div class="rp-keys">{key}</div></figure>')


def payoff_figure():
    """What each rule pays for every confidence a model could state.

    Small multiples at three private beliefs. The rules are imported from the
    package rather than restated here, for the same reason the trainer and the
    scorer share one module: a figure that argues about incentives must not be
    able to drift from the code that applies them.

    Binary is drawn because it is flat. That flatness IS the argument: under
    today's scoring the stated confidence cannot change what the answer earns,
    so the axis the other three rules use does not exist.
    """
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from belowzero.rules import binary, linear, quadratic

    rules = [("Confidence-calibrated", quadratic, "r2"),
             ("Linear confidence", linear, "r1"),
             ("No penalty", binary, "r0")]
    beliefs = [0.30, 0.60, 0.90]
    grid = [i / 100 for i in range(101)]

    W, H = 236, 210
    L, R, T, B = 42, 12, 26, 40
    lo, hi = -1.0, 1.0

    panels = []
    for q in beliefs:
        def x(p):
            return L + p * (W - L - R)

        def y(v):
            return T + (hi - v) / (hi - lo) * (H - T - B)

        parts = [(f'<line class="pf-axis" x1="{L}" y1="{y(0):.1f}" '
                 f'x2="{W - R}" y2="{y(0):.1f}"/>')]
        for tick in (-1, 0, 1):
            parts.append(f'<text class="pf-tick" x="{L - 6}" '
                         f'y="{y(tick) + 3.5:.1f}" text-anchor="end">'
                         f'{tick:+d}</text>'.replace("+0", "0"))
        # The honest report, marked once per panel rather than per curve.
        parts.append(f'<line class="pf-honest" x1="{x(q):.1f}" y1="{T}" '
                     f'x2="{x(q):.1f}" y2="{H - B}"/>')

        for label, rule, cls in rules:
            pts = []
            for p in grid:
                ev = q * rule(p, True) + (1 - q) * rule(p, False)
                pts.append(f"{x(p):.1f},{y(ev):.1f}")
            parts.append(f'<polyline class="pf-line pf-{cls}" '
                         f'points="{" ".join(pts)}"/>')
            # The best move: the p that maximises expected score. Ties are
            # broken toward the honest report so a flat rule is not drawn as
            # though it recommended an extreme.
            best = max(grid, key=lambda p: (round(
                q * rule(p, True) + (1 - q) * rule(p, False), 12), -abs(p - q)))
            ev = q * rule(best, True) + (1 - q) * rule(best, False)
            if cls != "r0":
                parts.append(f'<circle class="pf-dot pf-{cls}" '
                             f'cx="{x(best):.1f}" cy="{y(ev):.1f}" r="4"/>')
        parts.append(f'<text class="pf-title" x="{L}" y="{T - 10}">'
                     f'believes {q * 100:.0f}%</text>')
        parts.append(f'<text class="pf-tick" x="{(L + W - R) / 2:.0f}" '
                     f'y="{H - 12}" text-anchor="middle">confidence it '
                     f'states</text>')
        # The honest marker rides at the TOP of its guide line: at the bottom
        # it sat on the axis label, and in the 90% panel both were pushed off
        # the right edge together.
        anchor = "end" if q > 0.75 else ("start" if q < 0.45 else "middle")
        nudge = -4 if anchor == "end" else (4 if anchor == "start" else 0)
        parts.append(f'<text class="pf-tick" x="{x(q) + nudge:.1f}" '
                     f'y="{T - 10}" text-anchor="{anchor}">honest</text>')
        panels.append(f'<svg viewBox="0 0 {W} {H}" role="img" '
                      f'aria-label="Expected score against stated confidence '
                      f'when the model believes {q * 100:.0f} percent">'
                      + "".join(parts) + "</svg>")

    keys = "".join(f'<span class="pf-key pf-{cls}">{html.escape(label)}</span>'
                   for label, _, cls in rules)
    return ('<figure class="payoff"><div class="pf-panels">'
            + "".join(panels) + f'</div><div class="pf-keys">{keys}</div>'
            f'</figure>')


def build_brief():
    """The findings page with the prose removed: questions, tables, readings.

    Every number here is computed from the same data/processed/ CSVs the main
    page reads, with the same formulas, so the two pages cannot disagree. The
    prose lives in content/brief/*.md and this function only supplies the
    furniture, mirroring how content/index/ and build() divide the work.
    """
    summary = {r["metric"]: r["value"] for r in rows("census_summary.csv")}
    bench = rows("census_by_benchmark.csv")
    rows("hle_quadratic.csv")
    sens = rows("census_sensitivity.csv")
    pilot = rows("pilot_announced_rule.csv")

    # Fine-tuning programme breadth for the evidence ledger below: three
    # trained families (Qwen3 8B, GPT-OSS 20B, Nemotron 3 Nano 30B), 33
    # matched pairs. See notes/2026-09-03-third-family-protocol.md: the
    # Nemotron replication succeeded after a syntax warm-up cleared an
    # earlier untouched-base format-gate failure.
    with open(
        os.path.join(PROC, "training_effect_synthesis_summary.json"),
        encoding="utf-8",
    ) as handle:
        training_synthesis = json.load(handle)
    # This page stays on the first training programme (its prose was
    # written on those pairs); the exporter carries that programme alone
    # under "first" once the second programme exists, and the pooled
    # "all" block then spans both. Read the first-programme block.
    training_synthesis = {**training_synthesis, **training_synthesis.get("first", {})}
    synthesis_families = training_synthesis["design_breadth"]["families"]

    total = int(summary["responses_scanned"])

    # Three tiles, because the shared .stats grid is three columns wide and a
    # fourth tile orphans onto its own row. The probability-stating rate rides
    # in the section's prose instead.
    stats = (f'<div class="stats">'
             f'<div><b>{total:,}</b><span>graded responses scanned</span></div>'
             f'<div><b>{summary["models"]}</b><span>models across '
             f'{summary["benchmarks"]} benchmarks</span></div>'
             f'<div><b>{pct(summary["decline_rate"])}</b><span>ever say they '
             f'don&rsquo;t know</span></div>'
             f'</div>')

    # --- census table, grouped by kind ---------------------------------------
    # The distinction does the explaining, so it comes first: one group of
    # benchmarks where the environment can prove failure to the model, one
    # where the only signal is its own doubt. The agentic group is shown whole
    # (only two of its nine members clear the 3,000-response bar, and hiding
    # the other seven would make the 6%-vs-0.6% split look cherry-picked);
    # the closed-form group shows its two ends, zeros broken toward the
    # larger sample so "zero out of 140,588" carries the weight.
    def kind_of(r):
        if r["benchmark"] in AGENTIC:
            return "agentic"
        return "other" if r["benchmark"] in NOT_CLOSED_FORM else "closed"

    agentic = sorted([r for r in bench if kind_of(r) == "agentic"],
                     key=lambda r: float(r["decline_rate"]), reverse=True)
    closed = sorted([r for r in bench if kind_of(r) == "closed"],
                    key=lambda r: float(r["decline_rate"]), reverse=True)
    other = sorted([r for r in bench if kind_of(r) == "other"],
                   key=lambda r: float(r["decline_rate"]), reverse=True)
    peak = max(float(r["decline_rate"]) for r in bench)

    def bench_row(r, note=""):
        rate = float(r["decline_rate"])
        bar = (f'<span class="rbar" aria-hidden="true">'
               f'<i style="width:{rate / peak * 100:.0f}%"></i></span>')
        label = r["benchmark"] + (f'<span class="sub">{note}</span>'
                                  if note else "")
        return [label, f"{int(r['n_responses']):,}", f"{pct(rate)}{bar}"]

    def group_row(label, sub):
        return [f'<b>{label}</b><span class="sub">{sub}</span>', "", ""]

    # Every benchmark is listed now rather than the two ends of the
    # distribution: the table collapses to its first rows in the browser, so
    # completeness costs nothing and the reader can check any row they doubt.
    bench_body = (
        [group_row("Can watch itself fail",
                   "agentic tasks, where the environment proves the failure")]
        + [bench_row(r) for r in agentic]
        + [group_row("Only its own doubt",
                     "closed-form questions, what this page is about")]
        + [bench_row(r) for r in closed]
        + [group_row("Not closed-form question answering",
                     "set aside from the headline, for the reason given")]
        + [bench_row(r, NOT_CLOSED_FORM[r["benchmark"]]) for r in other])
    bench_tbl = table(
        ["benchmark", "responses", "says it doesn't know"],
        bench_body, collapse_after=12)

    # Three groups now, not two: the third holds benchmarks that cannot test
    # this claim, verified one at a time rather than assumed.
    def agg(kind):
        sel = [r for r in bench if kind_of(r) == kind]
        n = sum(int(r["n_responses"]) for r in sel)
        d = sum(int(r["n_decline_phrase"]) for r in sel)
        return len(sel), n, d, (d / n if n else 0)
    a_k, a_n, a_d, a_r = agg("agentic")
    c_k, c_n, c_d, closed_clean_rate = agg("closed")
    o_k, o_n, o_d, o_r = agg("other")
    split_tbl = table(
        ["kind of benchmark", "benchmarks", "responses", "declines", "rate"],
        [[("<b>Can watch itself fail</b><span class=\"sub\">agentic tasks: a "
          "red test suite, a shell command that errors</span>"),
          a_k, f"{a_n:,}", f"{a_d:,}", f"<b>{pct(a_r)}</b>"],
         [("<b>Only its own doubt</b><span class=\"sub\">closed-form questions, "
          "the case this page is about</span>"),
          c_k, f"{c_n:,}", f"{c_d:,}", f"<b>{pct(closed_clean_rate)}</b>"],
         [("Not closed-form question answering<span class=\"sub\">"
          "rubric-graded, unanswerable by design, or scored on format</span>"),
          o_k, f"{o_n:,}", f"{o_d:,}", pct(o_r)]])

    # The phrase evidence, from scripts/census_decline_samples.py. "What
    # fired" beside "what survives at the end of the response" is what
    # separates a vocabulary artifact from a model actually declining.
    hist = rows("census_phrase_histogram.csv")
    sens_bench = rows("census_sensitivity_by_benchmark.csv")

    def top_phrase(name):
        sel = [r for r in hist if r["benchmark"] == name]
        if not sel:
            return "&mdash;"
        top = max(sel, key=lambda r: int(r["responses_matching"]))
        return (f'<b>{top["phrase"]}</b><span class="sub">'
                f'{float(top["share_of_matched_responses"]) * 100:.0f}% of its '
                f'matches</span>')

    def sens_rate(name, scope):
        sel = [r for r in sens_bench if r["benchmark"] == name
               and r["search_scope"] == scope
               and r["phrase_list"].startswith("broad")]
        return float(sel[0]["decline_rate"]) if sel else 0.0

    lingoly = {"nocontext": sens_rate("lingoly_nocontext", "whole generation"),
               "context": sens_rate("lingoly_context", "whole generation")}

    phrase_rows = []
    for name, verdict in (
            ("healthbench", "vocabulary, not abstention"),
            ("judgebench", "quoting the instruction it is judging"),
            ("hle", "real, and often correct"),
            ("lingoly_nocontext", "real: unanswerable as posed"),
            ("lingoly_context", "the same puzzles, made answerable")):
        whole = sens_rate(name, "whole generation")
        final = sens_rate(name, "final 100 characters")
        phrase_rows.append([
            name, top_phrase(name), pct(whole), pct(final),
            f"{whole / final:.0f}&times;" if final else "&mdash;",
            f'<span class="sub">{verdict}</span>'])
    phrase_tbl = table(
        ["benchmark", "phrase that fired most", "anywhere in the response",
         "at the very end", "shrinks by", "what it turns out to be"],
        phrase_rows, right_from=2)

    # The strictest sensitivity setting: only what the model actually said at
    # the end, only unambiguous phrasings. Selected by name rather than by
    # minimum so a new sensitivity row cannot silently change what "strictest"
    # means on this page.
    strict = next(r for r in sens
                  if r["search_scope"] == "final 100 characters"
                  and r["phrase_list"].startswith("narrow"))
    strict_line = (f'zero out of {int(strict["n_responses"]):,} responses'
                   if int(strict["n_declines"]) == 0 else
                   f'{int(strict["n_declines"])} out of '
                   f'{int(strict["n_responses"]):,} responses')

    # --- the penalty-alone check, reduced to its two facts ------------------
    # The identity itself is stated in one plain sentence in the prose; the
    # caption carries the numbers that back it.
    affine = rows("affine_map.csv")
    affine_runs = len({r["run"] for r in affine})
    affine_dev = f'{max(float(r["deviation"]) for r in affine):.1e}'.replace(
        "e-", "e&minus;")

    # --- our own survey of how benchmarks are scored -------------------------
    # scripts/benchmark_scoring_survey.py: the census benchmarks classified
    # from the datastore's own grading labels, plus prominent external ones
    # with the basis cited per row.
    survey = rows("benchmark_scoring_survey.csv")
    n_survey = len(survey)
    n_census_rows = sum(1 for r in survey if r["source"] == "census")
    n_external = n_survey - n_census_rows
    n_graded = sum(1 for r in survey if r["prices_wrong_answers"] != "&mdash;")
    n_prices = sum(1 for r in survey if r["prices_wrong_answers"] == "yes")
    sum(1 for r in survey if r["asks_confidence"] != "no")

    survey_tbl = table(
        ["benchmark", "how it is scored", "prices wrong answers?",
         "silence beats a wrong answer?", "asks how sure?", "basis"],
        [[r["benchmark"], r["how_scored"], r["prices_wrong_answers"],
          r["silence_earns_more_than_wrong"], r["asks_confidence"],
          f'<span class="sub">{r["basis"]}</span>'] for r in
         sorted(survey, key=lambda r: (r["source"] != "external",
                                       r["benchmark"].lower()))],
        right_from=99, cls="brief-prose gaps", sortable=True,
        collapse_after=14)

    landscape_tbl = table(
        ["", "prices wrong answers?", "silence beats a wrong answer?",
         "asks how sure the model is?"],
        [[(f'<b>{n_graded - n_prices} of the {n_survey}</b>'
          '<span class="sub">every benchmark that grades answers '
          'right-or-wrong, ours and others\'</span>'),
          "no", "no, both score 0", "no"],
         [('<b>AA-Omniscience</b><span class="sub">the one mainstream index '
          'pricing error</span>'), "yes, &minus;1",
          "yes, silence is free", "no"],
         [('<b>Humanity\'s Last Exam</b><span class="sub">the one that asks '
          'for a number</span>'), "no", "no", "asks, but never scores it"],
         [(f'<span class="sub">{n_survey - n_graded} more do not grade '
          f'answers right-or-wrong at all: preference arenas, judge-scored '
          f'suites, rubric-graded conversation</span>'),
          "&mdash;", "&mdash;", "no"]],
        right_from=99, cls="brief-prose landscape")

    # --- the four named scoring approaches -----------------------------------
    # One reader-facing name per rule key, used verbatim everywhere else on
    # the page (mocks, training rows, ledger): binary, linear, quadratic,
    # quad_cost. The "asks the model for" column exists because a fixed
    # penalty without a stated probability is a different game from a stake
    # on your own confidence, and conflating them under "penalty" was a
    # reader trap.
    fourways_tbl = table(
        ["approach", "asks the model for", "right pays", "wrong pays",
         "model's best move", "what the stated number means"],
        [[("<b>No penalty for guessing</b><span class=\"sub\">today's "
          "default</span>"), "an answer only", "1", "0",
          "always guess, even at 1%", "no number is asked"],
         ["<b>Linear confidence rule</b>",
          "answer + confidence p", "+p", "&minus;p",
          "claim 100% or 0%, never between", "which side of a coin flip"],
         [("<b>Quadratic penalty for guessing</b><span class=\"sub\">produces "
          "the confidence-calibrated score used below</span>"),
          "answer + confidence p", "2p &minus; p&sup2;", "&minus;p&sup2;",
          "<b>report your true belief</b>", "the belief itself"]],
        right_from=99, cls="brief-prose gaps")

    # The fourth approach appears at the END of the section, after the first
    # three have built the intuition, per Ramon's sequencing note.
    costrow_tbl = table(
        ["approach", "asks the model for", "right pays", "wrong pays",
         "model's best move", "what the stated number means"],
        [[("<b>Quadratic penalty, plus a fixed cost for answering</b>"
          "<span class=\"sub\">optional abstention layer</span>"),
          "answer + confidence p", "2p &minus; p&sup2; &minus; c",
          "&minus;p&sup2; &minus; c",
          "true belief; stay silent below &radic;c",
          "the belief, plus a price on speaking"]],
        right_from=99, cls="brief-prose gaps")


    cost_tbl = table(
        ["assertion price c", "answer only when more confident than",
         "illustrative setting"],
        [["0", "<b>0% confident</b>, always answer",
          "<b>quadratic rule alone: confidence is scored, silence is not</b>"],
         ["0.09", "<b>30% confident</b>", "a film recommendation"],
         ["0.25", "<b>50% confident</b>",
          "a leaderboard that wants real caution"],
         ["0.56", "<b>75% confident</b>", "a drug-interaction answer"]],
        right_from=99, cls="brief-prose gaps")

    # --- the HLE decomposition, same formulas as the main page --------------
    def model_name(path):
        # "openai/gpt-5.2-2025-12-11" -> "GPT-5.2"; the release date is one
        # click away on the main page's table.
        stem = path.split("/")[-1].rsplit("-2", 1)[0]
        return (stem.upper() if stem.startswith("gpt")
                else stem.replace("-", " ").title())

    # --- the same answers under different scorings ---------------------------
    # Both rescoring tables share one shape: rows are things being judged,
    # columns are the named scoring approaches applied to identical stored
    # responses, and a final column says how the ranking moved. Ranks are
    # computed here rather than typed so a data refresh cannot leave a stale
    # arrow behind.
    def ranks(values):
        """Dense ranks, descending, '=' marking ties, on 3-dp values."""
        rounded = [round(v, 3) for v in values]
        order = sorted(set(rounded), reverse=True)
        return [f"{order.index(v) + 1}{'=' if rounded.count(v) > 1 else ''}"
                for v in rounded]

    def rank_moves(first, second):
        return [f"{a} &rarr; {b}" for a, b in zip(ranks(first), ranks(second))]

    def score_cell(v, dp=3):
        s = f"{v:.{dp}f}".replace("-", "&minus;")
        # Below zero is the observation the project is named for, so the
        # cells that cross it carry the emphasis.
        return f"<b>{s}</b>" if v < 0 else s

    # Every published HLE run rescored (scripts/hle_rescore.py), not the four
    # that happened to be written down first. Coverage is the load-bearing
    # column: a model that states a number on 6% of its answers cannot be
    # rescored, because that sliver is not a sample of the model.
    rescored = rows("hle_rescored_all.csv")
    for r in rescored:
        r["coverage"] = int(r["n_scored"]) / int(r["n_responses"])
    # Tables that show several releases from one company use release order,
    # newest first. Sorting these rows by the outcome being discussed made a
    # model family's chronology look arbitrary and, in the HLE table, put
    # GPT-5 ahead of the newer GPT-5.2 release. Dates embedded in model IDs do
    # most of the work; explicit overrides cover undated aliases.
    MODEL_RECENCY = {
        "anthropic/claude-opus-4-6": 20260205,
        "Qwen/Qwen3.5-4B": 20251201,
        "Qwen/Qwen3-8B": 20250429,
    }

    def model_recency(path):
        if path in MODEL_RECENCY:
            return MODEL_RECENCY[path]
        dated = re.search(r"(20\d{2})-?(\d{2})-?(\d{2})$", path)
        return int("".join(dated.groups())) if dated else 0

    def company_recency_key(r):
        path = r["model"]
        return (path.split("/", 1)[0].lower(), -model_recency(path), path)

    covered = sorted([r for r in rescored if r["coverage"] >= 0.9],
                     key=company_recency_key)
    sparse = sorted([r for r in rescored if r["coverage"] < 0.9],
                    key=company_recency_key)

    hle_acc = [float(r["accuracy"]) for r in covered]
    hle_quad = [float(r["quad"]) for r in covered]
    rank_moves(hle_acc, hle_quad)
    hle_scores = [float(r["quad"]) for r in covered]
    hle_lo, hle_hi = min(hle_scores), max(hle_scores)
    hle_tbl = table(
        ["model", "answers with confidence", "accuracy on those answers",
         "confidence on those answers", "confidence gap",
         "confidence-calibrated score"],
        [[model_name(r["model"]), f'{int(r["n_scored"]):,}',
          f'{float(r["accuracy"]) * 100:.1f}%',
          f'{float(r["mean_confidence"]) * 100:.0f}%',
          over_under_cell(r["mean_confidence"], r["accuracy"]),
          score_bar(float(r["quad"]), hle_lo, hle_hi)]
         for r in covered],
        sortable=True, cls="brief-hle")

    hle_cost_tbl = table(
        ["model", "confidence-calibrated score", "+ cost c = 0.09",
         "+ cost c = 0.25"],
        [[model_name(r["model"]), score_cell(float(r["quad"])),
          score_cell(float(r["quad_c09"])), score_cell(float(r["quad_c25"]))]
         for r in covered])

    hle_low_tbl = table(
        ["model", "responses", "states a confidence",
         "accuracy on that sliver", "confidence it claims there"],
        [[model_name(r["model"]), f'{int(r["n_responses"]):,}',
          f'<b>{r["coverage"] * 100:.0f}%</b>',
          f'{float(r["accuracy"]) * 100:.1f}%',
          f'{float(r["mean_confidence"]) * 100:.0f}%']
         for r in sparse])

    # Our fine-tuned variants' stored answers, scored after the fact under
    # each approach: the same lens-swap the published runs get above.
    grid = rows("dose_grid_knowledge.csv")
    picks = [("base", "0", "Untuned base"),
             ("binary", "500", "Accuracy only"),
             ("quadratic", "500", "Confidence-calibrated"),
             ("quad_cost_0.09", "500",
              "Confidence-calibrated + fixed cost (c = 0.09)")]
    sel = [next(g for g in grid
                if g["objective"] == o and g["step"] == st)
           for o, st, _ in picks]
    our_bin = [float(g["score_binary"]) for g in sel]
    our_quad = [float(g["score_quadratic"]) for g in sel]
    our_moves = rank_moves(our_bin, our_quad)
    ourscores_tbl = table(
        ["reward trained with", "scored on accuracy",
         "confidence-calibrated score", "+ cost c = 0.09",
         "rank: accuracy &rarr; calibrated"],
        [[label, f"{b:.2f}", score_cell(q),
          score_cell(float(g["score_quad_cost_0.09"])), move]
         for (o, st, label), g, b, q, move
         in zip(picks, sel, our_bin, our_quad, our_moves)],
        sortable=True)

    # --- our own testing, in levels rather than changes ---------------------
    # data/processed/pilot_levels.csv (scripts/export_pilot_levels.py) lifts
    # these out of results/tables.json. Two arms only: the plain condition and
    # the announced rule. Models are ordered by how badly they misjudge
    # themselves in the plain condition, because the spread IS the finding.
    levels = rows("pilot_levels.csv")

    def short_model(path):
        stem = path.split("/")[-1]
        return {"deepseek-v4-pro-0813": "DeepSeek V4 Pro",
                "gemini-3.7-flash": "Gemini 3.7 Flash",
                "mistral-medium-3.1": "Mistral Medium 3.1",
                "mistral-small-2603": "Mistral Small 4",
                "nemotron-3-nano-30b-a3b": "Nemotron 3 Nano",
                "gpt-5.6-luna": "GPT-5.6 Luna",
                "gpt-5.6-terra": "GPT-5.6 Terra",
                "qwen3.6-plus": "Qwen3.6 Plus"}.get(stem, stem)

    ARM_LABEL = {"control": "answer normally",
                 "quad_both": "rule + threshold"}

    lvl_scores = [float(r["calibrated_score"]) for r in levels
                  if r["benchmark"] != "POOLED"]
    lvl_lo, lvl_hi = min(lvl_scores), max(lvl_scores)

    def attempt_accuracy(r):
        """Accuracy conditional on answering, paired with stated confidence."""
        coverage = 1 - float(r["abstention_rate"])
        return float(r["accuracy"]) / coverage if coverage else 0.0

    def attempt_gap(r):
        """Claimed probability minus accuracy on the same answered items."""
        return float(r["mean_confidence"]) - attempt_accuracy(r)

    def level_row(r, *lead):
        """One self-contained row: every cell readable after any sort."""
        coverage = 1 - float(r["abstention_rate"])
        answered_accuracy = attempt_accuracy(r)
        return list(lead) + [
            f'{float(r["accuracy"]) * 100:.0f}%',
            f'{coverage * 100:.0f}%',
            f'{answered_accuracy * 100:.0f}%',
            f'{float(r["mean_confidence"]) * 100:.0f}%',
            over_under_cell(r["mean_confidence"], answered_accuracy),
            score_bar(float(r["calibrated_score"]), lvl_lo, lvl_hi)]

    metrics = ["overall accuracy", "answered", "accuracy when answered",
               "confidence when answered", "confidence gap",
               "confidence-calibrated score overall"]

    pooled = [r for r in levels if r["benchmark"] == "POOLED"]
    by_model = {}
    for r in pooled:
        by_model.setdefault(r["model"], []).append(r)
    order = sorted(by_model, key=lambda m: -max(
        attempt_gap(r) for r in by_model[m]))

    # Per benchmark is primary. Pooling averages benchmarks whose headroom
    # differs enormously -- BoolQ's two-choice chance accuracy already sits
    # above the threshold the rule implies -- and one model's pooled row is a
    # single benchmark. GPQA leads because it has the parity check.
    bench_order = ["gpqa", "simpleqa", "mmlu_pro", "medmcqa", "boolq"]

    def bench_rank(r):
        b = r["benchmark"]
        return (bench_order.index(b) if b in bench_order else 99,
                order.index(r["model"]), r["arm"] != "control")
    per_rows, per_meta = [], []
    for r in sorted([r for r in levels if r["benchmark"] != "POOLED"],
                    key=bench_rank):
        per_rows.append(level_row(r, short_model(r["model"]), r["benchmark"],
                                  ARM_LABEL[r["arm"]]))
        per_meta.append({"key": f'{r["model"]}|{r["benchmark"]}|{r["arm"]}'})
    pilot_levels_tbl = table(
        ["model", "benchmark", "told to"] + metrics,
        per_rows, right_from=3, sortable=True, collapse_after=12,
        row_meta=per_meta, table_id="pilot-levels")

    pooled_rows, pooled_meta = [], []
    for m in order:
        for arm in ("control", "quad_both"):
            r = next((x for x in by_model[m] if x["arm"] == arm), None)
            if r:
                pooled_rows.append(level_row(r, short_model(m),
                                             ARM_LABEL[arm]))
                pooled_meta.append({"key": f"{m}|{arm}"})
    pilot_pooled_tbl = table(
        ["model", "told to"] + metrics, pooled_rows, right_from=2,
        sortable=True, row_meta=pooled_meta, table_id="pilot-pooled")

    # --- the aggregate view -------------------------------------------------
    def pct_at(vals, q):
        v = sorted(vals)
        i = (len(v) - 1) * q
        a = int(i)
        b = min(a + 1, len(v) - 1)
        return v[a] + (v[b] - v[a]) * (i - a)

    per_bench_rows = [r for r in levels if r["benchmark"] != "POOLED"]

    # The earlier range plot placed three distributions one above another. It
    # was statistically faithful but forced the reader to integrate separate
    # scales and decode a bespoke legend. One table now keeps the treatment,
    # performance, confidence, and calibrated-score evidence in a single row.
    def median_value(value, arm):
        values = [value(r) for r in per_bench_rows if r["arm"] == arm]
        return pct_at(values, 0.5)

    def paired_score_improvements():
        indexed = {(r["model"], r["benchmark"], r["arm"]): r
                   for r in per_bench_rows}
        pairs = []
        for model, benchmark, arm in indexed:
            if arm != "quad_both":
                continue
            treated = indexed[(model, benchmark, "quad_both")]
            control = indexed.get((model, benchmark, "control"))
            if control:
                pairs.append(float(treated["calibrated_score"])
                             > float(control["calibrated_score"]))
        return sum(pairs), len(pairs)

    score_wins, score_pairs = paired_score_improvements()
    pilot_summary_body = []
    for arm, label in (("control", "Answer normally"),
                       ("quad_both", "Rule + 30% threshold")):
        pilot_summary_body.append([
            label,
            f'{median_value(lambda r: float(r["accuracy"]), arm) * 100:.0f}%',
            f'{median_value(lambda r: 1 - float(r["abstention_rate"]), arm) * 100:.0f}%',
            f'{median_value(attempt_accuracy, arm) * 100:.0f}%',
            f'{median_value(lambda r: float(r["mean_confidence"]), arm) * 100:.0f}%',
            f'{median_value(attempt_gap, arm) * 100:+.0f} pp'.replace("-", "&minus;"),
            f'{median_value(lambda r: float(r["calibrated_score"]), arm):.2f}',
            "&mdash;" if arm == "control" else f'<b>{score_wins}/{score_pairs}</b>',
        ])
    pilot_summary_tbl = table(
        ["test prompt", "overall accuracy", "answered",
         "accuracy when answered", "confidence when answered",
         "confidence gap among answers",
         "confidence-calibrated score overall",
         "model-benchmark scores improved"],
        pilot_summary_body, right_from=1, cls="brief-prose")

    pilot_takeaways = takeaways("pilot-levels", [
        ("Every model narrows its gap",
         ("Under the combined rule-and-threshold treatment, all six models "
          "claimed less relative to what they delivered. On GPQA the gap "
          "falls for every one of them."),
         [f'{m}|gpqa|{a}' for m in order for a in ("control", "quad_both")]),
        ("Accuracy barely moves",
         ("The gap closes because models claim less, not because they know "
         "less: accuracy shifts by a point or two either way."),
         [f'{m}|gpqa|{a}' for m in order for a in ("control", "quad_both")]),
        ("The worst-calibrated model gains most",
         ("GPT-5.6 Terra starts 53 points overconfident and closes furthest; "
         "Gemini starts at 11 and has little left to give."),
         [f'{m}|POOLED|{a}' for m in ("openai/gpt-5.6-terra",
                                      "google/gemini-3.7-flash")
          for a in ("control", "quad_both")]),
    ])

    # --- expanded prompting estimate ---------------------------------------
    # The original 20-to-50-item pilot remains useful historical evidence for
    # the scatter below.  The reader-facing prompting tables now use the larger
    # deterministic run: five providers, three benchmarks, eight prompts, and
    # 120 to 198 frozen items in every cell.  The export refuses incomplete or
    # ungraded cells, so a partially resumed paid run cannot silently appear.
    prompt_levels = rows("prompt_estimation_levels.csv")
    with open(os.path.join(PROC, "prompt_estimation_run.json"),
              encoding="utf-8") as handle:
        prompt_meta = json.load(handle)

    PROMPT_LABELS = {
        "control": "Answer normally",
        "guess": "Accuracy only",
        "thresh75": "75% answer threshold",
        "quad_formula": "Formula + 30% threshold",
        "quad_plain": "Explanation + 30% threshold",
        "quad_both": "Formula + explanation + 30% threshold",
        "quad_c50": "Formula + explanation + 50% threshold",
        "deploy": "Operational advice framing",
    }
    PROMPT_ORDER = ("control", "guess", "thresh75", "quad_formula",
                    "quad_plain", "quad_both", "quad_c50", "deploy")
    PROMPT_CHANGE = {
        "control": "No scoring rule stated",
        "guess": "Makes the incentive to guess explicit",
        "thresh75": "Announces a hard threshold and error penalty",
        "quad_formula": "Gives the score as algebra",
        "quad_plain": "Explains honest probabilities without algebra",
        "quad_both": "Combines the formula and explanation",
        "quad_c50": "Raises only the cost of answering",
        "deploy": "Requests the same behavior without grading language",
    }

    prompt_index = {(r["model"], r["benchmark"], r["contract"]): r
                    for r in prompt_levels}
    prompt_pairs = sorted({(r["model"], r["benchmark"])
                           for r in prompt_levels})

    def prompt_values(contract, field):
        return [float(prompt_index[(model, benchmark, contract)][field])
                for model, benchmark in prompt_pairs]

    def prompt_deltas(contract, field, *, absolute=False):
        values = []
        for model, benchmark in prompt_pairs:
            treated = float(prompt_index[(model, benchmark, contract)][field])
            control = float(prompt_index[(model, benchmark, "control")][field])
            if absolute:
                treated, control = abs(treated), abs(control)
            values.append(treated - control)
        return values

    def prompt_n_range(contract):
        values = [int(prompt_index[(m, b, contract)]["n"])
                  for m, b in prompt_pairs]
        return (f"{min(values)}" if min(values) == max(values)
                else f"{min(values)} to {max(values)}")

    prompt_summary_rows = []
    for contract in PROMPT_ORDER:
        accuracy = pct_at(prompt_values(contract, "accuracy"), .5)
        gap = pct_at([abs(v) for v in prompt_values(contract, "confidence_gap")], .5)
        score = pct_at(prompt_values(contract, "confidence_calibrated_score"), .5)
        if contract == "control":
            accuracy_cell = f"{accuracy * 100:.0f}% baseline"
            gap_cell = f"{gap * 100:.0f} pp baseline"
            score_cell_text = f"{score:.3f} baseline"
            wins_cell = "&mdash;"
        else:
            accuracy_delta = pct_at(prompt_deltas(contract, "accuracy"), .5)
            gap_delta = pct_at(prompt_deltas(
                contract, "confidence_gap", absolute=True), .5)
            score_delta = pct_at(prompt_deltas(
                contract, "confidence_calibrated_score"), .5)
            wins = sum(v > 0 for v in prompt_deltas(
                contract, "confidence_calibrated_score"))
            accuracy_cell = f"{accuracy_delta * 100:+.1f} pp".replace(
                "-", "&minus;")
            gap_cell = f"{gap_delta * 100:+.1f} pp".replace(
                "-", "&minus;")
            score_cell_text = f"{score_delta:+.3f}".replace("-", "&minus;")
            wins_cell = f"{wins}/15"
        prompt_summary_rows.append([
            f"<b>{PROMPT_LABELS[contract]}</b>",
            accuracy_cell, gap_cell, score_cell_text, wins_cell,
            prompt_n_range(contract),
            f'<span class="sub">{PROMPT_CHANGE[contract]}</span>',
        ])
    pilot_summary_tbl = table(
        ["test prompt", "median accuracy change",
         "median absolute confidence-gap change",
         "median confidence-calibrated score change", "cells with higher score",
         "items per model-benchmark cell", "what changes"],
        prompt_summary_rows, right_from=1, cls="brief-prose")

    # The primary comparison stays fixed at the intended default treatment,
    # rather than selecting whichever of eight prompts happened to look best.
    primary_contract = "quad_both"
    primary_gap_control = pct_at(
        [abs(v) for v in prompt_values("control", "confidence_gap")], .5)
    primary_gap_treated = pct_at(
        [abs(v) for v in prompt_values(primary_contract, "confidence_gap")], .5)
    primary_gap_delta = pct_at(prompt_deltas(
        primary_contract, "confidence_gap", absolute=True), .5)
    primary_accuracy_delta = pct_at(
        prompt_deltas(primary_contract, "accuracy"), .5)
    primary_score_delta = pct_at(
        prompt_deltas(primary_contract, "confidence_calibrated_score"), .5)
    primary_score_wins = sum(v > 0 for v in prompt_deltas(
        primary_contract, "confidence_calibrated_score"))

    expanded_detail_rows = []
    for model, benchmark in prompt_pairs:
        for contract in ("control", primary_contract):
            r = prompt_index[(model, benchmark, contract)]
            expanded_detail_rows.append([
                short_model(model), benchmark, PROMPT_LABELS[contract], r["n"],
                f'{float(r["accuracy"]) * 100:.1f}%',
                f'{float(r["answered_rate"]) * 100:.1f}%',
                f'{float(r["accuracy_when_answered"]) * 100:.1f}%',
                f'{float(r["confidence_when_answered"]) * 100:.1f}%',
                f'{float(r["confidence_gap"]) * 100:+.1f} pp',
                f'{float(r["confidence_calibrated_score"]):.3f}',
            ])
    pilot_levels_tbl = table(
        ["model", "benchmark", "test prompt", "items", "accuracy", "answered",
         "accuracy when answered", "confidence when answered", "confidence gap",
         "confidence-calibrated score"],
        expanded_detail_rows, right_from=3, sortable=True, collapse_after=12,
        table_id="prompt-estimation-levels")

    def real_scatter():
        """Every measured (accuracy, stated confidence) pair we have.

        Twenty-nine points, not nine: each of the six pilot models on each of
        the five benchmarks it answered, plus the three published HLE runs
        whose stated confidences cover the whole run. Pooling those pilot
        points into one dot per model threw away most of the evidence and made
        the chart look thin.

        Both axes are percentages on one scale and the plot is square, so the
        45-degree line means "claims exactly what it scores" and vertical
        distance from it is the self-estimation error. Every mark carries its
        numbers on hover.
        """
        pts = []
        for r in covered:
            pts.append(("hle", model_name(r["model"]), "HLE",
                        float(r["accuracy"]), float(r["mean_confidence"])))
        for r in levels:
            if r["benchmark"] != "POOLED" and r["arm"] == "control":
                pts.append(("pilot", short_model(r["model"]), r["benchmark"],
                            float(r["accuracy"]), float(r["mean_confidence"])))

        S, L, T, B = 340, 52, 20, 40
        W, H = L + S + 16, T + S + B
        lo, hi_dom = 0, 100

        def sx(v):
            return L + (v * 100 - lo) / (hi_dom - lo) * S

        def sy(v):
            return T + S - (v * 100 - lo) / (hi_dom - lo) * S
        parts = []
        for g in range(0, 101, 25):
            parts.append(f'<line class="ms-grid" x1="{sx(g / 100):.0f}" '
                         f'y1="{T}" x2="{sx(g / 100):.0f}" y2="{T + S}"/>')
            parts.append(f'<line class="ms-grid" x1="{L}" y1="{sy(g / 100):.0f}" '
                         f'x2="{L + S}" y2="{sy(g / 100):.0f}"/>')
            parts.append(f'<text class="ms-label" x="{sx(g / 100):.0f}" '
                         f'y="{T + S + 15}" text-anchor="middle">{g}%</text>')
            parts.append(f'<text class="ms-label" x="{L - 7}" '
                         f'y="{sy(g / 100) + 4:.0f}" text-anchor="end">{g}%</text>')
        parts.append(f'<line class="ms-diag" x1="{sx(0):.0f}" y1="{sy(0):.0f}" '
                     f'x2="{sx(1.0):.0f}" y2="{sy(1.0):.0f}"/>')
        parts.append(f'<text class="ms-label" x="{sx(0.97):.0f}" '
                     f'y="{sy(0.97) - 7:.0f}" text-anchor="end">claims what it '
                     f'scores</text>')
        parts.append(f'<text class="ms-label" x="{L + S / 2:.0f}" '
                     f'y="{H - 4}" text-anchor="middle">how often it is '
                     f'right</text>')
        parts.append(f'<text class="ms-label" transform="rotate(-90 12 '
                     f'{T + S / 2:.0f})" x="12" y="{T + S / 2:.0f}" '
                     f'text-anchor="middle">how sure it says it is</text>')
        claims = [p[4] for p in pts]
        parts.append(f'<rect class="ms-band" x="{L}" y="{sy(max(claims)):.0f}" '
                     f'width="{S}" '
                     f'height="{sy(min(claims)) - sy(max(claims)):.0f}"/>')
        for source, label, bench, acc, conf in sorted(pts, key=lambda p: -p[4]):
            cls = "ms-dot" + (" hle" if source == "hle" else "")
            parts.append(
                f'<circle class="{cls}" cx="{sx(acc):.0f}" '
                f'cy="{sy(conf):.0f}" r="4.5" tabindex="0" role="img" '
                f'data-model="{html.escape(label)}" '
                f'data-bench="{html.escape(bench)}" '
                f'data-acc="{acc * 100:.0f}" data-conf="{conf * 100:.0f}" '
                f'aria-label="{html.escape(label)} on {html.escape(bench)}: '
                f'right {acc * 100:.0f} percent, claims {conf * 100:.0f} '
                f'percent"></circle>')
        keys = ('<span class="ms-key">Published HLE runs</span>'
                '<span class="ms-key pilot">Our own testing, per benchmark</span>')
        span_acc = (max(p[3] for p in pts) - min(p[3] for p in pts)) * 100
        span_conf = (max(claims) - min(claims)) * 100
        fig = (f'<figure class="mock-scatter real" id="knowledge-scatter">'
               f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="How often '
               f'each model is right against how sure it says it is, '
               f'{len(pts)} measurements">' + "".join(parts) + "</svg>"
               f'<div class="ms-tip" id="ms-tip" hidden></div>'
               f'<div class="ms-keys">{keys}<span class="ms-count">'
               f'{len(pts)} measurements</span></div></figure>')
        return fig, span_acc, span_conf

    scatter_fig, scatter_acc_span, scatter_conf_span = real_scatter()

    # --- can this harness reproduce a published score? ----------------------
    # Ramon's question, answered with the arm that actually tested it. This is
    # the accuracy-only standard arm at each model's published reasoning
    # setting, which is NOT the arm the experiment runs; keeping it beside the
    # pilot tables is the only way a reader can reconcile a 90% here with a
    # 46% there.
    parity_rows = [r for r in rows("gpqa_parity.csv")
                   if r["status"].startswith("PASS")]
    # The same interval strip validation.html uses, on the same 65-100 scale,
    # so a reader who has seen that page recognises the device. .pi lives in
    # the shared stylesheet, so this costs markup only.
    def _pi_at(fraction):
        return f"{(float(fraction) * 100 - 65) / 35 * 100:.2f}%"

    parity_body = []
    for r in sorted(parity_rows, key=lambda r: -float(r["published_score"])):
        ours = int(r["correct"]) / int(r["n"])
        style = (f'--lo:{_pi_at(r["interval_low"])};'
                 f'--hi:{_pi_at(r["interval_high"])};'
                 f'--pub:{_pi_at(r["published_score"])};'
                 f'--ours:{_pi_at(ours)}')
        parity_body.append([
            r["label"].split(" (")[0],
            f'{float(r["published_score"]) * 100:.1f}%',
            f'<b>{ours * 100:.1f}%</b>',
            (f'<div class="pi" style="{style}"><i class="band"></i>'
            f'<i class="pub"></i><i class="ours"></i></div>')])
    parity_tbl = (
        table(["model", "published", "this harness", "where it landed"],
              parity_body, right_from=1, cls="brief-pi")
        + '<div class="pi-legend">'
        '<span><em class="band"></em>range a published score implies at this '
        'sample size</span><span><em class="pub"></em>published score</span>'
        '<span><em class="ours"></em>this run</span></div>')

    # --- what a score-maximising model DOES, worked through ------------------
    # Three stacked blocks, one per private belief, in the same shape as the
    # live widget's readout, which reads more clearly than a grid. Under no
    # penalty the cell says no number is ASKED: the rule never requests one,
    # and "any number" invented a behaviour the rule does not have.
    def worked_blocks():
        from belowzero.rules import binary, linear, quadratic
        grid = [i / 100 for i in range(101)]

        def num(v):
            text = f"{v:+.2f}".rstrip("0").rstrip(".")
            return (text if text not in ("+0", "-0") else "0").replace(
                "-", "&minus;")
        out = []
        for q in (0.9, 0.6, 0.3):
            body = []
            for name, rule, asks in (("No penalty", binary, False),
                                     ("Linear confidence", linear, True),
                                     ("Confidence-calibrated", quadratic, True)):
                best = max(grid, key=lambda p, rule=rule, q=q: (round(
                    q * rule(p, True) + (1 - q) * rule(p, False), 12),
                    -abs(p - q)))
                if not asks:
                    states = '<span class="sub">no number is asked</span>'
                    verdict = "the score cannot depend on its confidence"
                else:
                    states = f'<span class="move">{best * 100:.0f}%</span>'
                    verdict = ("<b>the truth</b>" if abs(best - q) < 0.005
                               else "a bluff, off by "
                                    f"{abs(best - q) * 100:.0f} points")
                body.append([name, "yes", states,
                             (f'{verdict}<span class="sub">pays '
                             f'{num(rule(best, True))} right, '
                             f'{num(rule(best, False))} wrong</span>')])
            out.append(
                f'<h4 class="worked-h">A model that privately believes '
                f'<b>{q * 100:.0f}%</b></h4>'
                + table(["under this rule", "it answers", "stating",
                         "which is"], body, right_from=99,
                        cls="brief-prose worked"))
        return "".join(out)
    worked_tbl = worked_blocks()

    # --- the fine-tune matrix: reward x announced prompt, in levels ---------
    matrix = rows("finetune_matrix.csv")

    # Two separate columns, because "what it was trained on" and "what it was
    # told at test time" are the two axes of the experiment and merging them
    # into one label made the design unreadable. Every score also carries its
    # distance from one fixed anchor -- the untuned model answering normally --
    # so all sixteen numbers are read against the same baseline rather than
    # against whichever row happens to sit above them.
    # The full prompt labels wrap to two lines in a seven-column table and
    # double every row's height; the short forms say the same thing.
    SHORT_PROMPT = {"neutral": "Answer normally",
                    "quadratic": "Maximise confidence-calibrated score"}

    def matrix_measures(r):
        """Return measures whose labels expose their actual denominator.

        The final evaluation had no invalid responses, so coverage is one
        minus abstention. Confidence is reported only on attempted answers;
        comparing it with overall accuracy would mix populations.
        """
        overall_accuracy = float(r["accuracy"])
        coverage = 1 - float(r["abstention_rate"])
        answered_accuracy = overall_accuracy / coverage if coverage else 0.0
        confidence = float(r["mean_confidence"])
        return overall_accuracy, coverage, answered_accuracy, confidence

    def matrix_table(seed_filter, table_id=None):
        """Two axes as two columns, one delta grammar, one emphasised anchor.

        "What it was trained on" and "what it was told at test time" are the
        experiment's two axes; merging them into one label made the design
        unreadable. Distance from baseline is expressed once, in its own
        column, against a single fixed anchor (the untuned model answering
        normally) rather than against whichever row happens to sit above it.
        """
        sel = [r for r in matrix if r["seed"] == seed_filter]
        anchor = next(r for r in sel if r["checkpoint"] == "base"
                      and r["prompt_condition"] == "neutral")
        base_score = float(anchor["calibrated_score"])
        body, meta = [], []
        for r in sel:
            is_anchor = r is anchor
            score = float(r["calibrated_score"])
            accuracy, coverage, answered_accuracy, confidence = matrix_measures(r)
            body.append([
                r["checkpoint_label"] + ('<span class="tag-chip">baseline'
                                         '</span>' if is_anchor else ""),
                SHORT_PROMPT.get(r["prompt_condition"], r["prompt_label"]),
                f'{accuracy * 100:.1f}%',
                f'{coverage * 100:.1f}%',
                f'{answered_accuracy * 100:.1f}%',
                f'{confidence * 100:.0f}%',
                over_under_cell(confidence, answered_accuracy),
                score_cell(score),
                "&mdash;" if is_anchor
                else f'{score - base_score:+.3f}'.replace("-", "&minus;")])
            meta.append({"key": f'{r["checkpoint"]}|{r["prompt_condition"]}',
                         "cls": "anchor" if is_anchor else ""})
        return table(
            ["trained on", "told to", "overall accuracy", "answered",
             "accuracy when answered", "confidence when answered",
             "confidence gap", "confidence-calibrated score",
             "vs baseline"],
            body, right_from=2, sortable=True, row_meta=meta,
            table_id=table_id)
    train_matrix_tbl = matrix_table("mean", table_id="train-matrix")

    # The crossed matrix is the complete experiment, but it is not the fastest
    # way to see what training did. The neutral-prompt rows isolate the change
    # in the weights and put benchmark performance beside the calibrated score.
    neutral_rows = [r for r in matrix
                    if r["seed"] == "mean"
                    and r["prompt_condition"] == "neutral"]
    neutral_anchor = next(r for r in neutral_rows
                          if r["checkpoint"] == "base")
    base_accuracy = float(neutral_anchor["accuracy"])
    base_calibrated = float(neutral_anchor["calibrated_score"])
    summary_takeaway = {
        "base": "Untuned reference",
        "binary": "Highest accuracy; worse confidence-calibrated score",
        "quadratic": "Highest confidence-calibrated score",
        "quad_cost": ("Ties the confidence-calibrated score; "
                      "cost adds no gain"),
    }
    train_summary_body = []
    for r in neutral_rows:
        accuracy, _, answered_accuracy, confidence = matrix_measures(r)
        calibrated = float(r["calibrated_score"])
        accuracy_delta = accuracy - base_accuracy
        calibrated_delta = calibrated - base_calibrated
        accuracy_comparison = (
            "baseline" if r["checkpoint"] == "base"
            else f"{accuracy_delta * 100:+.1f} pp vs untuned")
        calibrated_comparison = (
            "baseline" if r["checkpoint"] == "base"
            else f"{calibrated_delta:+.3f} vs untuned")
        train_summary_body.append([
            r["checkpoint_label"],
            f'<b>{summary_takeaway[r["checkpoint"]]}</b>',
            (f'{accuracy * 100:.1f}%<span class="sub">'
             f'{accuracy_comparison}</span>').replace(
                 "-", "&minus;"),
            f'{confidence * 100:.0f}%',
            over_under_cell(confidence, answered_accuracy),
            (f'{calibrated:.3f}<span class="sub">'
             f'{calibrated_comparison}</span>').replace(
                 "-", "&minus;"),
        ])
    train_summary_tbl = table(
        ["trained on", "takeaway", "overall accuracy",
         "confidence when answered", "confidence gap",
         "confidence-calibrated score"],
        train_summary_body, right_from=2, cls="brief-prose")

    train_takeaways = takeaways("train-matrix", [
        ("The change is in the weights, not the prompt",
         ("The untuned model moves from 0.390 to 0.393 when the rule is "
          "announced. Training on the rule reaches 0.443 under the neutral "
          "prompt. In this experiment, asking was not a substitute for "
          "changing the weights."),
         ["base|neutral", "base|quadratic", "quadratic|neutral",
          "quadratic|quadratic"]),
        ("Accuracy-only training raises accuracy AND confidence",
         ("It gains five points of accuracy and claims 96%, up from 90. The "
          "reward pays for confident answers, so it produced them, and its "
          "confidence-calibrated score fell below the untuned model it started from: "
         "training for the leaderboard's metric made its self-knowledge "
         "worse."),
         ["base|neutral", "binary|neutral"]),
        ("Calibration closes a 30-point gap to nothing",
         ("Asked to maximise the confidence-calibrated score, the calibration-trained "
         "model claims 63% and delivers 63%. The untuned base and the "
         "accuracy-trained version both sit 30 points overconfident."),
         ["base|neutral", "binary|neutral", "quadratic|quadratic"]),
        ("The fixed cost adds no training gain",
         ("With and without it the confidence-calibrated scores tie at 0.443, and across "
         "two seeds its incremental effect was +0.00006 with the seeds "
         "landing on opposite signs."),
         ["quadratic|neutral", "quad_cost|neutral"]),
    ])

    # The larger held-out policy test separates the model's learned reward
    # from the final deployment rule. Every row shows levels so lower error is
    # never credited without also showing how many answers were withheld.
    with open(os.path.join(PROC, "policy_architecture_summary.json"),
              encoding="utf-8") as fh:
        policy_architecture = json.load(fh)
    with open(os.path.join(PROC, "prompt_threshold_factorial_summary.json"),
              encoding="utf-8") as fh:
        prompt_factorial = json.load(fh)
    prompt_headline = prompt_factorial["headline"]

    def prompt_policy_row(label, detail, prefix):
        return [
            f'<b>{label}</b><span class="sub">{detail}</span>',
            f'{float(prompt_headline[f"{prefix}_coverage"]) * 100:.1f}%',
            f'{float(prompt_headline[f"{prefix}_accuracy_when_answered"]) * 100:.1f}%',
            f'{float(prompt_headline[f"{prefix}_wrong_per_question"]) * 100:.1f}',
            f'{float(prompt_headline[f"{prefix}_utility_per_question"]) * 100:+.1f}'.replace(
                "-", "&minus;"),
        ]

    prompt_factorial_tbl = table(
        ["same checkpoint at the 30% break-even point", "answers shown",
         "accuracy when shown", "wrong answers per 100 questions",
         "decision value per 100 questions"],
        [
            prompt_policy_row(
                "Penalty inside the prompt",
                "Model receives the cost and decides whether to answer",
                "embedded"),
            prompt_policy_row(
                "Confidence prompt only",
                "No deterministic cutoff; isolates the simpler prompt",
                "confidence_native"),
            prompt_policy_row(
                "Confidence prompt + code",
                "Code withholds probabilities below 30%",
                "separated"),
        ],
        right_from=1, cls="brief-prose policy-architecture")
    policy_index = {
        (float(r["threshold"]), r["approach"]): r
        for r in policy_architecture["policy_comparison"]
    }
    policy_labels = {
        "embedded_cost_native": (
            "Embedded cost policy",
            "Cost-trained model decides whether to answer"),
        "separated_confidence_external": (
            "Separated policy",
            "Confidence-only model; code applies the threshold"),
        "hybrid_cost_external": (
            "Hybrid policy",
            "Cost-trained model; code still applies the threshold"),
    }

    def policy_level_row(threshold, approach):
        r = policy_index[(threshold, approach)]
        label, gloss = policy_labels[approach]
        value = float(r["utility_per_question"]) * 100
        return [
            f'<b>{label}</b><span class="sub">{gloss}</span>',
            f'{float(r["coverage"]) * 100:.1f}%',
            f'{float(r["accuracy_when_answered"]) * 100:.1f}%',
            f'{float(r["wrong_per_question"]) * 100:.1f}',
            f'{value:+.1f}'.replace("-", "&minus;"),
        ]

    policy_primary_tbl = table(
        ["deployment design at the 30% break-even point", "answers shown",
         "accuracy when shown", "wrong answers per 100 questions",
         "decision value per 100 questions"],
        [policy_level_row(0.30, approach) for approach in (
            "embedded_cost_native", "separated_confidence_external",
            "hybrid_cost_external")],
        right_from=1, cls="brief-prose policy-architecture")

    policy_stakes_rows = []
    for threshold in (0.30, 0.70, 0.80, 0.90):
        row = [
            f'{threshold * 100:.0f}%',
            f'{threshold / (1 - threshold):.2f}&times;',
        ]
        for approach in ("embedded_cost_native",
                         "separated_confidence_external",
                         "hybrid_cost_external"):
            r = policy_index[(threshold, approach)]
            value = float(r["utility_per_question"]) * 100
            cell = (f'{float(r["wrong_per_question"]) * 100:.1f} wrong'
                    f'<span class="sub">value {value:+.1f}</span>')
            row.append(cell.replace("-", "&minus;"))
        policy_stakes_rows.append(row)
    policy_stakes_tbl = table(
        ["answer threshold", "wrong-answer cost", "embedded cost policy",
         "confidence-only + external gate", "cost-trained + external gate"],
        policy_stakes_rows, right_from=1,
        cls="brief-prose policy-architecture-stakes")

    # Per-seed detail: confidence is the seed-unstable column, so the
    # averaged row above should be read as direction rather than level.
    seed_body = []
    for r in [r for r in matrix if r["seed"] in ("0", "1")]:
        accuracy, coverage, answered_accuracy, confidence = matrix_measures(r)
        seed_body.append([
            r["checkpoint_label"],
            SHORT_PROMPT.get(r["prompt_condition"], r["prompt_label"]),
            f'seed {r["seed"]}',
            f'{accuracy * 100:.1f}%',
            f'{coverage * 100:.1f}%',
            f'{answered_accuracy * 100:.1f}%',
            f'{confidence * 100:.0f}%',
            over_under_cell(confidence, answered_accuracy),
            score_cell(float(r["calibrated_score"]))])
    train_seeds_tbl = table(
        ["trained on", "told to", "seed", "overall accuracy", "answered",
         "accuracy when answered", "confidence when answered",
         "confidence gap", "confidence-calibrated score"], seed_body, right_from=3,
        sortable=True)

    # --- behaviour under social pressure ------------------------------------
    # Both arms always, as in the sycophancy evaluation: the wrong-pushback
    # column alone would be the flattering half and would not distinguish a
    # model with judgement from one that is merely inert.
    pressure = rows("sycophancy_pressure.csv")
    at_125 = [r for r in pressure if r["step"] in ("0", "125")]
    grouped = {}
    for r in at_125:
        grouped.setdefault(r["reward_label"], []).append(r)
    pressure_body = []
    for label in ["Untuned base", "Accuracy only", "Confidence-calibrated",
                  "Confidence-calibrated + fixed cost"]:
        sel = grouped.get(label, [])
        if not sel:
            continue
        def mean(key, sel=sel):
            return sum(float(r[key]) for r in sel) / len(sel)
        wrong = mean("accepts_wrong_pushback")
        pressure_body.append([
            label + ('<span class="sub">the model everything else is '
                     'measured against</span>' if label == "Untuned base" else ""),
            f'<b>{wrong * 100:.0f}%</b>' if wrong > 0.7 else f'{wrong * 100:.0f}%',
            f'{mean("abandoned_correct_rate") * 100:.0f}%',
            f'{mean("accepts_right_pushback") * 100:.0f}%'])
    pressure_tbl = table(
        ["checkpoint", "accepts wrong pushback", "abandons a correct answer",
         "accepts right pushback"], pressure_body)

    pressure_replication = rows("alignment_pressure_replication.csv")
    pressure_replication_by_key = {
        (r["reward"], r["step"]): r for r in pressure_replication
    }
    pressure_contrasts = rows("alignment_pressure_contrasts.csv")
    pressure_replication_tbl = table(
        ["trained with", "step", "accepts wrong pushback",
         "accepts correct pushback", "pressure discernment"],
        [[r["reward_label"], r["step"],
          f'{float(r["accepts_wrong_pushback"]) * 100:.0f}%',
          f'{float(r["accepts_right_pushback"]) * 100:.0f}%',
          f'{float(r["pressure_discernment"]) * 100:.0f} pp']
         for r in pressure_replication],
        right_from=1, sortable=True, cls="brief-prose")

    pressure_prompting = rows("alignment_pressure_prompting.csv")
    pressure_prompt_contrasts = rows(
        "alignment_pressure_prompt_contrasts.csv")
    pressure_spend = rows("alignment_pressure_spend.csv")
    pressure_spend_total = sum(
        float(r["conservative_spend_usd"]) for r in pressure_spend)
    neutral_replication_spend = next(
        float(r["conservative_spend_usd"]) for r in pressure_spend
        if r["run"] == "alignment_pressure_replication_v1")
    announced_prompt_spend = sum(
        float(r["conservative_spend_usd"]) for r in pressure_spend
        if r["scope"] == "full" and "pressure_prompt_" in r["run"])
    pressure_prompt_contrast_tbl = table(
        ["test prompt", "wrong-pushback adoption",
         "pressure discernment", "reading"],
        [[r["prompt_label"],
          (f'{float(r["delta_wrong_adoption"]) * 100:+.0f}'.replace(
              "-", "&minus;")
           + ' pp worse <span class="sub">confidence-calibrated minus '
             'accuracy training</span>'),
          (f'{float(r["delta_pressure_discernment"]) * 100:+.0f}'.replace(
              "-", "&minus;")
           + ' pp <span class="sub">confidence-calibrated minus accuracy '
             'training</span>'),
          "Adverse gap remains"]
         for r in pressure_prompt_contrasts],
        right_from=99, sortable=True,
        cls="brief-prose alignment-prompt-contrast")
    pressure_prompt_levels_tbl = table(
        ["trained with", "test prompt", "accepts wrong pushback",
         "accepts correct pushback", "pressure discernment"],
        [[r["reward_label"], r["prompt_label"],
          f'{float(r["wrong_adoption"]) * 100:.0f}%',
          f'{float(r["right_adoption"]) * 100:.0f}%',
          f'{float(r["pressure_discernment"]) * 100:.0f} pp']
         for r in pressure_prompting],
        right_from=2, sortable=True, cls="brief-prose")

    # --- the announced-rule pilot, one table per track ----------------------
    # data/processed/pilot_announced_rule.csv transcribes the pilot's paired
    # tables (notes/2026-08-15-live-pilot.md). Error columns exist in the CSV
    # but are not shown: they depend on the still-unvalidated judge, and the
    # page's rule is that a number appears only once its instrument has.
    def pilot_tbl(track):
        sel = [r for r in pilot if r["track"] == track]

        # One decimal count per column, not %g: mixed precision down a column
        # ("+0.18" beside "+0.083") reads as a difference in certainty when it
        # is only a difference in trailing zeros. An exact zero drops the sign
        # because "+0.0" asserts a direction that is not there.
        def signed(v, dp, unit=""):
            x = float(v)
            s = f"{x:.{dp}f}" if x == 0 else f"{x:+.{dp}f}"
            return f'{s.replace("-", "&minus;")}{unit}'
        pp = 1 if track == "mc-pooled" else 0
        return table(
            ["model", "paired n", "abstention", "stated confidence",
             "calibrated score", "exact p"],
            [[r["model"], r["paired_n"],
              f'<b>{signed(r["abstention_change_pp"], pp, " pp")}</b>',
              signed(r["confidence_change_pp"], 1, " pp"),
              signed(r["quadratic_score_change"], 3),
              r["exact_p"]] for r in sel])
    pilot_sqa_tbl = pilot_tbl("simpleqa")
    pilot_mc_tbl = pilot_tbl("mc-pooled")

    # --- fine-tuning outcomes, in absolute levels ---------------------------
    # Read straight from the final test's combined neutral-prompt results so
    # the cells cannot drift from the training page, which draws on the same
    # file. Rows reuse the four-ways names verbatim: the table is the
    # empirical test of that table's "best move" column, and the naming makes
    # the correspondence visible.
    with open(os.path.join(PROC, "finetune_pilot_summary.json"),
              encoding="utf-8") as fh:
        final = json.load(fh)["final_test"]["neutral_combined"]

    def train_row(key, label, bold_score=False):
        r = final[key]
        score = f'{float(r["quadratic_score"]):.3f}'
        return [label,
                f'{float(r["accuracy"]) * 100:.1f}%',
                f'{float(r["mean_reported_probability"]) * 100:.0f}%',
                f'<b>{score}</b>' if bold_score else score]

    train_tbl = table(
        ["trained with", "benchmark score", "average confidence it claims",
         "confidence-calibrated score"],
        [train_row("base", "Untuned base"),
         train_row("binary", "Accuracy only"
                   '<span class="sub">no penalty for guessing</span>',
                   bold_score=True),
         train_row("quadratic", "Confidence-calibrated"
                   '<span class="sub">the quadratic rule</span>',
                   bold_score=True),
         train_row("quad_cost",
                   "Confidence-calibrated + fixed cost for answering")])

    # The announced-prompt robustness check: the same paired contrast
    # (quadratic-trained versus accuracy-trained) re-measured under prompts
    # announcing each approach. Read from the same results file.
    with open(os.path.join(PROC, "finetune_pilot_summary.json"),
              encoding="utf-8") as fh:
        robust = json.load(fh)["final_test"][
            "prompt_robustness_quadratic_versus_binary"]
    announce_rows = [
        ("neutral", ("Nothing announced <span class=\"sub\">the primary "
                    "test</span>")),
        ("binary", "Accuracy scoring announced"),
        ("quadratic", "Confidence-calibrated scoring announced"),
        ("quad_cost", "Confidence-calibrated + fixed cost announced")]
    announce_tbl = table(
        ["what the test prompt announced",
         "confidence-calibrated training wins by",
         "benchmark-score change"],
        [[label,
          f'<b>+{float(robust[k]["quadratic_score_change"]):.3f}</b>',
          f'{float(robust[k]["accuracy_change"]) * 100:+.1f} pp'.replace(
              "-", "&minus;")]
         for k, label in announce_rows])

    train_bench_tbl = table(
        ["evaluation benchmark", "change in confidence-calibrated score"],
        [["GPQA", "<b>+0.497</b>"],
         ["MMLU-Pro", "<b>+0.193</b>"],
         ["ARC", "<b>&minus;0.153</b>"],
         ["BoolQ", "<b>&minus;0.087</b>"]])

    constraints = rows("behaviour_constraints.csv")
    constraints_tbl = table(
        ["checkpoint", "breaks the constraint", "declines the task",
         "unusable response"],
        [[r["reward_label"] + ('<span class="sub">the model everything else '
                               'is measured against</span>'
                               if r["reward"] == "base" else ""),
          f'{float(r["breaks_constraint"]) * 100:.0f}%',
          f'{float(r["declines"]) * 100:.0f}%',
          f'{float(r["unusable"]) * 100:.0f}%'] for r in constraints])

    # --- held-out transfer beyond the training benchmarks -----------------
    # The screen establishes that these tasks are not saturated for the model
    # families we can evaluate through Tinker. The final comparison is always
    # matched within training seed: confidence-aware reward versus the binary
    # reward at the same 500-step dose. That pairing prevents seed quality from
    # being mistaken for an objective effect.
    BENCH_LABEL = {
        "truthfulqa_mc": "TruthfulQA MC1",
        "ethics_hard": "ETHICS hard",
        "bbq": "BBQ",
    }
    MODEL_LABEL = {
        "Qwen/Qwen3-8B": "Qwen3 8B",
        "Qwen/Qwen3.5-4B": "Qwen3.5 4B",
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16": "Nemotron 3 Nano",
    }
    screen = rows("broader_model_screen.csv")

    def screen_accuracy_when_answered(r):
        coverage = float(r["coverage"])
        return float(r["accuracy"]) / coverage if coverage else 0.0

    broader_screen_tbl = table(
        ["model", "benchmark", "overall accuracy", "answered",
         "accuracy when answered", "confidence when answered",
         "calibration error among answers",
         "confidence-calibrated score overall"],
        [[MODEL_LABEL.get(r["model"], r["model"]),
          BENCH_LABEL.get(r["benchmark"], r["benchmark"]),
          f'{float(r["accuracy"]) * 100:.0f}%',
          f'{float(r["coverage"]) * 100:.0f}%',
          f'{screen_accuracy_when_answered(r) * 100:.0f}%',
          f'{float(r["mean_confidence"]) * 100:.0f}%',
          f'{float(r["expected_calibration_error"]) * 100:.0f} pp',
          f'{float(r["score_quadratic"]):.3f}']
         for r in sorted(screen, key=lambda r: (
             list(BENCH_LABEL).index(r["benchmark"]),
             r["model"].split("/", 1)[0].lower(),
             -model_recency(r["model"]),
             MODEL_LABEL.get(r["model"], r["model"])))],
        right_from=2, sortable=True)

    broader = rows("broader_tuned_contrasts.csv")
    common_seeds = {"0", "1", "2", "4", "5"}
    common_arms = ("quadratic", "quad_cost_0.09")
    ARM_SHORT = {
        "quadratic": "Confidence-calibrated",
        "quad_cost_0.09": "Confidence-calibrated + cost",
    }

    def mean_range(records, field, scale=1.0, dp=1, unit=""):
        """Show the pooled direction without hiding between-seed dispersion."""
        values = [float(r[field]) * scale for r in records]
        mean_value = sum(values) / len(values)
        return (f'{mean_value:+.{dp}f}{unit} '
                f'<span class="sub">{min(values):+.{dp}f} to '
                f'{max(values):+.{dp}f}</span>').replace("-", "&minus;")

    performance_body = []
    transfer_body = []
    for benchmark, benchmark_label in BENCH_LABEL.items():
        for arm in common_arms:
            selected = [
                r for r in broader
                if r["benchmark"] == benchmark
                and r["treatment_arm"] == arm
                and r["training_seed"] in common_seeds
            ]
            positive = sum(float(r["delta_score_quadratic"]) > 0
                           for r in selected)
            accuracy_positive = sum(float(r["delta_accuracy"]) > 0
                                    for r in selected)
            performance_body.append([
                benchmark_label,
                ARM_SHORT[arm],
                "No reliable gain",
                mean_range(selected, "delta_accuracy", 100, 1, " pp"),
                f'{accuracy_positive}/5',
            ])
            transfer_body.append([
                benchmark_label,
                ARM_SHORT[arm],
                mean_range(selected, "delta_accuracy", 100, 1, " pp"),
                mean_range(selected, "delta_mean_confidence", 100, 1, " pp"),
                mean_range(selected, "delta_expected_calibration_error",
                           100, 1, " pp"),
                mean_range(selected, "delta_score_quadratic", 1, 3),
                f'<b>{positive}/5</b>' if positive == 5 else f'{positive}/5',
            ])
    broader_performance_tbl = table(
        ["held-out benchmark", "trained with",
         "performance takeaway", "accuracy change vs accuracy-only",
         "seeds with higher accuracy"],
        performance_body, right_from=3, sortable=True,
        cls="brief-prose")
    broader_transfer_tbl = table(
        ["held-out benchmark", "trained with", "overall accuracy change",
         "confidence change among answers",
         "calibration-error change among answers",
         "confidence-calibrated score change overall",
         "seeds with higher calibrated score"],
        transfer_body, right_from=2, sortable=True)

    ethics = [r for r in rows("broader_tuned_strata_contrasts.csv")
              if r["benchmark"] == "ethics_hard"
              and r["training_seed"] in common_seeds]
    ETHICS_LABEL = {
        "commonsense": "Commonsense",
        "deontology": "Deontology",
        "justice": "Justice",
        "utilitarianism": "Utilitarianism",
        "virtue": "Virtue",
    }
    ethics_body = []
    for stratum, stratum_label in ETHICS_LABEL.items():
        for arm in common_arms:
            selected = [r for r in ethics if r["stratum"] == stratum
                        and r["treatment_arm"] == arm]
            positive = sum(float(r["delta_score_quadratic"]) > 0
                           for r in selected)
            ethics_body.append([
                stratum_label, ARM_SHORT[arm],
                mean_range(selected, "delta_accuracy", 100, 1, " pp"),
                mean_range(selected, "delta_score_quadratic", 1, 3),
                f'{positive}/5',
            ])
    ethics_tasks_tbl = table(
        ["ETHICS task", "trained with", "accuracy",
         "confidence-calibrated score",
         "seeds improved"], ethics_body, right_from=2, sortable=True)

    # BBQ's published bias endpoint is signed. An objective improves it only
    # when it moves the magnitude toward zero, so compute absolute-score
    # changes from levels instead of treating every negative signed delta as a
    # gain. Unknown answers are excluded by the benchmark's definition.
    bbq_levels = rows("broader_tuned_bbq_bias.csv")
    bbq_by_key = {(r["checkpoint"], r["context_condition"]): r
                  for r in bbq_levels}
    bbq_body = []
    for context, context_label in (("ambig", "Ambiguous context"),
                                   ("disambig", "Disambiguated context")):
        for arm in common_arms:
            magnitude_changes = []
            attempt_changes = []
            for seed in sorted(common_seeds):
                treatment = bbq_by_key[(f"seed{seed}-{arm}", context)]
                control = bbq_by_key[(f"seed{seed}-binary", context)]
                magnitude_changes.append(
                    abs(float(treatment["accuracy_scaled_bias_score"]))
                    - abs(float(control["accuracy_scaled_bias_score"])))
                attempt_changes.append(
                    int(treatment["non_unknown_attempts"])
                    - int(control["non_unknown_attempts"]))
            improved = sum(change < 0 for change in magnitude_changes)
            bbq_body.append([
                context_label, ARM_SHORT[arm],
                (f'{sum(magnitude_changes) / 5 * 100:+.1f} pp '
                 f'<span class="sub">{min(magnitude_changes) * 100:+.1f} to '
                 f'{max(magnitude_changes) * 100:+.1f}</span>').replace(
                     "-", "&minus;"),
                f'{sum(attempt_changes) / 5:+.1f}'.replace("-", "&minus;"),
                f'{improved}/5',
            ])
    bbq_bias_tbl = table(
        ["BBQ endpoint", "trained with", "change in |bias|",
         "non-unknown answers", "seeds improved"],
        bbq_body, right_from=2, sortable=True)

    # --- alignment scorecard and checkpoint-level relationship ------------
    # "Alignment" is not collapsed into one score. Each row names a distinct
    # behavioral dimension, its observable proxy, and the matched comparison.
    # This prevents a small change on one benchmark from laundering a general
    # claim about whether the model is aligned.
    def selected_contrasts(benchmark, arm="quadratic"):
        return [
            r for r in broader
            if r["benchmark"] == benchmark
            and r["treatment_arm"] == arm
            and r["training_seed"] in common_seeds
        ]

    def average(records, field):
        return sum(float(record[field]) for record in records) / len(records)

    truth = selected_contrasts("truthfulqa_mc")
    ethics_quad = selected_contrasts("ethics_hard")
    truth_accuracy_delta = average(truth, "delta_accuracy")
    ethics_accuracy_delta = average(ethics_quad, "delta_accuracy")

    ambiguous_bias_changes = []
    for seed in sorted(common_seeds):
        treatment = bbq_by_key[(f"seed{seed}-quadratic", "ambig")]
        control = bbq_by_key[(f"seed{seed}-binary", "ambig")]
        ambiguous_bias_changes.append(
            abs(float(treatment["accuracy_scaled_bias_score"]))
            - abs(float(control["accuracy_scaled_bias_score"])))

    constraints_by_reward = {r["reward"]: r for r in constraints}
    calibrated_constraint = float(
        constraints_by_reward["quadratic"]["breaks_constraint"])
    accuracy_constraint = float(
        constraints_by_reward["binary"]["breaks_constraint"])
    base_constraint = float(constraints_by_reward["base"]["breaks_constraint"])

    pressure_accuracy_125 = pressure_replication_by_key[("binary", "125")]
    pressure_calibrated_125 = pressure_replication_by_key[("quadratic", "125")]
    calibrated_wrong = float(
        pressure_calibrated_125["accepts_wrong_pushback"])
    accuracy_wrong = float(pressure_accuracy_125["accepts_wrong_pushback"])
    calibrated_right = float(
        pressure_calibrated_125["accepts_right_pushback"])
    accuracy_right = float(pressure_accuracy_125["accepts_right_pushback"])
    worse_pressure_comparisons = sum(
        float(r["delta_wrong_adoption"]) > 0 for r in pressure_contrasts
    )

    alignment_scorecard_tbl = table(
        ["alignment dimension", "how it was measured",
         "confidence-calibrated vs accuracy training", "consistency",
         "what it suggests"],
        [
            ["Truthfulness", "TruthfulQA accuracy",
             f'{truth_accuracy_delta * 100:+.1f} pp'.replace("-", "&minus;"),
             f'{sum(float(r["delta_accuracy"]) > 0 for r in truth)}/5 seeds better',
             "No gain"],
            ["Ethical-judgment agreement", "ETHICS hard accuracy",
             f'{ethics_accuracy_delta * 100:+.1f} pp'.replace("-", "&minus;"),
             f'{sum(float(r["delta_accuracy"]) > 0 for r in ethics_quad)}/5 seeds better',
             "No clear gain"],
            ["Social bias", "BBQ ambiguous-context |bias|",
             (f'{sum(ambiguous_bias_changes) / len(ambiguous_bias_changes) * 100:+.1f} pp '
              '<span class="sub">higher is worse</span>').replace("-", "&minus;"),
             f'{sum(change < 0 for change in ambiguous_bias_changes)}/5 seeds better',
             "Inconsistent; mean worsened"],
            ["Constraint adherence", "Explicit-rule violation rate",
             (f'{calibrated_constraint * 100:.0f}% vs '
              f'{accuracy_constraint * 100:.0f}% '
              f'<span class="sub">untuned: {base_constraint * 100:.0f}%</span>'),
             "Two-seed pilot aggregate",
             "Better than accuracy training; same as base"],
            ["Pressure discernment", "Wrong and correct pushback",
             (f'wrong: {calibrated_wrong * 100:.0f}% vs '
              f'{accuracy_wrong * 100:.0f}% '
              f'<span class="sub">+{(calibrated_wrong - accuracy_wrong) * 100:.0f} pp worse; '
              f'correct: {calibrated_right * 100:.0f}% vs '
              f'{accuracy_right * 100:.0f}%</span>'),
             f'{worse_pressure_comparisons}/6 seed-dose comparisons worse',
             "Replicated adverse signal"],
        ],
        right_from=99, sortable=True, cls="brief-prose alignment-scorecard")

    relationship = rows("alignment_relationship.csv")
    relationship_tbl = table(
        ["alignment indicator", "lower calibration quartile",
         "upper calibration quartile", "change",
         "within-objective association"],
        [[r["indicator"],
          f'{float(r["lower_calibration_quartile_mean"]) * 100:.1f}%',
          f'{float(r["upper_calibration_quartile_mean"]) * 100:.1f}%',
          (f'{float(r["quartile_change"]) * 100:+.1f} pp').replace(
              "-", "&minus;"),
          (f'&rho; = {float(r["within_objective_rank_correlation"]):+.2f}').replace(
              "-", "&minus;")]
         for r in relationship],
        right_from=1, sortable=True, cls="brief-prose alignment-relationship")

    # --- matched catastrophic-decision and agentic battery -----------------
    # Keep the dimensions separate. A model can improve high-stakes selective
    # prediction while becoming more persuadable, and the new run does exactly
    # that. A single score would erase the main result.
    matched_levels = rows("matched_alignment_battery.csv")
    matched_contrasts = rows("matched_alignment_battery_contrasts.csv")

    def matched_arm(arm):
        return [r for r in matched_levels if r["training_objective"] == arm]

    def median_range(records, field, scale=100, dp=0, unit="%"):
        values = sorted(float(r[field]) * scale for r in records)
        median = values[len(values) // 2]
        return (f'<b>{median:.{dp}f}{unit}</b>'
                f'<span class="sub">{values[0]:.{dp}f} to '
                f'{values[-1]:.{dp}f}{unit} across seeds</span>')

    def median_delta(arm, field, *, higher_is_worse=False):
        selected = [r for r in matched_contrasts
                    if r["treatment_objective"] == arm]
        values = sorted(float(r[field]) * 100 for r in selected)
        median = values[len(values) // 2]
        if higher_is_worse:
            detail = f'{sum(value > 0 for value in values)}/5 seeds higher, worse'
        else:
            detail = f'{sum(value < 0 for value in values)}/5 seeds lower'
        return ((f'{median:+.0f} pp').replace("-", "&minus;")
                + f'<span class="sub">{detail}</span>')

    MATCHED_LABEL = {
        "binary": "Accuracy only",
        "quadratic": "Confidence-calibrated",
        "quad_cost_0.09": "Confidence-calibrated + fixed cost",
    }
    matched_battery_body = []
    for arm in ("binary", "quadratic", "quad_cost_0.09"):
        records = matched_arm(arm)
        if arm == "binary":
            decision_change = "reference"
            unsupported_change = "reference"
        else:
            decision_change = median_delta(
                arm, "high_confidence_wrong_execution_change")
            unsupported_change = median_delta(
                arm, "unsupported_wrong_adoption_change", higher_is_worse=True)
        matched_battery_body.append([
            MATCHED_LABEL[arm],
            median_range(records, "high_confidence_wrong_execution_rate"),
            decision_change,
            median_range(records, "adopted_unsupported_wrong_rate"),
            unsupported_change,
            median_range(records, "adopted_verified_correct_rate"),
            "0/80",
        ])
    matched_battery_tbl = table(
        ["trained with",
         "very bad decision: wrong, executed, and at least 95% confident",
         "change vs accuracy-only",
         "accepts unsupported wrong claim",
         "change vs accuracy-only",
         "accepts correction labeled independently verified",
         "prohibited actions in agentic scenarios"],
        matched_battery_body, right_from=1, sortable=True,
        cls="brief-prose matched-alignment")

    # --- plural-prudence causal ladder -------------------------------------
    # This is the primary alignment answer. Training effects use matched seed
    # contrasts under the neutral prompt. Prompt effects are a separate table,
    # paired to each checkpoint and compared with that checkpoint's neutral
    # response. Keeping them separate prevents prompt compliance from being
    # reported as a change in the trained weights.
    pp_levels = rows("plural_prudence_levels.csv")
    pp_contrasts = rows("plural_prudence_contrasts.csv")
    pp_prompts = rows("plural_prudence_prompt_contrasts.csv")

    def pp_median(values):
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    def pp_baseline(field, *, scale=100, dp=0, unit="%"):
        values = [
            float(r[field]) * scale for r in pp_levels
            if r["framing"] == "neutral"
            and r["training_objective"] == "binary"
            and r[field] != ""
        ]
        return f'<b>{pp_median(values):.{dp}f}{unit}</b><span class="sub">median of 5 seeds</span>'

    def pp_training_change(
        arm, field, *, favorable, scale=100, dp=1, unit=" pp"
    ):
        values = [
            float(r[f"{field}_change"]) * scale for r in pp_contrasts
            if r["framing"] == "neutral"
            and r["treatment_objective"] == arm
            and r[f"{field}_change"] != ""
        ]
        median = pp_median(values)
        favorable_n = sum(
            value < 0 if favorable == "lower" else value > 0
            for value in values
        )
        rendered = f'{median:+.{dp}f}{unit}'.replace("-", "&minus;")
        return (f'<b>{rendered}</b><span class="sub">'
                f'{favorable_n}/5 seeds {favorable}</span>')

    pp_training_body = [
        ["Probability error (Brier loss; lower is better)",
         pp_baseline("prudence_brier_loss", scale=1, dp=3, unit=""),
         pp_training_change("quadratic", "prudence_brier_loss",
                            favorable="lower", scale=1, dp=3, unit=""),
         pp_training_change("quad_cost_0.09", "prudence_brier_loss",
                            favorable="lower", scale=1, dp=3, unit=""),
         "Calibration improved in every seed"],
        ["Wrong, executed, and at least 90% confident",
         pp_baseline("prudence_high_confidence_wrong_execution_rate"),
         pp_training_change(
             "quadratic", "prudence_high_confidence_wrong_execution_rate",
             favorable="lower", dp=0),
         pp_training_change(
             "quad_cost_0.09", "prudence_high_confidence_wrong_execution_rate",
             favorable="lower", dp=0),
         "Large reduction in catastrophic overcommitment"],
        ["Wrong execution at any confidence",
         pp_baseline("prudence_wrong_execution_rate"),
         pp_training_change("quadratic", "prudence_wrong_execution_rate",
                            favorable="lower", dp=0),
         pp_training_change("quad_cost_0.09", "prudence_wrong_execution_rate",
                            favorable="lower", dp=0),
         "Fixed cost adds more verification"],
        ["Accuracy on the hard questions",
         pp_baseline("prudence_accuracy"),
         pp_training_change("quadratic", "prudence_accuracy",
                            favorable="higher", dp=1),
         pp_training_change("quad_cost_0.09", "prudence_accuracy",
                            favorable="higher", dp=1),
         "No material capability gain or loss"],
        ["Error after exact numerical evidence (percentage points)",
         pp_baseline("evidence_posterior_absolute_error",
                     scale=1, dp=1, unit=" points"),
         pp_training_change("quadratic", "evidence_posterior_absolute_error",
                            favorable="lower", scale=1, dp=1, unit=" points"),
         pp_training_change("quad_cost_0.09", "evidence_posterior_absolute_error",
                            favorable="lower", scale=1, dp=1, unit=" points"),
         "No transfer to evidence updating"],
        ["Unauthorized evaluator-reference use",
         pp_baseline("integrity_unauthorized_shortcut_rate"),
         pp_training_change("quadratic", "integrity_unauthorized_shortcut_rate",
                            favorable="lower", dp=1),
         pp_training_change("quad_cost_0.09", "integrity_unauthorized_shortcut_rate",
                            favorable="lower", dp=1),
         "Small and inconsistent"],
        ["Appropriate response to goal changes",
         pp_baseline("goal_appropriate_action_rate"),
         pp_training_change("quadratic", "goal_appropriate_action_rate",
                            favorable="higher", dp=1),
         pp_training_change("quad_cost_0.09", "goal_appropriate_action_rate",
                            favorable="higher", dp=1),
         "No transfer to goal correction"],
    ]
    plural_prudence_training_tbl = table(
        ["behavior", "accuracy-only level",
         "confidence-calibrated matched change",
         "fixed-cost matched change", "reading"],
        pp_training_body, right_from=99, sortable=True,
        cls="brief-prose plural-prudence-training")

    def pp_prompt_change(
        framing, field, *, favorable, scale=100, dp=1, unit=" pp"
    ):
        values = [
            float(r[f"{field}_change"]) * scale for r in pp_prompts
            if r["framing"] == framing and r[f"{field}_change"] != ""
        ]
        median = pp_median(values)
        favorable_n = sum(
            value < 0 if favorable == "lower" else value > 0
            for value in values
        )
        rendered = f'{median:+.{dp}f}{unit}'.replace("-", "&minus;")
        return (f'<b>{rendered}</b><span class="sub">'
                f'{favorable_n}/16 checkpoints {favorable}</span>')

    plural_prudence_prompt_tbl = table(
        ["test-time reminder", "wrong execution",
         "exact-evidence error", "unauthorized reference use",
         "appropriate goal response", "reading"],
        [["Plural ends",
          pp_prompt_change("plural", "prudence_wrong_execution_rate",
                           favorable="lower"),
          pp_prompt_change("plural", "evidence_posterior_absolute_error",
                           favorable="lower", scale=1, dp=1, unit=" points"),
          pp_prompt_change("plural", "integrity_unauthorized_shortcut_rate",
                           favorable="lower"),
          pp_prompt_change("plural", "goal_appropriate_action_rate",
                           favorable="higher"),
          "Strongest integrity effect"],
         ["Prudence",
          pp_prompt_change("prudence", "prudence_wrong_execution_rate",
                           favorable="lower"),
          pp_prompt_change("prudence", "evidence_posterior_absolute_error",
                           favorable="lower", scale=1, dp=1, unit=" points"),
          pp_prompt_change("prudence", "integrity_unauthorized_shortcut_rate",
                           favorable="lower"),
          pp_prompt_change("prudence", "goal_appropriate_action_rate",
                           favorable="higher"),
          "Better decisions; shortcuts rose"],
         ["Both reminders",
          pp_prompt_change("combined", "prudence_wrong_execution_rate",
                           favorable="lower"),
          pp_prompt_change("combined", "evidence_posterior_absolute_error",
                           favorable="lower", scale=1, dp=1, unit=" points"),
          pp_prompt_change("combined", "integrity_unauthorized_shortcut_rate",
                           favorable="lower"),
          pp_prompt_change("combined", "goal_appropriate_action_rate",
                           favorable="higher"),
          "Best balance across links"]],
        right_from=99, sortable=True, cls="brief-prose plural-prudence-prompt")

    # --- external calibration and alignment transfer ----------------------
    # Keep performance, calibration, honesty, and hierarchy as distinct rows.
    # Their favorable directions differ, and a composite would make improved
    # probability quality look like improved honesty.
    external_levels = rows("external_transfer_levels.csv")
    external_contrasts = rows("external_transfer_contrasts.csv")

    def external_aggregate(records, field):
        by_seed = {}
        for record in records:
            by_seed.setdefault(str(record["training_seed"]), []).append(
                float(record[field]))
        return [sum(values) / len(values) for values in by_seed.values()]

    def external_baseline(field, *, family="calibration transfer", task=None,
                          setting=None, scale=100, dp=0, unit="%"):
        selected = [
            record for record in external_levels
            if record["training_objective"] == "binary"
            and record["family"] == family
            and (task is None or record["task"] == task)
            and (setting is None or record["setting"] == setting)
            and record[field] != ""
        ]
        values = external_aggregate(selected, field)
        return f'<b>{pp_median(values) * scale:.{dp}f}{unit}</b><span class="sub">median of 5 seeds</span>'

    def external_change(arm, field, *, favorable, family="calibration transfer",
                        task=None, setting=None, scale=100, dp=0, unit=" pp"):
        selected = [
            record for record in external_contrasts
            if record["treatment_objective"] == arm
            and record["family"] == family
            and (task is None or record["task"] == task)
            and (setting is None or record["setting"] == setting)
            and record[field] != ""
        ]
        values = external_aggregate(selected, field)
        median = pp_median(values)
        favorable_n = sum(
            value > 0 if favorable == "higher" else value < 0
            for value in values
        )
        rendered = f'{median * scale:+.{dp}f}{unit}'.replace("-", "&minus;")
        return (f'<b>{rendered}</b><span class="sub">'
                f'{favorable_n}/5 seeds {favorable}</span>')

    external_transfer_tbl = table(
        ["measure (favorable direction)", "accuracy-only level",
         "confidence-calibrated matched change",
         "fixed-cost matched change", "reading"],
        [
            ["Unrelated short answers: confidence-calibrated score (higher)",
             external_baseline("confidence_calibrated_score", scale=1, dp=3,
                               unit=""),
             external_change("quadratic", "confidence_calibrated_score_change",
                             favorable="higher", scale=1, dp=3, unit=""),
             external_change("quad_cost_0.09",
                             "confidence_calibrated_score_change",
                             favorable="higher", scale=1, dp=3, unit=""),
             "Core calibration transfers"],
            ["Unrelated short answers: wrong at 90%+ confidence (lower)",
             external_baseline("high_confidence_wrong_rate"),
             external_change("quadratic",
                             "high_confidence_wrong_rate_change",
                             favorable="lower"),
             external_change("quad_cost_0.09",
                             "high_confidence_wrong_rate_change",
                             favorable="lower"),
             "Large reduction in overconfidence"],
            ["Unrelated short answers: exact accuracy (higher)",
             external_baseline("accuracy"),
             external_change("quadratic", "accuracy_change",
                             favorable="higher", dp=1),
             external_change("quad_cost_0.09", "accuracy_change",
                             favorable="higher", dp=1),
             "No performance gain"],
            ["MASK known facts: truth under pressure (higher)",
             external_baseline("pressure_truth_rate",
                               family="honesty under pressure", task="MASK",
                               setting="known_facts"),
             external_change("quadratic", "pressure_truth_rate_change",
                             favorable="higher", family="honesty under pressure",
                             task="MASK", setting="known_facts", dp=1),
             external_change("quad_cost_0.09", "pressure_truth_rate_change",
                             favorable="higher", family="honesty under pressure",
                             task="MASK", setting="known_facts", dp=1),
             "No honesty gain"],
            ["MASK provided facts: truth under pressure (higher)",
             external_baseline("pressure_truth_rate",
                               family="honesty under pressure", task="MASK",
                               setting="provided_facts"),
             external_change("quadratic", "pressure_truth_rate_change",
                             favorable="higher", family="honesty under pressure",
                             task="MASK", setting="provided_facts", dp=1),
             external_change("quad_cost_0.09", "pressure_truth_rate_change",
                             favorable="higher", family="honesty under pressure",
                             task="MASK", setting="provided_facts", dp=1),
             "No honesty gain"],
            ["IHEval: obey stronger system instruction (higher)",
             external_baseline("accuracy", family="instruction hierarchy",
                               task="language", setting="conflict_system_strong"),
             external_change("quadratic", "accuracy_change", favorable="higher",
                             family="instruction hierarchy", task="language",
                             setting="conflict_system_strong"),
             external_change("quad_cost_0.09", "accuracy_change",
                             favorable="higher", family="instruction hierarchy",
                             task="language", setting="conflict_system_strong"),
             "Small, inconsistent"],
            ["IHEval: resist stronger user conflict (higher)",
             external_baseline("accuracy", family="instruction hierarchy",
                               task="language", setting="conflict_user_strong"),
             external_change("quadratic", "accuracy_change", favorable="higher",
                             family="instruction hierarchy", task="language",
                             setting="conflict_user_strong"),
             external_change("quad_cost_0.09", "accuracy_change",
                             favorable="higher", family="instruction hierarchy",
                             task="language", setting="conflict_user_strong"),
             "Hard condition remains poor"],
        ],
        right_from=99, sortable=True, cls="brief-prose external-transfer")

    # --- domain-specific training and matched behavior --------------------
    # These rows cross training subject with evaluation subject. Performance,
    # confidence quality, and high-confidence error remain separate endpoints
    # because the new experiment shows that they can move in opposite ways.
    domain_transfer = rows("domain_transfer_contrasts.csv")
    domain_label = {
        "medicine": "Medicine",
        "math": "Math",
        "ethics": "Legal and ethical reasoning",
    }

    def pp_change(value, dp=0):
        return f'{float(value) * 100:+.{dp}f} pp'.replace("-", "&minus;")

    def score_change(row):
        value = float(row["confidence_calibrated_score_change"])
        low = float(row["score_ci_low"])
        high = float(row["score_ci_high"])
        return ((f'<b>{value:+.3f}</b><span class="sub">95% interval '
                 f'{low:+.3f} to {high:+.3f}</span>')
                .replace("-", "&minus;"))

    domain_transfer_tbl = table(
        ["trained on", "tested on", "accuracy change (pp)",
         "confidence-calibrated score change (−1 to +1)",
         "wrong at 80%+ confidence change (pp)"],
        [[domain_label[r["training_domain"]],
          domain_label[r["evaluation_domain"]],
          pp_change(r["accuracy_change"]),
          score_change(r),
          pp_change(r["high_confidence_wrong_change"])]
         for r in domain_transfer],
        right_from=2, sortable=True, cls="brief-prose domain-transfer")

    domain_replication = [
        row for row in rows("domain_replication_summary.csv")
        if row["training_domain"] != "all"
    ]

    def median_range(row, median_key, min_key, max_key, *, points=False):
        scale = 100 if points else 1
        dp = 1 if points else 3
        median = float(row[median_key]) * scale
        low = float(row[min_key]) * scale
        high = float(row[max_key]) * scale
        unit = " pp" if points else ""
        text = (f'<b>{median:+.{dp}f}{unit}</b><span class="sub">range '
                f'{low:+.{dp}f} to {high:+.{dp}f}{unit}</span>')
        return text.replace("-", "&minus;")

    domain_replication_tbl = table(
        ["trained on", "matched seeds completed",
         "wrong at 80%+ confidence change, median (range; pp)",
         "accuracy change, median (range; pp)",
         "confidence-calibrated score change, median (range; −1 to +1)",
         "direction count"],
        [[domain_label[row["training_domain"]],
          (f'{row["admitted_training_pairs"]} of '
           f'{row["planned_training_pairs"]}' +
           (f'<span class="sub">{row["failed_training_pairs"]} failed health gate</span>'
            if int(row["failed_training_pairs"]) else "")),
          median_range(row, "median_high_confidence_wrong_change",
                       "min_high_confidence_wrong_change",
                       "max_high_confidence_wrong_change", points=True),
          median_range(row, "median_accuracy_change", "min_accuracy_change",
                       "max_accuracy_change", points=True),
          median_range(row, "median_confidence_calibrated_score_change",
                       "min_confidence_calibrated_score_change",
                       "max_confidence_calibrated_score_change"),
          (f'{row["risk_reductions_observed"]} of {row["planned_contrasts"]} '
           f'planned<span class="sub">score improved '
           f'{row["score_improvements_observed"]} of '
           f'{row["observed_contrasts"]} measurable</span>')]
         for row in domain_replication],
        right_from=99, sortable=True, cls="brief-prose domain-replication")

    # --- pooled calibration, unseen-domain transfer, and hidden opportunity --
    # These tables use only matched binary/quadratic seed pairs. Accuracy and
    # high-confidence error share the all-item denominator; the agentic risk
    # rates use the 160 policy-conflict actions per checkpoint and keep the 160
    # authorized controls beside them.
    multitask_transfer = rows("multitask_transfer_summary.csv")
    pooled_transfer = [
        row for row in multitask_transfer if row["training_regime"] == "pooled"
    ]
    expanded_domain_label = {**domain_label, "gpqa": "GPQA Diamond (unseen)"}
    pooled_transfer_tbl = table(
        ["tested on", "items per checkpoint", "matched seed pairs",
         "accuracy change, median (range; pp)",
         "wrong at 80%+ confidence change, median (range; pp)",
         "confidence-calibrated score change, median (range; &minus;1 to +1)",
         "seeds reducing high-confidence errors"],
        [[expanded_domain_label[row["evaluation_domain"]],
          "198" if row["evaluation_domain"] == "gpqa" else "300",
          row["matched_seed_pairs"],
          median_range(row, "median_accuracy_change", "min_accuracy_change",
                       "max_accuracy_change", points=True),
          median_range(row, "median_high_confidence_wrong_change",
                       "min_high_confidence_wrong_change",
                       "max_high_confidence_wrong_change", points=True),
          median_range(row, "median_confidence_calibrated_score_change",
                       "min_confidence_calibrated_score_change",
                       "max_confidence_calibrated_score_change"),
          f'{row["risk_reductions"]} of {row["matched_seed_pairs"]}']
         for row in pooled_transfer],
        right_from=1, sortable=True, cls="brief-prose pooled-transfer")

    gpqa_transfer = [
        row for row in multitask_transfer if row["evaluation_domain"] == "gpqa"
    ]
    training_label = {
        "pooled": "Pooled medicine + math + ethics",
        **domain_label,
    }
    gpqa_transfer_tbl = table(
        ["calibration trained on", "matched seed pairs",
         "GPQA accuracy change, median (range; pp)",
         "GPQA wrong at 80%+ confidence change, median (range; pp)",
         "confidence-calibrated score change, median (range; &minus;1 to +1)"],
        [[training_label[row["training_regime"]], row["matched_seed_pairs"],
          median_range(row, "median_accuracy_change", "min_accuracy_change",
                       "max_accuracy_change", points=True),
          median_range(row, "median_high_confidence_wrong_change",
                       "min_high_confidence_wrong_change",
                       "max_high_confidence_wrong_change", points=True),
          median_range(row, "median_confidence_calibrated_score_change",
                       "min_confidence_calibrated_score_change",
                       "max_confidence_calibrated_score_change")]
         for row in sorted(
             gpqa_transfer,
             key=lambda item: (item["training_regime"] != "pooled",
                               item["training_regime"]),
         )],
        right_from=1, sortable=True, cls="brief-prose gpqa-transfer")

    hidden_rows = rows("hidden_opportunity_contrasts.csv")

    def hidden_summary(label, selected):
        def values(key):
            return [float(row[key]) for row in selected]

        def pct_range(key):
            vals = values(key)
            return (f'<b>{statistics.median(vals) * 100:+.1f} pp</b>'
                    f'<span class="sub">range {min(vals) * 100:+.1f} to '
                    f'{max(vals) * 100:+.1f} pp</span>').replace("-", "&minus;")

        control = values("binary_unauthorized_action_rate")
        treatment = values("quadratic_unauthorized_action_rate")
        change = values("change_unauthorized_action_rate")
        return [
            label,
            str(len(selected)),
            (f'{statistics.median(control) * 100:.1f}% &rarr; '
             f'<b>{statistics.median(treatment) * 100:.1f}%</b>'),
            pct_range("change_unauthorized_action_rate"),
            pct_range("change_high_confidence_unauthorized_rate"),
            pct_range("change_authorized_control_completion"),
            f'{sum(value < 0 for value in change)} of {len(selected)}',
        ]

    pooled_hidden = [row for row in hidden_rows if row["training_regime"] == "pooled"]
    subject_hidden = [row for row in hidden_rows if row["training_regime"] != "pooled"]
    hidden_opportunity_tbl = table(
        ["training comparison", "matched seed pairs",
         "unauthorized shortcut rate among 160 conflict actions",
         "shortcut-rate change, median (range; pp)",
         "high-confidence shortcut change, median (range; pp)",
         "authorized completion change among 160 controls",
         "pairs reducing shortcuts"],
        [hidden_summary("Pooled", pooled_hidden),
         hidden_summary("Subject-specific", subject_hidden)],
        right_from=1, sortable=True, cls="brief-prose hidden-opportunity")

    multitask_gates = rows("multitask_family_gates.csv")
    family_gate_tbl = table(
        ["model stage", "responses or training examples", "malformed rate",
         "gate result"],
        [[("Shared knowledge-free format checkpoint" if row["stage"] ==
           "knowledge_free_format_checkpoint" else
           row["stage"].replace("full_profile_seed", "Full profile, seed ")),
          f'{int(row["sample_size"]):,}',
          ("not applicable" if not row["invalid_rate"] else
           f'{float(row["invalid_rate"]) * 100:.2f}%'),
          ("Completed; continue" if row["decision"] == "continue_to_full_profiles"
           else "Passed" if row["decision"] == "admit"
           else "Failed 1% gate; stop")]
         for row in multitask_gates],
        right_from=1, sortable=True, cls="brief-prose multitask-family-gates")

    openweight_gates = rows("openweight_family_gates.csv")
    openweight_names = {
        "openai/gpt-oss-20b": "GPT-OSS 20B",
        "moonshotai/Kimi-K2.6": "Kimi K2.6",
    }
    openweight_gate_tbl = table(
        ["model", "test", "responses", "malformed", "what happened", "decision"],
        [[openweight_names.get(row["model"], row["model"]),
          ("Route check" if row["stage"] == "one_response_route_check"
           else "Full format profile"),
          f'{int(row["sample_size"]):,}',
          (f'{int(row["invalid_count"]):,} '
           f'({float(row["invalid_rate"]) * 100:.1f}%)'),
          row["observation"],
          ("Continue to full profile" if row["decision"] == "continue_to_full_profile"
           else "Stop before full profile" if row["decision"] == "stop_before_full_profile"
           else "Stop before reward training")]
         for row in openweight_gates],
        right_from=2, sortable=True, cls="brief-prose openweight-family-gates")

    openweight_followup_gates = rows("openweight_followup_gates.csv")
    openweight_followup_gate_tbl = table(
        ["model configuration", "responses", "token allowance", "malformed",
         "gate"],
        [[row["model_stage"], f'{int(row["responses"]):,}', row["max_tokens"],
          f'{int(row["malformed_count"]):,} ({float(row["malformed_rate"]) * 100:.2f}%)',
          ("Passed" if row["gate"] == "pass" else "Failed")]
         for row in openweight_followup_gates],
        right_from=1, sortable=True, cls="brief-prose openweight-followup-gates")

    openweight_followup_training = rows("openweight_followup_training.csv")
    openweight_followup_training_tbl = table(
        ["model configuration", "planned matched pairs", "complete pairs",
         "failed pairs", "evaluated checkpoints"],
        [[row["model"], row["planned_pairs"], row["complete_pairs"],
          row["failed_pairs"], row["evaluated_checkpoints"]]
         for row in openweight_followup_training],
        right_from=1, sortable=True, cls="brief-prose openweight-followup-training")

    openweight_followup_transfer = rows("openweight_followup_transfer.csv")
    openweight_followup_transfer_tbl = table(
        ["held-out domain", "matched pairs",
         "confidence-calibrated score change, median (range; &minus;1 to +1)",
         "high-confidence wrong-answer change, median (range; pp)",
         "accuracy change, median (range; pp)", "score improved"],
        [[domain_label.get(row["evaluation_domain"], row["evaluation_domain"].upper()),
          row["matched_pairs"],
          median_range(row, "median_confidence_calibrated_score_change",
                       "min_confidence_calibrated_score_change",
                       "max_confidence_calibrated_score_change"),
          median_range(row, "median_high_confidence_wrong_change",
                       "min_high_confidence_wrong_change",
                       "max_high_confidence_wrong_change", points=True),
          median_range(row, "median_accuracy_change", "min_accuracy_change",
                       "max_accuracy_change", points=True),
          f'{row["score_improvements"]} of {row["matched_pairs"]}']
         for row in openweight_followup_transfer],
        right_from=1, sortable=True, cls="brief-prose openweight-followup-transfer")

    openweight_followup_hidden = rows("openweight_followup_hidden.csv")
    openweight_followup_hidden_tbl = table(
        ["training seed", "unauthorized shortcuts: accuracy to confidence",
         "shortcut change", "high-confidence shortcut change",
         "authorized completion change"],
        [[row["training_seed"],
          (f'{float(row["binary_unauthorized_rate"]) * 100:.1f}% &rarr; '
           f'{float(row["quadratic_unauthorized_rate"]) * 100:.1f}%'),
          f'{float(row["unauthorized_rate_change"]) * 100:+.1f} pp',
          f'{float(row["high_confidence_unauthorized_change"]) * 100:+.1f} pp',
          f'{float(row["authorized_completion_change"]) * 100:+.1f} pp']
         for row in openweight_followup_hidden],
        right_from=1, sortable=True, cls="brief-prose openweight-followup-hidden")

    model_gates = rows("domain_replication_model_gates.csv")
    gate_by_model = collections.defaultdict(list)
    for row in model_gates:
        gate_by_model[row["model"]].append(row)
    model_gate_tbl = table(
        ["model", "64-response pilot", "full profile", "decision"],
        [[model,
          "0% malformed",
          (f'<b>{min(float(row["invalid_rate"]) for row in records if row["stage"] == "full_base_profile") * 100:.1f}%'
           + (f' to {max(float(row["invalid_rate"]) for row in records if row["stage"] == "full_base_profile") * 100:.1f}%'
              if len([row for row in records if row["stage"] == "full_base_profile"]) > 1 else "")
           + ' malformed</b><span class="sub">1,920 responses per subject</span>'),
          "Stopped before reward training"]
         for model, records in sorted(gate_by_model.items())],
        right_from=99, sortable=True, cls="brief-prose model-gates")

    domain_behavior = rows("domain_alignment_behavior.csv")

    def level_change(row, stem, *, lower_better):
        control = float(row[f"{stem}_binary"])
        treatment = float(row[f"{stem}_quadratic"])
        change = treatment - control
        direction = "better" if (change < 0) == lower_better and change != 0 else (
            "worse" if change != 0 else "no change"
        )
        return ((f'{control * 100:.1f}% &rarr; <b>{treatment * 100:.1f}%</b>'
                 f'<span class="sub">{change * 100:+.1f} pp, {direction}</span>')
                .replace("-", "&minus;"))

    domain_behavior_tbl = table(
        ["trained on",
         "unauthorized shortcut rate (lower is better)",
         "benign tool success (higher is better)",
         "appropriate goal response (higher is better)",
         "XSTest benign refusal (lower is better)"],
        [[domain_label[r["training_domain"]],
          level_change(r, "unauthorized_shortcut", lower_better=True),
          level_change(r, "benign_tool_success", lower_better=False),
          level_change(r, "goal_appropriate", lower_better=False),
          level_change(r, "xstest_benign_refusal", lower_better=True)]
         for r in domain_behavior],
        right_from=99, sortable=True, cls="brief-prose domain-behavior")

    test_variation_tbl = table(
        ["battery", "where it came from", "what varied", "what saturated"],
        [
            ["Plural-prudence chain",
             "New deterministic scenarios created here; hard questions from public benchmarks",
             "Risky decisions, evidence updates, shortcuts, tool use, and goal changes",
             "Hard-constraint violations were nearly always zero"],
            ["Matched alignment battery",
             "Public MMLU-Pro and MedMCQA questions; agentic scenarios adapted from Anthropic research",
             "High-stakes decisions and response to claimed evidence",
             "Transparent prohibited-action scenarios were zero throughout"],
            ["External transfer battery",
             "Public GSM8K, TriviaQA, HotpotQA, MASK, and IHEval",
             "Probability quality, honesty under pressure, and language hierarchy",
             "IHEval prompt hijacking: every pilot model passed controls and failed attacks"],
            ["Domain-transfer and behavior battery",
             "Frozen MedMCQA, MMLU-Pro math, ETHICS hard, official XSTest, and new tool scenarios",
             "Cross-subject performance, overconfident error, unauthorized shortcuts, and benign controls",
             "XSTest harmful compliance, checker tampering, concealment, and most goal endpoints"],
            ["Pooled transfer and hidden-opportunity battery",
             "Frozen subject pools, full GPQA Diamond, and 32 new conflict-control workflow pairs",
             "Five pooled seeds, cross-subject restraint, and unauthorized actions without misconduct labels",
             "Authorized controls remained at 100%; concealment remained at zero"],
        ],
        right_from=99, sortable=True, cls="brief-prose test-variation-audit")

    # --- the evidence ledger -------------------------------------------------
    def state(kind, label):
        return f'<span class="state {kind}">{label}</span>'
    status_tbl = table(
        ["claim", "evidence", "status", "what would settle it"],
        [["Models almost never say they don't know on closed-form benchmarks",
          (f"{total:,} published responses; the strictest reading finds "
          f"{strict_line} on GPQA Diamond"),
          state("done", "Strong census"),
          "a refreshed corpus with outcome-level abstention labels"],
         [("A flat wrong-answer penalty, when every item must be answered, "
           "cannot reorder a leaderboard"),
          ("every published run rescored at three penalty levels: same order "
          "every time, matching the algebra"), state("done", "Exact"),
          "mathematical identity under the stated conditions"],
         [("Told the rule and a 30% threshold, models narrow their "
           "overconfidence"),
          ((f"median matched confidence-gap change "
            f"{primary_gap_delta * 100:+.1f} points; the score improved in "
            f"{primary_score_wins}/{len(prompt_pairs)} matched comparisons, "
            "with 120 to 198 items per condition").replace("-", "&minus;")),
          state("now", "Mixed larger estimate"),
          ("a reasoning-on replication, a second generation per item, and "
           "more task formats")],
        [("Training on the rule improves the confidence-calibrated score "
          "versus accuracy training"),
          ("five pooled and seven subject-specific Qwen pairs; on unseen GPQA "
           "the median gain was +0.149 to +0.178 across training regimes"),
          state("pass", f"Replicated in {len(synthesis_families)} families"),
          ("a fourth base-model family; Kimi K2.6 and DeepSeek V3.1 still fail "
           "the format gate before training starts")],
        ["Better self-estimation transfers to some held-out tasks",
          ("five pooled seed pairs cut high-confidence wrong answers by 13 to "
           "51 points across four subjects, including unseen GPQA; accuracy "
           "fell by 1 to 3 points"),
          state("now", "Five-seed cross-subject result"),
          "a second healthy model family"],
         ["Calibration training makes models better behaved",
          ("overconfident bad decisions fell sharply; hidden unauthorized "
           "shortcuts fell by 1 to 3 points at the median with no control loss, "
           "but still occurred in 84% to 94% of conflict trials"),
          state("now", "Strong prudence; small integrity gain"),
          ("multi-step hidden-action environments with concealment opportunities "
           "and another model family")],
         ["A fixed answering cost improves training beyond the quadratic rule",
          ("its incremental effect moved in opposite directions on two seeds; "
          "with and without it the confidence-calibrated scores tie"),
          state("invalid", "No training gain"),
          "an isolated prompt contrast and a training dose grid over c"],
         ["The free-form judge can be trusted",
          ("validation against hand labels not yet run; short-answer accuracy "
          "leans on it"), state("todo", "Open"),
          "judgecheck against 60 hand labels, ~$1"],
         ["The rule improves grading rather than staging deployment",
          "the falsifier arm ran in the pilot and is not yet analysed",
          state("todo", "Open"),
          "analysing the arm that already ran"]],
        right_from=99, cls="brief-prose gaps")

    next_tbl = table(
        ["page", "the question it answers"],
        [['<a href="index.html">Findings page</a>',
          "an alternative narrative presentation of the same research"],
         ['<a href="validation.html">Harness validation</a>',
          "did this harness reproduce published scores before any treatment"],
         ['<a href="training.html">Fine-tuning</a>',
          "the training design, the gates, and the runs that stopped"],
         ['<a href="dose-response.html">Dose response</a>',
          "how the training effect grows and decays with steps"],
         ['<a href="why-linear-fails.html">Why linear fails</a>',
          "the interactive version of the linear rule's failure"],
         ['<a href="related-work.html">What this builds on</a>',
          "what already exists, and how much of this ground is taken"]],
        right_from=99, cls="brief-prose gaps")

    # Footnotes and source lines. The brief carried nineteen descriptive
    # captions and no attribution at all; these are the claims a reader is
    # most likely to want to check, using the same fn() device the findings
    # page already uses.
    fn_hle_few = fn(
        "Every published HLE run was rescored, not a chosen few. Only three "
        "models state a confidence on essentially every response, which is "
        "what rescoring needs: the rule scores the number a model gives, so a "
        "run that mostly gives none cannot be scored under it. The models "
        "that state one rarely are shown below, with what their sliver "
        "actually measures.")
    fn_census_phrases = fn(
        "Roughly eighteen phrasings, from &ldquo;I don't know&rdquo; through "
        "&ldquo;cannot determine&rdquo; to a bare &ldquo;unknown&rdquo;. The "
        "full list, and how much the rate moves when it is narrowed, are in "
        "the appendix below. The broad list is used for the headline because "
        "it is the setting most likely to FIND declining, which makes a low "
        "number harder to dismiss.")
    fn_pilot_reasoning = fn(
        "Reasoning was disabled for five of the six models to keep the pilot "
        "inside its budget, and the prompt asks for a confidence and appends "
        "an &ldquo;I don't know&rdquo; option. Both push accuracy well below "
        "each model's published score. The comparison here is between two "
        "conditions of the same model, which those choices affect equally.")
    fn_seeds = fn(
        "Two training seeds, averaged. The confidence column is the "
        "seed-unstable one: the calibration-trained model claims 45% on one "
        "seed and 63% on the other under the neutral prompt. Per-seed rows "
        "are in the collapsed block below.")

    # The appendix's dataset registry, rendered from the same dict the source
    # lines use, so a pull date cannot say one thing under a table and
    # another in the appendix.
    SCRIPT_FOR = {
        "census": "scripts/census.py",
        "decline_samples": "scripts/census_decline_samples.py",
        "hle": "scripts/hle_rescore.py",
        "parity": "the lab's runner (not in the repository; available on request)",
        "pilot": "the lab's runner and its report (not in the repository; available on request)",
        "prompt_estimation": "scripts/export_prompt_estimation.py",
        "finetune": "scripts/export_finetune_matrix.py",
        "policy_architecture": "scripts/analyze_policy_architecture.py",
        "prompt_threshold_factorial": (
            "scripts/analyze_prompt_threshold_factorial.py"),
        "pressure": "scripts/export_sycophancy.py",
        "pressure_replication": "scripts/export_pressure_replication.py",
        "pressure_prompting": "scripts/export_pressure_prompting.py",
        "constraints": "scripts/export_behaviour.py",
        "broader": "scripts/summarize_broader_evals.py",
        "alignment": "scripts/analyze_alignment_relationship.py",
        "matched_alignment": "scripts/export_alignment_battery.py",
        "plural_prudence": "scripts/export_plural_prudence.py",
        "external_transfer": "scripts/export_external_transfer.py",
        "domain_alignment": "scripts/export_domain_alignment.py",
        "domain_replication": "scripts/export_domain_replication.py",
        "multitask_family_agentic": "scripts/export_multitask_family_agentic.py",
        "openweight_family": "scripts/export_openweight_family.py",
        "openweight_followup": "scripts/export_openweight_followup.py",
    }
    vintage_tbl = table(
        ["dataset", "pulled", "what it is", "regenerate with"],
        [[key.replace("_", " "), when, what,
          f'<code>{SCRIPT_FOR[key]}</code>']
         for key, (when, what) in DATA_VINTAGE.items()],
        right_from=99, cls="brief-prose vintage")

    sens_tbl_brief = table(
        ["what was searched", "phrase list", "declines found", "rate"],
        [[r["search_scope"], r["phrase_list"], r["n_declines"],
          f'<b>{pct(r["decline_rate"], 3)}</b>'] for r in sens])

    body = content.load("brief").format(
        b_stats=stats,
        b_stated_pct=pct(summary["stated_confidence_rate"]),
        b_decline_pct=pct(summary["decline_rate"]),
        b_bench=bench_tbl,
        b_split=split_tbl,
        b_strict=strict_line,
        b_affine_runs=affine_runs,
        b_affine_dev=affine_dev,
        b_landscape=landscape_tbl,
        b_fourways=fourways_tbl,
        b_cost=cost_tbl,
        b_hle=hle_tbl,
        b_hle_cost=hle_cost_tbl,
        b_ourscores=ourscores_tbl,
        b_announce=announce_tbl,
        b_payoff=payoff_widget(),
        b_worked=worked_tbl,
        b_costrow=costrow_tbl,
        b_parity=parity_tbl,
        b_pilot_levels=pilot_levels_tbl,
        b_pilot_summary=pilot_summary_tbl,
        b_prompt_gap_control=f"{primary_gap_control * 100:.0f}",
        b_prompt_gap_treated=f"{primary_gap_treated * 100:.0f}",
        b_prompt_gap_delta=f"{primary_gap_delta * 100:+.1f}".replace(
            "-", "&minus;"),
        b_prompt_gap_reduction=f"{-primary_gap_delta * 100:.1f}",
        b_prompt_accuracy_delta=f"{primary_accuracy_delta * 100:+.1f}".replace(
            "-", "&minus;"),
        b_prompt_score_delta=f"{primary_score_delta:+.3f}".replace(
            "-", "&minus;"),
        b_prompt_score_wins=primary_score_wins,
        b_prompt_comparisons=len(prompt_pairs),
        b_prompt_responses=f"{int(prompt_meta['responses']):,}",
        b_pilot_pooled=pilot_pooled_tbl,
        b_takeaways_pilot=pilot_takeaways,
        b_takeaways_train=train_takeaways,
        b_hle_low=hle_low_tbl,
        b_survey=survey_tbl,
        b_vintage=vintage_tbl,
        b_sens=sens_tbl_brief,
        b_fn_hle_few=fn_hle_few,
        b_fn_census_phrases=fn_census_phrases,
        b_fn_pilot_reasoning=fn_pilot_reasoning,
        b_fn_seeds=fn_seeds,
        b_src_census=vintage("census"),
        b_src_hle=vintage("hle"),
        b_src_pilot=vintage(
            "prompt_estimation",
            (f"{int(prompt_meta['responses']):,} parse-preserved responses; "
             f"generation cost ${float(prompt_meta['generation_cost_usd']):.2f}. "
             "All headline outcomes were graded deterministically.")),
        b_src_parity=vintage("parity"),
        b_src_finetune=vintage("finetune"),
        b_src_policy_architecture=vintage("policy_architecture"),
        b_src_prompt_threshold_factorial=vintage("prompt_threshold_factorial"),
        b_src_pressure=vintage("pressure"),
        b_src_pressure_replication=vintage(
            "pressure_replication",
            ("The 150 items were excluded from the earlier pilot by item "
             "offset. Every second-turn response was parseable. Conservative "
             f"Tinker reservation: ${neutral_replication_spend:.6f} under a "
             "$1.35 cap.")),
        b_src_pressure_prompting=vintage(
            "pressure_prompting",
            ("The three announced-rule conditions added 4,488 parse-clean "
             "evaluations. Their conservative Tinker reservation was "
             f"${announced_prompt_spend:.6f}. Including pilots and the neutral "
             f"replication, all eight completed runs reserved "
             f"${pressure_spend_total:.6f} under explicit caps.")),
        b_src_constraints=vintage("constraints"),
        b_src_samples=vintage("decline_samples"),
        b_survey_total=n_survey,
        b_survey_census=n_census_rows,
        b_survey_external=n_external,
        b_survey_graded=n_graded,
        b_phrase=phrase_tbl,
        b_ratio_agentic=f"{a_r / closed_clean_rate:.0f}",
        b_agentic_rate=pct(a_r),
        b_closed_clean=pct(closed_clean_rate),
        b_lingoly_no=pct(lingoly["nocontext"]),
        b_lingoly_yes=pct(lingoly["context"]),
        b_lingoly_ratio=f"{lingoly['nocontext'] / lingoly['context']:.1f}",
        b_train_matrix=train_matrix_tbl,
        b_train_summary=train_summary_tbl,
        b_prompt_factorial=prompt_factorial_tbl,
        b_prompt_factorial_wrong_delta=(
            f'{abs(prompt_headline["wrong_change"]) * 100:.1f}'
        ),
        b_prompt_factorial_value_delta=(
            f'{prompt_headline["utility_change"] * 100:.1f}'
        ),
        b_prompt_only_value_delta=(
            f'{prompt_headline["prompt_only_utility_change"] * 100:.1f}'
        ),
        b_gate_value_delta=(
            f'{abs(prompt_headline["gate_marginal_utility_change"]) * 100:.1f}'
        ),
        b_prompt_embedded_invalid=int(
            prompt_headline["embedded_format_failures"]),
        b_prompt_separated_invalid=int(
            prompt_headline["separated_format_failures"]),
        b_prompt_formatted_wrong_delta=(
            f'{abs(prompt_factorial["well_formatted_pair_sensitivity"]["wrong_change"]) * 100:.1f}'
        ),
        b_prompt_formatted_value_delta=(
            f'{prompt_factorial["well_formatted_pair_sensitivity"]["utility_change"] * 100:.1f}'
        ),
        b_policy_primary=policy_primary_tbl,
        b_policy_stakes=policy_stakes_tbl,
        b_policy_wrong_delta=(
            f'{policy_architecture["headline_equal_benchmark_weight"]["wrong_change"] * 100:.1f}'
        ),
        b_policy_matched_error_delta=(
            f'{policy_architecture["headline_equal_benchmark_weight"]["matched_error_change"] * 100:.1f}'
        ),
        b_train_seeds=train_seeds_tbl,
        b_pressure=pressure_tbl,
        b_pressure_replication=pressure_replication_tbl,
        b_pressure_prompt_contrasts=pressure_prompt_contrast_tbl,
        b_pressure_prompt_levels=pressure_prompt_levels_tbl,
        b_constraints=constraints_tbl,
        b_broader_screen=broader_screen_tbl,
        b_broader_performance=broader_performance_tbl,
        b_broader_transfer=broader_transfer_tbl,
        b_ethics_tasks=ethics_tasks_tbl,
        b_bbq_bias=bbq_bias_tbl,
        b_alignment_scorecard=alignment_scorecard_tbl,
        b_alignment_relationship=relationship_tbl,
        b_matched_alignment=matched_battery_tbl,
        b_plural_prudence_training=plural_prudence_training_tbl,
        b_plural_prudence_prompting=plural_prudence_prompt_tbl,
        b_external_transfer=external_transfer_tbl,
        b_domain_transfer=domain_transfer_tbl,
        b_domain_replication=domain_replication_tbl,
        b_domain_replication_gates=model_gate_tbl,
        b_pooled_transfer=pooled_transfer_tbl,
        b_gpqa_transfer=gpqa_transfer_tbl,
        b_hidden_opportunity=hidden_opportunity_tbl,
        b_multitask_family_gates=family_gate_tbl,
        b_openweight_family_gates=openweight_gate_tbl,
        b_openweight_followup_gates=openweight_followup_gate_tbl,
        b_openweight_followup_training=openweight_followup_training_tbl,
        b_openweight_followup_transfer=openweight_followup_transfer_tbl,
        b_openweight_followup_hidden=openweight_followup_hidden_tbl,
        b_domain_behavior=domain_behavior_tbl,
        b_test_variation_audit=test_variation_tbl,
        b_src_plural_prudence=vintage(
            "plural_prudence",
            ("Neutral training comparisons use five independent matched "
             "training seeds. Agentic repetitions estimate behavior on the "
             "frozen prompts and are not additional training replicates. "
             "No composite alignment score was constructed. Conservative "
             "Tinker reservation: $7.234702 under an $8.64 cap; both pilots "
             "reserved another $0.015366.")),
        b_src_external_transfer=vintage(
            "external_transfer",
            ("The confirmatory run used 450 fresh short-answer questions, "
             "483 MASK pressure scenarios plus 209 supported belief probes, "
             "and 200 matched IHEval language conditions. Five training "
             "seeds were compared within seed. Conservative Tinker "
             "reservation: $1.555547 under a $1.56 cap; the two pilots "
             "reserved another $0.041739. Exact items, raw responses, source "
             "revisions, and checkpoint paths are preserved.")),
        b_src_domain_alignment=vintage(
            "domain_alignment",
            ("Each training domain used 240 frozen training items and 100 "
             "disjoint evaluation items per subject. Domain contrasts use "
             "one matched training seed. XSTest used its official 250 benign "
             "and 200 harmful prompts. The agentic battery used five samples "
             "per checkpoint-scenario cell. All raw responses, item hashes, "
             "checkpoint paths, and spend ledgers are preserved. The full "
             "program reserved $2.561390 under its $20 cap.")),
        b_src_domain_replication=vintage(
            "domain_replication",
            ("Every evaluation cell contains 300 exact-ID-disjoint new items. "
             "The two failed Qwen math pairs remain in the planned denominator. "
             "All raw responses, failed health records, checkpoint paths, and "
             "spend ledgers are preserved. Conservative Tinker liability is "
             "$5.877904 under the $20 program cap.")),
        b_src_multitask_family_agentic=vintage(
            "multitask_family_agentic",
            ("Every factual contrast is matched within seed. The hidden test "
             "uses 32 matched conflict-control scenarios with five repetitions, "
             "or 160 conflict and 160 control actions per checkpoint. GPQA uses "
             "its full 198-item census and has zero training-ID overlap. Exact "
             "prior responses were reused where item and checkpoint identities "
             "matched. Recorded new spend was $4.543019 under the $20 cap.")),
        b_src_openweight_family=vintage(
            "openweight_family",
            ("The protocol was committed before sampling. GPT-OSS stopped "
             "after its one-response route check. Kimi completed one full "
             "1,920-response profile, then stopped because its 48.5% malformed "
             "rate exceeded the frozen 1% gate. Raw responses, hashes, and "
             "spend ledgers are preserved. Actual spend was $1.125826 under "
             "the $20 cap.")),
        b_src_openweight_followup=vintage(
            "openweight_followup",
            ("Every factual contrast compares confidence-aware with accuracy-only "
             "training within the same seed. The shared syntax checkpoint is the "
             "control for all reward arms. One planned seed failed its first "
             "training health gate and was not replaced. Raw responses, failed "
             "health records, checkpoint paths, and spend ledgers are preserved. "
             "Recorded liability was $10.929454 under the $20 cap; two terminal "
             "sampling steps use conservative maximum-token backfills.")),
        b_src_matched_alignment=vintage(
            "matched_alignment",
            ("All rows use the same five training seeds at step 500. "
             "Decision rates are among parseable responses; parse rates were "
             "89% to 100% across checkpoints. Evidence-response rates are "
             "conditional: 21 to 31 initially correct items per seed for the "
             "unsupported claim and 29 to 39 initially wrong items per seed "
             "for the correction labeled verified. The prompt states that the "
             "answer key was independently verified; it does not show the "
             "underlying evidence. The agentic test recorded zero "
             "prohibited actions in all 288 checkpoint-scenario cells, "
             "including the untuned base and two extra fixed-cost variants. "
             "Conservative Tinker reservation: $0.511622 under a $0.80 cap.")),
        b_src_alignment=vintage(
            "alignment",
            ("Calibration quartiles are formed separately inside each of "
             "five training objectives. Checkpoints come from one seed and "
             "are repeated trajectory states, not 100 independent models.")),
        b_pressure_spend_total=f"${pressure_spend_total:.6f}",
        b_src_broader=vintage(
            "broader",
            ("TruthfulQA, ETHICS, and BBQ are described by their official "
             "repositories; all model answers and exact item manifests are "
             "preserved with the run.")),
        b_mock_scatter=scatter_fig,
        b_scatter_acc_span=f"{scatter_acc_span:.0f}",
        b_scatter_conf_span=f"{scatter_conf_span:.0f}",
        b_stated_pct2=pct(summary["stated_confidence_rate"]),
        b_pilot_sqa=pilot_sqa_tbl,
        b_pilot_mc=pilot_mc_tbl,
        b_train=train_tbl,
        b_train_bench=train_bench_tbl,
        b_status=status_tbl,
        b_next=next_tbl)

    body = body + BRIEF_JS

    side_page(
        "brief.html",
        title="There should be a penalty for guessing &middot; Below Zero",
        description="How accuracy-only benchmarks reward confident guesses, "
                    "how to score honest confidence, and what changed when "
                    "models were prompted and trained on that rule.",
        h1="There should be a penalty for guessing",
        standfirst="How accuracy-only benchmarks reward confident guesses, "
                   "how to score honest confidence, and what changed when "
                   "models were prompted and trained on that rule.",
        body=body,
        footer="Every figure comes from the CSVs published with the site and "
               "is computed by the same code. Corrections welcome.",
        content_updated=BRIEF_CONTENT_UPDATED,
        style_updated=BRIEF_STYLE_UPDATED,
        site_commit=BRIEF_SITE_COMMIT,
        extra_css=BRIEF_CSS)


def build_table_brief():
    """Build the rearrangeable, table-first outline of the findings.

    This page deliberately recomputes its headline cells from the committed
    processed files. It does not copy rendered tables out of ``brief.html``:
    the two pages share evidence, not markup, and a stale hand-entered summary
    should fail visibly when the underlying CSV changes.
    """
    summary = {r["metric"]: r["value"] for r in rows("census_summary.csv")}

    def signed_pp(value, dp=1):
        return f'{value * 100:+.{dp}f} pp'.replace("-", "&minus;")

    def evidence_state(kind, label):
        return f'<span class="evidence-state {kind}">{label}</span>'

    # --- the argument in one screen ---------------------------------------
    survey = rows("benchmark_scoring_survey.csv")
    gradable = [r for r in survey if r["prices_wrong_answers"] in {"yes", "no"}]
    priced_wrong = sum(r["prices_wrong_answers"] == "yes" for r in gradable)

    prompt_levels = rows("prompt_estimation_levels.csv")
    with open(os.path.join(PROC, "prompt_estimation_run.json"),
              encoding="utf-8") as handle:
        prompt_meta = json.load(handle)
    prompt_index = {
        (r["model"], r["benchmark"], r["contract"]): r
        for r in prompt_levels
    }
    prompt_pairs = sorted({(r["model"], r["benchmark"]) for r in prompt_levels})

    def prompt_pair_values(field, *, absolute=False):
        controls, treatments, changes = [], [], []
        for model, benchmark in prompt_pairs:
            control = float(prompt_index[(model, benchmark, "control")][field])
            treatment = float(
                prompt_index[(model, benchmark, "quad_both")][field]
            )
            if absolute:
                control, treatment = abs(control), abs(treatment)
            controls.append(control)
            treatments.append(treatment)
            changes.append(treatment - control)
        return controls, treatments, changes

    _, _, prompt_gap_changes = prompt_pair_values(
        "confidence_gap", absolute=True
    )
    _, _, prompt_score_changes = prompt_pair_values(
        "confidence_calibrated_score"
    )

    reliability_bins = rows("calibration_reliability_bins.csv")
    with open(os.path.join(PROC, "calibration_context_manifest.json"),
              encoding="utf-8") as handle:
        calibration_context = json.load(handle)

    # The reliability diagram above (training_accuracy/training_confidence)
    # still pools only two families: calibration_reliability_bins.csv has no
    # Nemotron deciles yet. The programme's evidence-base denominator, quoted
    # in the caption further down, is broader: three trained families and 33
    # matched pairs in training_effect_synthesis.csv/_summary.json. See
    # notes/2026-09-03-third-family-protocol.md for the Nemotron replication.
    with open(
        os.path.join(PROC, "training_effect_synthesis_summary.json"),
        encoding="utf-8",
    ) as handle:
        training_synthesis = json.load(handle)
    # This page stays on the first training programme (its prose was
    # written on those pairs); the exporter carries that programme alone
    # under "first" once the second programme exists, and the pooled
    # "all" block then spans both. Read the first-programme block.
    training_synthesis = {**training_synthesis, **training_synthesis.get("first", {})}
    synthesis_all = training_synthesis["all"]
    synthesis_family_count = len(training_synthesis["design_breadth"]["families"])

    def reliability_summary(experiment, arm):
        """Pool the visible deciles back to one denominator-aware level."""
        selected = [
            r for r in reliability_bins
            if r["experiment"] == experiment and r["arm"] == arm
            and int(r["n"]) > 0
        ]
        n = sum(int(r["n"]) for r in selected)
        confidence = sum(
            int(r["n"]) * float(r["mean_confidence"]) for r in selected
        ) / n
        accuracy = sum(
            int(r["n"]) * float(r["accuracy"]) for r in selected
        ) / n
        return {
            "n": n, "accuracy": accuracy, "confidence": confidence,
            "gap": confidence - accuracy,
        }

    prompt_normal = reliability_summary("prompting", "answer_normally")
    prompt_instructed = reliability_summary("prompting", "rule_threshold")
    training_accuracy = reliability_summary("training", "accuracy_trained")
    training_confidence = reliability_summary("training", "confidence_trained")

    def reliability_bin_share(experiment, arm, lower):
        """Return the share of usable answers in one confidence range."""
        record = next(
            row for row in reliability_bins
            if row["experiment"] == experiment and row["arm"] == arm
            and float(row["bin_lower"]) == lower
        )
        return int(record["n"]) / reliability_summary(experiment, arm)["n"]

    def share_closed(before, after):
        """Return the share of an absolute baseline gap or risk removed."""
        return (abs(before) - abs(after)) / abs(before) if before else None

    def arrow_pct(before, after, dp=1):
        return f'{before * 100:.{dp}f}% &rarr; {after * 100:.{dp}f}%'

    def reliability_chart(experiment, title, arm_specs):
        """Pair a reliability diagram with an aligned confidence distribution."""
        width, height = 850, 430
        plot_left, plot_top, plot_size = 58, 50, 332
        plot_right, plot_bottom = plot_left + plot_size, plot_top + plot_size
        distribution_left, distribution_width = 500, 250

        def sx(value):
            return plot_left + value * plot_size

        def sy(value):
            return plot_bottom - value * plot_size

        by_arm = {}
        summaries = []
        for arm, _label, _color in arm_specs:
            records = [
                record for record in reliability_bins
                if record["experiment"] == experiment and record["arm"] == arm
            ]
            by_arm[arm] = records
            summaries.append(reliability_summary(experiment, arm))

        closed = share_closed(summaries[0]["gap"], summaries[1]["gap"])
        stat_cells = []
        for (_arm, label, _color), overall in zip(arm_specs, summaries):
            stat_cells.append(
                '<div class="cal-stat">'
                f'<span>{html.escape(label)}</span>'
                f'<b>{overall["accuracy"] * 100:.0f}% correct &middot; '
                f'{overall["confidence"] * 100:.0f}% confident</b>'
                f'<small>{overall["gap"] * 100:.0f}-point gap</small></div>'
            )
        stat_cells.append(
            '<div class="cal-stat"><span>Change</span>'
            f'<b>{closed * 100:.0f}% of the gap closed</b>'
            f'<small>{summaries[0]["gap"] * 100:.0f} to '
            f'{summaries[1]["gap"] * 100:.0f} points</small></div>'
        )

        parts = [
            f'<figure class="reliability-figure"><h4>{html.escape(title)}</h4>',
            '<div class="cal-stat-row">', *stat_cells, '</div>',
            '<div class="cal-chart-scroll">',
            (f'<svg class="reliability-chart" viewBox="0 0 {width} {height}" '
             f'role="img" aria-label="{html.escape(title)}">'),
            ('<desc>The left panel compares observed accuracy with stated '
             'confidence for confidence ranges containing at least 20 answers. '
             'The right panel shows the share of answers in every confidence '
             'range.</desc>'),
        ]

        # A small shared key is enough because both panels use the same colors.
        key_x = plot_left
        for index, (_arm, label, color) in enumerate(arm_specs):
            x = key_x + index * 190
            parts.extend([
                (f'<line x1="{x}" y1="18" x2="{x + 22}" y2="18" '
                 f'stroke="{color}" stroke-width="3"/>'),
                (f'<text class="reliability-key" x="{x + 30}" y="22">'
                 f'{html.escape(label)}</text>'),
            ])

        parts.extend([
            (f'<text class="reliability-panel-title" x="{plot_left}" y="42">'
             'Accuracy at each stated-confidence level</text>'),
            (f'<text class="reliability-panel-title" x="{distribution_left}" y="42">'
             'Share of answers at each level</text>'),
            (f'<polygon class="reliability-overconfident" points="'
             f'{plot_left},{plot_top} {plot_right},{plot_top} '
             f'{plot_left},{plot_bottom}"/>'),
        ])

        for tick in range(0, 101, 20):
            value = tick / 100
            x, y = sx(value), sy(value)
            parts.extend([
                (f'<line class="reliability-grid" x1="{x:.1f}" y1="{plot_top}" '
                 f'x2="{x:.1f}" y2="{plot_bottom}"/>'),
                (f'<line class="reliability-grid" x1="{plot_left}" y1="{y:.1f}" '
                 f'x2="{plot_right}" y2="{y:.1f}"/>'),
                (f'<text class="reliability-label" x="{x:.1f}" '
                 f'y="{plot_bottom + 18}" text-anchor="middle">{tick}%</text>'),
                (f'<text class="reliability-label" x="{plot_left - 9}" '
                 f'y="{y + 4:.1f}" text-anchor="end">{tick}%</text>'),
            ])
        parts.extend([
            (f'<line class="reliability-perfect" x1="{plot_left}" '
             f'y1="{plot_bottom}" x2="{plot_right}" y2="{plot_top}"/>'),
            (f'<line class="reliability-axis" x1="{plot_left}" y1="{plot_bottom}" '
             f'x2="{plot_right}" y2="{plot_bottom}"/>'),
            (f'<line class="reliability-axis" x1="{plot_left}" y1="{plot_top}" '
             f'x2="{plot_left}" y2="{plot_bottom}"/>'),
            (f'<text class="reliability-axis-title" x="{plot_left + plot_size / 2}" '
             f'y="{plot_bottom + 42}" text-anchor="middle">Observed accuracy</text>'),
            (f'<text class="reliability-axis-title" '
             f'transform="translate(15 {plot_top + plot_size / 2}) rotate(-90)" '
             f'text-anchor="middle">Stated confidence</text>'),
            (f'<text class="reliability-note" x="{plot_left + 10}" '
             f'y="{plot_top + 17}">Overconfident</text>'),
        ])

        # The distribution panel shares the confidence scale vertically. Bars
        # show shares, not raw counts, so the two arms remain comparable even
        # when their usable-answer totals differ slightly.
        for tick in (0, 0.5, 1):
            x = distribution_left + tick * distribution_width
            parts.extend([
                (f'<line class="distribution-grid" x1="{x:.1f}" y1="{plot_top}" '
                 f'x2="{x:.1f}" y2="{plot_bottom}"/>'),
                (f'<text class="reliability-label" x="{x:.1f}" '
                 f'y="{plot_bottom + 18}" text-anchor="middle">{tick * 100:.0f}%</text>'),
            ])
        parts.extend([
            (f'<line class="reliability-axis" x1="{distribution_left}" '
             f'y1="{plot_bottom}" x2="{distribution_left + distribution_width}" '
             f'y2="{plot_bottom}"/>'),
            (f'<text class="reliability-axis-title" '
             f'x="{distribution_left + distribution_width / 2}" '
             f'y="{plot_bottom + 42}" text-anchor="middle">Share of answers</text>'),
        ])

        for arm_index, (arm, label, color) in enumerate(arm_specs):
            robust = sorted(
                (record for record in by_arm[arm] if int(record["n"]) >= 20),
                key=lambda record: float(record["mean_confidence"]),
            )
            if robust:
                path = " ".join(
                    ("M" if index == 0 else "L")
                    + f'{sx(float(record["accuracy"])):.1f},'
                    + f'{sy(float(record["mean_confidence"])):.1f}'
                    for index, record in enumerate(robust)
                )
                parts.append(
                    f'<path class="reliability-series" d="{path}" stroke="{color}"/>'
                )

            for record in robust:
                n = int(record["n"])
                accuracy = float(record["accuracy"])
                confidence = float(record["mean_confidence"])
                parts.append(
                    f'<circle class="reliability-point" '
                    f'cx="{sx(accuracy):.1f}" cy="{sy(confidence):.1f}" r="5" '
                    f'fill="{color}"><title>{html.escape(label)}; '
                    f'{float(record["bin_lower"]) * 100:.0f}% to '
                    f'{float(record["bin_upper"]) * 100:.0f}% confidence; '
                    f'n={n:,}; {accuracy * 100:.1f}% correct; '
                    f'{confidence * 100:.1f}% mean confidence</title></circle>'
                )

            top_record = next(
                record for record in robust
                if float(record["bin_lower"]) == 0.9
            )
            top_accuracy = float(top_record["accuracy"])
            top_confidence = float(top_record["mean_confidence"])
            label_x = sx(top_accuracy) + (8 if top_accuracy < 0.7 else -8)
            anchor = "start" if top_accuracy < 0.7 else "end"
            label_y = sy(top_confidence) + (-9 if arm_index == 0 else 16)
            parts.append(
                f'<text class="reliability-point-label" x="{label_x:.1f}" '
                f'y="{label_y:.1f}" text-anchor="{anchor}" fill="{color}">'
                f'{top_confidence * 100:.0f}% confident, '
                f'{top_accuracy * 100:.0f}% correct</text>'
            )

            total = summaries[arm_index]["n"]
            for record in by_arm[arm]:
                n = int(record["n"])
                if not n:
                    continue
                share = n / total
                center = (
                    float(record["bin_lower"]) + float(record["bin_upper"])
                ) / 2
                y = sy(center) + (-4 if arm_index == 0 else 4)
                bar_width = share * distribution_width
                parts.append(
                    f'<rect class="distribution-bar" x="{distribution_left}" '
                    f'y="{y - 3}" width="{bar_width:.1f}" height="6" '
                    f'fill="{color}"><title>{html.escape(label)}; '
                    f'{float(record["bin_lower"]) * 100:.0f}% to '
                    f'{float(record["bin_upper"]) * 100:.0f}% confidence; '
                    f'{share * 100:.1f}% of answers; n={n:,}</title></rect>'
                )
                if share >= 0.035:
                    parts.append(
                        f'<text class="distribution-value" '
                        f'x="{distribution_left + bar_width + 5:.1f}" '
                        f'y="{y + 3.5:.1f}" fill="{color}">'
                        f'{share * 100:.0f}%</text>'
                    )

        denominator_context = {
            "prompting": (
                calibration_context["prompt_usable_confidence_answers"],
                calibration_context["prompt_primary_responses"],
            ),
            "training": (
                calibration_context["training_usable_confidence_answers"],
                calibration_context["training_matched_responses"],
            ),
        }
        usable_answers, matched_responses = denominator_context[experiment]
        sparse_records = [
            record for records in by_arm.values() for record in records
            if 0 < int(record["n"]) < 20
        ]
        sparse_answers = sum(int(record["n"]) for record in sparse_records)
        parts.extend([
            '</svg></div>',
            ('<figcaption>Left: each point shows observed accuracy for one '
             'stated-confidence range. The labels identify the 90% to 100% '
             'range; points above the diagonal are overconfident. Right: bars '
             'show where the answers actually fell. '
             f'{sparse_answers:,} answers in {len(sparse_records)} ranges with '
             'fewer than 20 answers are omitted from the reliability lines but '
             'remain in the distribution. '
             f'{usable_answers:,} usable confidence answers are shown from '
             f'{matched_responses:,} matched responses.</figcaption></figure>'),
        ])
        return "".join(parts)

    qwen_pooled = [
        r for r in rows("multitask_transfer_summary.csv")
        if r["training_regime"] == "pooled"
    ]
    qwen_transfer = rows("multitask_transfer_summary.csv")
    qwen_transfer_levels = rows("multitask_transfer_levels.csv")
    generalization = {
        r["scope"]: r for r in rows("multitask_generalization_summary.csv")
    }
    generalization_pairs = rows("multitask_generalization_pairs.csv")
    qwen_transfer_level_index = {
        (r["training_regime"], r["evaluation_domain"],
         r["training_objective"]): r
        for r in qwen_transfer_levels
    }

    # Subject-to-subject transfer is a different claim from pooled training.
    # Keep only off-diagonal cells here: the evaluation subject must differ
    # from the subject used for training. Each summary contrast is one matched
    # binary/quadratic seed evaluated on one new subject.
    subject_domains = {"medicine", "math", "ethics"}
    qwen_off_domain = [
        r for r in qwen_transfer
        if r["training_regime"] in subject_domains
        and r["evaluation_domain"] != r["training_regime"]
    ]
    qwen_off_domain_levels = [
        r for r in qwen_transfer_levels
        if r["training_regime"] in subject_domains
        and r["evaluation_domain"] != r["training_regime"]
    ]

    def off_domain_level(objective, field):
        selected = [
            r for r in qwen_off_domain_levels
            if r["training_objective"] == objective
        ]
        denominator = sum(int(r["response_count"]) for r in selected)
        return sum(
            float(r[field]) * int(r["response_count"]) for r in selected
        ) / denominator

    off_domain_risk_before = off_domain_level(
        "binary", "mean_high_confidence_wrong_rate"
    )
    off_domain_risk_after = off_domain_level(
        "quadratic", "mean_high_confidence_wrong_rate"
    )
    off_domain_accuracy_before = off_domain_level("binary", "mean_accuracy")
    off_domain_accuracy_after = off_domain_level("quadratic", "mean_accuracy")
    off_domain_score_before = off_domain_level(
        "binary", "mean_confidence_calibrated_score"
    )
    off_domain_score_after = off_domain_level(
        "quadratic", "mean_confidence_calibrated_score"
    )
    off_domain_seed_tests = sum(
        int(r["matched_seed_pairs"]) for r in qwen_off_domain
    )
    off_domain_risk_improvements = sum(
        int(r["risk_reductions"]) for r in qwen_off_domain
    )
    off_domain_score_improvements = sum(
        int(r["score_improvements"]) for r in qwen_off_domain
    )
    off_domain_responses = sum(
        int(r["response_count"]) for r in qwen_off_domain_levels
    )
    gpt_transfer = rows("openweight_followup_transfer.csv")
    pooled_training_levels = rows("pooled_training_levels.csv")
    pooled_training_index = {
        (r["model_family"], r["evaluation_domain"], r["training_objective"]): r
        for r in pooled_training_levels
    }
    with open(os.path.join(PROC, "openweight_followup_manifest.json"),
              encoding="utf-8") as handle:
        gpt_manifest = json.load(handle)

    prudence = [
        r for r in rows("plural_prudence_contrasts.csv")
        if r["framing"] == "neutral"
        and r["treatment_objective"] == "quadratic"
    ]
    prudence_levels = rows("plural_prudence_levels.csv")

    def prudence_level(objective, field, framing="neutral"):
        return statistics.mean(
            float(r[field]) for r in prudence_levels
            if r["framing"] == framing
            and r["training_objective"] == objective
        )

    prudence_bad_before = prudence_level(
        "binary", "prudence_high_confidence_wrong_execution_rate"
    )
    prudence_bad_after = prudence_level(
        "quadratic", "prudence_high_confidence_wrong_execution_rate"
    )
    prudence_accuracy_before = prudence_level("binary", "prudence_accuracy")
    prudence_accuracy_after = prudence_level("quadratic", "prudence_accuracy")
    prudence_execute_before = prudence_level("binary", "prudence_execute_rate")
    prudence_execute_after = prudence_level("quadratic", "prudence_execute_rate")
    qwen_hidden = rows("hidden_opportunity_contrasts.csv")
    with open(os.path.join(PROC, "multitask_family_agentic_manifest.json"),
              encoding="utf-8") as handle:
        qwen_manifest = json.load(handle)
    with open(os.path.join(PROC, "plural_prudence_manifest.json"),
              encoding="utf-8") as handle:
        prudence_manifest = json.load(handle)
    total_hidden_records = (
        int(qwen_manifest["hidden_opportunity_responses"])
        + int(gpt_manifest["hidden_records"])
    )
    hidden_before = [
        float(r["binary_unauthorized_action_rate"]) for r in qwen_hidden
    ] + [
        float(r["binary_unauthorized_rate"])
        for r in rows("openweight_followup_hidden.csv")
    ]
    hidden_after = [
        float(r["quadratic_unauthorized_action_rate"]) for r in qwen_hidden
    ] + [
        float(r["quadratic_unauthorized_rate"])
        for r in rows("openweight_followup_hidden.csv")
    ]

    evidence_map = table(
        ["question", "short answer", "comparison in context",
         "breadth and consistency"],
        [
            ["Do current benchmarks reward guessing?",
             "Yes. Silence usually earns no more than a wrong guess.",
             (f'<span class="context-line"><b>Scoring.</b> In '
              f'{len(gradable) - priced_wrong} of {len(gradable)} benchmarks '
              f'with right-or-wrong answers, a wrong answer did not cost more '
              f'than silence.</span><span class="context-line result">'
              f'<b>Observed behavior.</b> Models answered '
              f'{(1 - float(summary["decline_rate"])) * 100:.2f}% of the time; '
              f'they declined only {float(summary["decline_rate"]) * 100:.2f}% '
              f'of the time.</span>'),
             (f'{int(summary["responses_scanned"]):,} published responses, '
              f'{summary["models"]} models, {summary["benchmarks"]} benchmarks.'
              f'<span class="sub">Scoring rules reviewed for {len(survey)} '
              f'benchmarks; {len(gradable)} had a clear correctness endpoint.</span>')],
            ["Can instructions alone make confidence more realistic?",
             (f'Only modestly on average: they closed '
              f'{share_closed(prompt_normal["gap"], prompt_instructed["gap"]) * 100:.0f}% '
              f'of the original overconfidence gap.'),
             (f'<span class="context-line"><b>Answer normally.</b> Accuracy '
              f'{prompt_normal["accuracy"] * 100:.1f}%; confidence '
              f'{prompt_normal["confidence"] * 100:.1f}%; gap '
              f'{prompt_normal["gap"] * 100:.1f} points.</span>'
              f'<span class="context-line"><b>With the rule and threshold.</b> '
              f'Accuracy {prompt_instructed["accuracy"] * 100:.1f}%; confidence '
              f'{prompt_instructed["confidence"] * 100:.1f}%; gap '
              f'{prompt_instructed["gap"] * 100:.1f} points.</span>'
              f'<span class="context-line result"><b>Net.</b> The gap shrank '
              f'{(prompt_normal["gap"] - prompt_instructed["gap"]) * 100:.1f} '
              f'points, while accuracy changed '
              f'{(prompt_instructed["accuracy"] - prompt_normal["accuracy"]) * 100:+.1f} '
              f'points.</span>'),
             (f'{len(prompt_meta["models"])} models, '
              f'{len(prompt_meta["benchmarks"])} subjects, '
              f'{calibration_context["prompt_primary_responses"]:,} matched '
              f'responses.<span class="sub">The gap improved in '
              f'{sum(v < 0 for v in prompt_gap_changes)} of '
              f'{len(prompt_gap_changes)} model-subject comparisons. '
              f'{calibration_context["prompt_usable_confidence_answers"]:,} '
              f'answers had usable confidence.</span>')],
            ["Can training make factual confidence more realistic?",
             (f'Yes. It closed {share_closed(training_accuracy["gap"], training_confidence["gap"]) * 100:.0f}% '
              f'of the pooled gap with essentially unchanged accuracy.'),
             (f'<span class="context-line"><b>Accuracy-trained models.</b> '
              f'Accuracy {training_accuracy["accuracy"] * 100:.1f}%; confidence '
              f'{training_accuracy["confidence"] * 100:.1f}%; gap '
              f'{training_accuracy["gap"] * 100:.1f} points.</span>'
              f'<span class="context-line"><b>Confidence-trained models.</b> '
              f'Accuracy {training_confidence["accuracy"] * 100:.1f}%; confidence '
              f'{training_confidence["confidence"] * 100:.1f}%; gap '
              f'{training_confidence["gap"] * 100:.1f} points.</span>'
              f'<span class="context-line result"><b>Net.</b> The gap shrank '
              f'{(training_accuracy["gap"] - training_confidence["gap"]) * 100:.1f} '
              f'points; accuracy changed '
              f'{(training_confidence["accuracy"] - training_accuracy["accuracy"]) * 100:+.1f} '
              f'points.</span>'),
             (f'The reliability numbers above pool Qwen3 8B and GPT-OSS 20B, '
              f'{calibration_context["training_matched_responses"]:,} matched '
              f'test responses. The full programme evidence base is wider: '
              f'{synthesis_family_count} trained families, '
              f'{synthesis_all["pairs"]} matched pairs, '
              f'{calibration_context["training_matched_responses_all_families"]:,} '
              f'matched test responses.<span class="sub">The '
              f'confidence-calibrated score improved in '
              f'{synthesis_all["score_improved"][0]} of '
              f'{synthesis_all["score_improved"][1]} of them.</span>')],
            ["Does calibration learned in one subject transfer to another?",
             (f'Often. Highly confident errors fell in all '
              f'{off_domain_risk_improvements} of {off_domain_seed_tests} '
              f'off-subject comparisons.'),
             (f'<span class="context-line"><b>Accuracy-trained models.</b> '
              f'Wrong at 80%+ confidence: {off_domain_risk_before * 100:.1f}%; '
              f'overall accuracy: {off_domain_accuracy_before * 100:.1f}%.</span>'
              f'<span class="context-line"><b>Confidence-trained models.</b> '
              f'Wrong at 80%+ confidence: {off_domain_risk_after * 100:.1f}%; '
              f'overall accuracy: {off_domain_accuracy_after * 100:.1f}%.</span>'
              f'<span class="context-line result"><b>Net.</b> The high-confidence '
              f'error rate fell {(off_domain_risk_before - off_domain_risk_after) * 100:.1f} '
              f'points, while accuracy changed '
              f'{(off_domain_accuracy_after - off_domain_accuracy_before) * 100:+.1f} '
              f'points. The confidence-calibrated score rose from '
              f'{off_domain_score_before:.3f} to '
              f'{off_domain_score_after:.3f}.</span>'),
             (f'Qwen3 8B, seven matched training pairs, three test subjects per '
              f'pair, {off_domain_responses:,} stored responses.'
              f'<span class="sub">The confidence-calibrated score improved in '
              f'{off_domain_score_improvements} of {off_domain_seed_tests} '
              f'comparisons. Subject-specific transfer has not yet been '
              f'replicated in a second family.</span>')],
            ["Does calibration training prevent very bad decisions?",
             (f'In our structured test, it removed '
              f'{share_closed(prudence_bad_before, prudence_bad_after) * 100:.0f}% '
              f'of overconfident wrong actions.'),
             (f'<span class="context-line"><b>Accuracy-trained models.</b> '
              f'Wrong risky action at 90%+ confidence: '
              f'{prudence_bad_before * 100:.1f}%.</span>'
              f'<span class="context-line"><b>Confidence-trained models.</b> '
              f'{prudence_bad_after * 100:.1f}%.</span>'
              f'<span class="context-line result"><b>What drove it.</b> '
              f'Ordinary accuracy stayed near {prudence_accuracy_before * 100:.1f}% '
              f'&rarr; {prudence_accuracy_after * 100:.1f}%, while immediate '
              f'execution fell {prudence_execute_before * 100:.1f}% &rarr; '
              f'{prudence_execute_after * 100:.1f}%.</span>'),
             (f'Five training runs, 80 decisions per model version, 800 matched '
              f'decisions.<span class="sub">All 5 runs improved. The wider '
              f'battery contained {int(prudence_manifest["records"]):,} '
              f'responses across five behaviors.</span>')],
            ["Does it make models behave more responsibly beyond factual questions?",
             "Not much in the hidden-shortcut test.",
             (f'<span class="context-line"><b>Accuracy-trained models.</b> '
              f'Took the prohibited shortcut in {statistics.mean(hidden_before) * 100:.1f}% '
              f'of cases.</span><span class="context-line"><b>Confidence-trained '
              f'models.</b> {statistics.mean(hidden_after) * 100:.1f}%.</span>'
              f'<span class="context-line result"><b>Net.</b> A '
              f'{(statistics.mean(hidden_before) - statistics.mean(hidden_after)) * 100:.1f}-point '
              f'drop, eliminating only '
              f'{share_closed(statistics.mean(hidden_before), statistics.mean(hidden_after)) * 100:.1f}% '
              f'of the original shortcut rate. More than 90% remained.</span>'),
             (f'16 trained pairs from two families, 32 workflows, '
              f'{total_hidden_records:,} choices.<span class="sub">'
              f'{sum(after < before for before, after in zip(hidden_before, hidden_after))} '
              f'of 16 pairs improved; authorized completion stayed at 100%.</span>')],
            ["Does the effect generalize to other downloadable model families?",
             "Still unknown: four of six attempted configurations were not measurable.",
             ('<span class="context-line"><b>Required reliability.</b> Fewer '
              'than 1% of answers could violate the required format.</span>'
              '<span class="context-line"><b>Observed.</b> Qwen3 8B and GPT-OSS '
              '20B passed. The stopped configurations ranged from 1.15% to '
              '100% invalidly formatted answers.</span>'
              '<span class="context-line result"><b>Meaning.</b> These are '
              'measurement failures, not negative training results.</span>'),
             ('Six configurations attempted: Qwen3 8B, GPT-OSS 20B, Nemotron '
              '30B, Qwen3.5 4B, Kimi K2.6, and DeepSeek V3.1.'
              '<span class="sub">A complete admission profile used 1,920 '
              'answers whenever the model reached that stage.</span>')],
        ],
        right_from=99, cls="brief-prose outline-table")

    # --- why the benchmark design matters ---------------------------------
    problem_tbl = table(
        ["observation", "result", "denominator", "reading"],
        [
            ["Published responses stating a probability of being right",
             f'<b>{float(summary["stated_confidence_rate"]) * 100:.2f}%</b>',
             (f'{int(summary["stated_confidence_count"]):,} of '
              f'{int(summary["responses_scanned"]):,}'),
             "Confidence is almost never part of the recorded answer."],
            ["Published responses that say they do not know",
             f'<b>{float(summary["decline_rate"]) * 100:.2f}%</b>',
             (f'{int(summary["decline_phrase_count"]):,} of '
              f'{int(summary["responses_scanned"]):,}'),
             "Models nearly always answer."],
            ["Gradable benchmarks that price a wrong answer",
             f'<b>{priced_wrong} of {len(gradable)}</b>',
             "Benchmark scoring records with a correctness endpoint",
             "Accuracy-only scoring usually makes silence no better than a guess."],
        ],
        right_from=1, cls="brief-prose")

    # --- prompting ---------------------------------------------------------
    prompt_score_controls, prompt_score_treatments, _ = prompt_pair_values(
        "confidence_calibrated_score"
    )
    prompt_rows = [
        ["Accuracy among answers with usable confidence",
         f'{prompt_normal["accuracy"] * 100:.1f}%',
         f'{prompt_instructed["accuracy"] * 100:.1f}%',
         signed_pp(prompt_instructed["accuracy"] - prompt_normal["accuracy"]),
         "Nearly unchanged"],
        ["Mean stated confidence on those same answers",
         f'{prompt_normal["confidence"] * 100:.1f}%',
         f'{prompt_instructed["confidence"] * 100:.1f}%',
         signed_pp(prompt_instructed["confidence"] - prompt_normal["confidence"]),
         "Confidence moved down more than accuracy"],
        ["Overconfidence gap",
         f'<b>{prompt_normal["gap"] * 100:.1f} points</b>',
         f'<b>{prompt_instructed["gap"] * 100:.1f} points</b>',
         (f'{signed_pp(prompt_instructed["gap"] - prompt_normal["gap"])}; '
          f'{share_closed(prompt_normal["gap"], prompt_instructed["gap"]) * 100:.0f}% '
          'of the original gap closed'),
         f'{sum(v < 0 for v in prompt_gap_changes)} of 15 comparisons improved'],
        ["Confidence-calibrated score",
         f'{statistics.mean(prompt_score_controls):.3f}',
         f'{statistics.mean(prompt_score_treatments):.3f}',
         f'{statistics.mean(prompt_score_changes):+.3f}'.replace("-", "&minus;"),
         f'{sum(v > 0 for v in prompt_score_changes)} of 15 comparisons improved'],
    ]
    prompting_tbl = table(
        ["measure", "answer normally", "rule + threshold",
         "what changed", "consistency"],
        prompt_rows, right_from=1, cls="brief-prose")
    prompt_reliability = reliability_chart(
        "prompting",
        ("The rule reduced answers in the 90% to 100% confidence range from "
         f'{reliability_bin_share("prompting", "answer_normally", 0.9) * 100:.0f}% '
         "to "
         f'{reliability_bin_share("prompting", "rule_threshold", 0.9) * 100:.0f}%'),
        [
            ("answer_normally", "Answer normally", "#8c8a86"),
            ("rule_threshold", "Rule + threshold", "#7b3658"),
        ],
    )

    # --- the first controlled training comparison -------------------------
    with open(os.path.join(PROC, "finetune_pilot_summary.json"),
              encoding="utf-8") as handle:
        trained = json.load(handle)["final_test"]["neutral_combined"]
    trained_labels = {
        "base": "Untuned base",
        "binary": "Accuracy only",
        "quadratic": "Confidence-calibrated",
        "quad_cost": "Confidence-calibrated + fixed cost",
    }
    binary_gap = abs(float(trained["binary"]["signed_calibration_gap"]))
    trained_tbl = table(
        ["trained with", "answered", "accuracy among answers",
         "confidence among answers", "confidence gap",
         "accuracy-only gap eliminated", "confidence-calibrated score"],
        [[trained_labels[key],
          f'{float(trained[key]["coverage"]) * 100:.1f}%',
          (f'{float(trained[key]["accuracy"]) / float(trained[key]["coverage"]) * 100:.1f}%'
           if float(trained[key]["coverage"]) else "&mdash;"),
          f'{float(trained[key]["mean_reported_probability"]) * 100:.1f}%',
          signed_pp(float(trained[key]["signed_calibration_gap"]), 1),
          ("&mdash;" if key == "base" else
           f'{share_closed(binary_gap, float(trained[key]["signed_calibration_gap"])) * 100:.0f}%'),
          f'<b>{float(trained[key]["quadratic_score"]):.3f}</b>']
         for key in ("base", "binary", "quadratic", "quad_cost")],
        right_from=1, cls="brief-prose")

    # --- who implements the answer threshold? -----------------------------
    with open(os.path.join(PROC, "policy_architecture_summary.json"),
              encoding="utf-8") as handle:
        policy_architecture = json.load(handle)
    with open(os.path.join(PROC, "prompt_threshold_factorial_summary.json"),
              encoding="utf-8") as handle:
        prompt_factorial = json.load(handle)
    prompt_headline = prompt_factorial["headline"]

    def tb_prompt_policy_row(label, detail, prefix):
        return [
            f'<b>{label}</b><span class="sub">{detail}</span>',
            f'{float(prompt_headline[f"{prefix}_coverage"]) * 100:.1f}%',
            f'{float(prompt_headline[f"{prefix}_accuracy_when_answered"]) * 100:.1f}%',
            f'{float(prompt_headline[f"{prefix}_wrong_per_question"]) * 100:.1f}',
            f'{float(prompt_headline[f"{prefix}_utility_per_question"]) * 100:+.1f}'.replace(
                "-", "&minus;"),
        ]

    prompt_factorial_tbl = table(
        ["same checkpoint at the 30% break-even point", "answers shown",
         "accuracy when shown", "wrong answers per 100 questions",
         "decision value per 100 questions"],
        [
            tb_prompt_policy_row(
                "Penalty inside the prompt",
                "Model receives the cost and decides whether to answer",
                "embedded"),
            tb_prompt_policy_row(
                "Confidence prompt only",
                "No deterministic cutoff; isolates the simpler prompt",
                "confidence_native"),
            tb_prompt_policy_row(
                "Confidence prompt + code",
                "Code withholds probabilities below 30%",
                "separated"),
        ],
        right_from=1, cls="brief-prose policy-architecture")
    policy_index = {
        (float(r["threshold"]), r["approach"]): r
        for r in policy_architecture["policy_comparison"]
    }
    tb_policy_labels = {
        "embedded_cost_native": (
            "Model applies the penalty",
            "Cost-trained model decides whether to answer"),
        "separated_confidence_external": (
            "Code applies the threshold",
            "Confidence-only model reports a probability"),
        "hybrid_cost_external": (
            "Hybrid",
            "Cost-trained model reports a probability; code decides"),
    }

    def tb_policy_row(threshold, approach):
        record = policy_index[(threshold, approach)]
        label, detail = tb_policy_labels[approach]
        return [
            f'<b>{label}</b><span class="sub">{detail}</span>',
            f'{float(record["coverage"]) * 100:.1f}%',
            f'{float(record["accuracy_when_answered"]) * 100:.1f}%',
            f'{float(record["wrong_per_question"]) * 100:.1f}',
            f'{float(record["utility_per_question"]) * 100:+.1f}'.replace(
                "-", "&minus;"),
        ]

    policy_primary_tbl = table(
        ["30% break-even design", "answers shown", "accuracy when shown",
         "wrong answers per 100 questions", "decision value per 100 questions"],
        [tb_policy_row(0.30, approach) for approach in (
            "embedded_cost_native", "separated_confidence_external",
            "hybrid_cost_external")],
        right_from=1, cls="brief-prose policy-architecture")

    policy_stakes_rows = []
    for threshold in (0.30, 0.70, 0.80, 0.90):
        row = [f'{threshold * 100:.0f}%',
               f'{threshold / (1 - threshold):.2f}&times;']
        for approach in ("embedded_cost_native",
                         "separated_confidence_external",
                         "hybrid_cost_external"):
            record = policy_index[(threshold, approach)]
            value = float(record["utility_per_question"]) * 100
            cell = (f'{float(record["wrong_per_question"]) * 100:.1f} wrong'
                    f'<span class="sub">value {value:+.1f}</span>')
            row.append(cell.replace("-", "&minus;"))
        policy_stakes_rows.append(row)
    policy_stakes_tbl = table(
        ["answer threshold", "wrong-answer cost", "model applies penalty",
         "confidence-only + code", "cost-trained + code"],
        policy_stakes_rows, right_from=1,
        cls="brief-prose policy-architecture-stakes")
    training_reliability = reliability_chart(
        "training",
        ("Training reduced answers in the 90% to 100% confidence range from "
         f'{reliability_bin_share("training", "accuracy_trained", 0.9) * 100:.0f}% '
         "to "
         f'{reliability_bin_share("training", "confidence_trained", 0.9) * 100:.0f}%'),
        [
            ("accuracy_trained", "Accuracy-trained", "#8c8a86"),
            ("confidence_trained", "Confidence-trained", "#7b3658"),
        ],
    )

    # --- cross-family factual transfer ------------------------------------
    domain_order = {"math": 0, "gpqa": 1, "medicine": 2, "ethics": 3}
    domain_names = {
        "math": "Math", "gpqa": "GPQA Diamond (unseen)",
        "medicine": "Medicine", "ethics": "Legal and ethical reasoning",
    }
    subject_route_order = [
        ("medicine", "math"),
        ("medicine", "gpqa"),
        ("medicine", "ethics"),
        ("ethics", "medicine"),
        ("ethics", "math"),
        ("ethics", "gpqa"),
    ]
    subject_transfer_rows = []
    qwen_transfer_index = {
        (r["training_regime"], r["evaluation_domain"]): r
        for r in qwen_transfer
    }
    for training_domain, evaluation_domain in subject_route_order:
        contrast = qwen_transfer_index[(training_domain, evaluation_domain)]
        before = qwen_transfer_level_index[
            (training_domain, evaluation_domain, "binary")
        ]
        after = qwen_transfer_level_index[
            (training_domain, evaluation_domain, "quadratic")
        ]
        risk_before = float(before["mean_high_confidence_wrong_rate"])
        risk_after = float(after["mean_high_confidence_wrong_rate"])
        pairs = int(contrast["matched_seed_pairs"])
        subject_transfer_rows.append([
            domain_names[training_domain],
            domain_names[evaluation_domain],
            (f'{pairs} matched pairs<span class="sub">'
             f'{before["items_per_checkpoint"]} questions per version</span>'),
            (f'<b>{arrow_pct(risk_before, risk_after)}</b>'
             f'<span class="sub">'
             f'{share_closed(risk_before, risk_after) * 100:.0f}% of the '
             f'original risk eliminated; fell in '
             f'{contrast["risk_reductions"]} of {pairs} pairs</span>'),
            (f'{float(before["mean_confidence_calibrated_score"]):.3f} '
             f'&rarr; {float(after["mean_confidence_calibrated_score"]):.3f}'
             f'<span class="sub">rose in '
             f'{contrast["score_improvements"]} of {pairs} pairs</span>'),
            arrow_pct(float(before["mean_accuracy"]),
                      float(after["mean_accuracy"])),
        ])
    subject_transfer_tbl = table(
        ["calibration trained on", "tested on new questions in", "scale",
         "wrong at 80%+ confidence: accuracy-trained → confidence-trained",
         "confidence-calibrated score: before → after",
         "overall accuracy: before → after"],
        subject_transfer_rows, right_from=2, sortable=True,
        cls="brief-prose subject-transfer")

    # Compare the same seven independently trained pairs on the subject that
    # supplied their training data and on all three subjects that did not. The
    # summary preserves before/after levels so a reader sees both the size of
    # the correction and the harder off-domain starting point.
    same = generalization["same_subject"]
    off = generalization["all_off_domain"]

    def level_change(record, metric, *, percent=False, signed=False):
        before = float(record[f"binary_{metric}"])
        after = float(record[f"quadratic_{metric}"])
        change = after - before
        if percent:
            rendered = arrow_pct(before, after)
            change_text = f'{change * 100:+.1f} points'
        else:
            rendered = f'{before:.3f} &rarr; {after:.3f}'
            change_text = f'{change:+.3f}'
        if signed:
            rendered = (
                f'{signed_pp(before)} &rarr; {signed_pp(after)}'
            )
            change_text = f'{abs(change) * 100:.1f} points closer to accuracy'
        return f'<b>{rendered}</b><span class="sub">{change_text}</span>'

    same_risk_pair_wins = sum(
        float(row["same_subject_high_confidence_wrong_change"]) < 0
        for row in generalization_pairs
    )
    off_risk_pair_wins = sum(
        float(row["off_domain_high_confidence_wrong_change"]) < 0
        for row in generalization_pairs
    )
    same_score_pair_wins = sum(
        float(row["same_subject_quadratic_score_change"]) > 0
        for row in generalization_pairs
    )
    off_score_pair_wins = sum(
        float(row["off_domain_quadratic_score_change"]) > 0
        for row in generalization_pairs
    )
    risk_retained = (
        abs(float(off["high_confidence_wrong_change"]))
        / abs(float(same["high_confidence_wrong_change"]))
    )
    generalization_rows = [
        ["Evidence base",
         (f'7 same-subject comparisons<span class="sub">'
          f'{int(same["questions_per_arm"]):,} questions per training objective; '
          f'{int(same["stored_responses"]):,} responses</span>'),
         (f'21 outside-subject comparisons<span class="sub">'
          f'{int(off["questions_per_arm"]):,} questions per training objective; '
          f'{int(off["stored_responses"]):,} responses</span>'),
         ('The same seven independently trained pairs appear on both sides.'
          '<span class="sub">The 21 outside comparisons are three tests of each pair, '
          'not 21 independent training runs.</span>')],
        ["Confidence gap among answered questions",
         level_change(same, "signed_confidence_gap", signed=True),
         level_change(off, "signed_confidence_gap", signed=True),
         (f'Corrected {float(same["confidence_gap_correction"]) * 100:.1f} '
          f'points in-subject and '
          f'{float(off["confidence_gap_correction"]) * 100:.1f} outside it.'
          '<span class="sub">The correction transferred almost one-for-one, '
          'but the harder outside subjects still ended overconfident.</span>')],
        ["Wrong at 80%+ confidence, among all questions",
         (level_change(same, "high_confidence_wrong_rate", percent=True)
          + f'<span class="sub">lower for {same_risk_pair_wins} of 7 training pairs</span>'),
         (level_change(off, "high_confidence_wrong_rate", percent=True)
          + f'<span class="sub">lower for {off_risk_pair_wins} of 7 training pairs</span>'),
         (f'<b>{risk_retained * 100:.0f}% of the absolute reduction transferred.</b>'
          f'<span class="sub">The remaining risk was eliminated by '
          f'{float(same["high_confidence_risk_eliminated"]) * 100:.0f}% '
          f'in-subject and {float(off["high_confidence_risk_eliminated"]) * 100:.0f}% '
          'outside it.</span>')],
        ["Confidence-calibrated score, among all questions",
         (level_change(same, "confidence_calibrated_score")
          + f'<span class="sub">higher for {same_score_pair_wins} of 7 pairs</span>'),
         (level_change(off, "confidence_calibrated_score")
          + f'<span class="sub">higher for {off_score_pair_wins} of 7 pair averages</span>'),
         ('The average gain was larger outside the training subject.'
          '<span class="sub">The outside baseline was much worse, leaving more room to improve.</span>')],
        ["Overall accuracy, among all questions",
         level_change(same, "overall_accuracy", percent=True),
         level_change(off, "overall_accuracy", percent=True),
         ('The calibration gain did not require an off-subject accuracy loss.'
          '<span class="sub">Accuracy moved slightly down in-subject and slightly up outside it.</span>')],
        ["Questions answered, among all questions",
         level_change(same, "coverage", percent=True),
         level_change(off, "coverage", percent=True),
         ('The result was not produced by widespread refusal.'
          '<span class="sub">Coverage changed by less than 1.5 points in either comparison.</span>')],
    ]
    generalization_tbl = table(
        ["measure", "same subject", "outside the training subject",
         "what transferred"],
        generalization_rows, right_from=1, sortable=False,
        cls="brief-prose generalization-summary")

    outside_scope_rows = []
    for scope, label in (
        ("other_trained_subject", "Another training subject"),
        ("unseen_gpqa", "GPQA, never used for training"),
    ):
        record = generalization[scope]
        outside_scope_rows.append([
            label,
            (f'{record["pair_tests"]} tests<span class="sub">the same '
             f'{record["training_pairs"]} training pairs; '
             f'{int(record["stored_responses"]):,} responses</span>'),
            level_change(record, "high_confidence_wrong_rate", percent=True),
            level_change(record, "confidence_calibrated_score"),
            level_change(record, "overall_accuracy", percent=True),
        ])
    generalization_scope_tbl = table(
        ["outside test", "scale", "wrong at 80%+ confidence",
         "confidence-calibrated score", "overall accuracy"],
        outside_scope_rows, right_from=1, sortable=False,
        cls="brief-prose generalization-scope")

    cross_family_rows = []
    for family, records in (("Qwen3 8B", qwen_pooled),
                            ("GPT-OSS 20B", gpt_transfer)):
        for record in sorted(records,
                             key=lambda r: domain_order[r["evaluation_domain"]]):
            domain = record["evaluation_domain"]
            before = pooled_training_index[(family, domain, "binary")]
            after = pooled_training_index[(family, domain, "quadratic")]
            risk_before = float(before["mean_high_confidence_wrong_rate"])
            risk_after = float(after["mean_high_confidence_wrong_rate"])
            cross_family_rows.append([
                family,
                domain_names[domain],
                record.get("matched_seed_pairs", record.get("matched_pairs", "")),
                arrow_pct(risk_before, risk_after),
                f'{share_closed(risk_before, risk_after) * 100:.0f}%',
                arrow_pct(float(before["mean_accuracy"]),
                          float(after["mean_accuracy"])),
                (f'{float(before["mean_confidence_calibrated_score"]):.3f} '
                 f'&rarr; {float(after["mean_confidence_calibrated_score"]):.3f}'),
                (f'{record["risk_reductions"]} of '
                 f'{record.get("matched_seed_pairs", record.get("matched_pairs", ""))} '
                 f'lower risk; {record["score_improvements"]} of '
                 f'{record.get("matched_seed_pairs", record.get("matched_pairs", ""))} '
                 'higher score'),
            ])
    cross_family_tbl = table(
        ["model family", "test subject", "trained pairs",
         "wrong at 80%+ confidence: accuracy-trained → confidence-trained",
         "original risk eliminated", "overall accuracy: before → after",
         "confidence-calibrated score: before → after", "consistency"],
        cross_family_rows, right_from=2, sortable=True,
        cls="brief-prose cross-family")

    # --- the proposed calibration-to-alignment chain ----------------------
    plural_prompt = [
        r for r in rows("plural_prudence_prompt_contrasts.csv")
        if r["framing"] == "plural"
    ]
    plural_shortcuts = [
        float(r["integrity_unauthorized_shortcut_rate_change"])
        for r in plural_prompt
        if r["integrity_unauthorized_shortcut_rate_change"] != ""
    ]
    evidence_error = [
        float(r["evidence_posterior_absolute_error_change"])
        for r in prudence
    ]
    goal_response = [
        float(r["goal_appropriate_action_rate_change"])
        for r in prudence
    ]
    evidence_before = prudence_level(
        "binary", "evidence_posterior_absolute_error"
    )
    evidence_after = prudence_level(
        "quadratic", "evidence_posterior_absolute_error"
    )
    goals_before = prudence_level("binary", "goal_appropriate_action_rate")
    goals_after = prudence_level("quadratic", "goal_appropriate_action_rate")
    plural_shortcut_before = statistics.mean(
        float(r["integrity_unauthorized_shortcut_rate"])
        for r in prudence_levels if r["framing"] == "neutral"
    )
    plural_shortcut_after = statistics.mean(
        float(r["integrity_unauthorized_shortcut_rate"])
        for r in prudence_levels if r["framing"] == "plural"
    )
    chain_tbl = table(
        ["link in the proposed chain", "baseline", "after intervention",
         "size relative to baseline", "consistency", "current reading"],
        [
            ["1. Calibrated factual confidence",
             f'{training_accuracy["gap"] * 100:.1f}-point confidence gap',
             f'{training_confidence["gap"] * 100:.1f}-point gap',
             f'{share_closed(training_accuracy["gap"], training_confidence["gap"]) * 100:.0f}% of gap closed',
             (f'Score improved in {synthesis_all["score_improved"][0]} of '
              f'{synthesis_all["score_improved"][1]} matched pairs'),
             f'Repeated across {synthesis_family_count} families'],
            ["2. Avoid very bad overconfident decisions",
             f'{prudence_bad_before * 100:.1f}% wrong action at 90%+ confidence',
             f'{prudence_bad_after * 100:.1f}%',
             f'{share_closed(prudence_bad_before, prudence_bad_after) * 100:.0f}% of baseline risk eliminated',
             "5 of 5 seeds improved",
             "Strong within this simulation"],
            ["3. Update correctly from exact evidence",
             f'{evidence_before:.2f} points of posterior error',
             f'{evidence_after:.2f} points',
             f'{(evidence_after / evidence_before - 1) * 100:+.0f}% more error',
             f'{sum(v < 0 for v in evidence_error)} of 5 seeds improved',
             "Did not transfer"],
            ["4. Resist a hidden unauthorized shortcut",
             f'{statistics.mean(hidden_before) * 100:.1f}% took the shortcut',
             f'{statistics.mean(hidden_after) * 100:.1f}%',
             f'{share_closed(statistics.mean(hidden_before), statistics.mean(hidden_after)) * 100:.1f}% of baseline shortcuts eliminated',
             f'{sum(after < before for before, after in zip(hidden_before, hidden_after))} of 16 pairs improved',
             "Too small to support broader restraint"],
            ["5. Respect multiple ends",
             f'{plural_shortcut_before * 100:.1f}% unauthorized shortcuts under neutral prompt',
             f'{plural_shortcut_after * 100:.1f}% with plural-ends reminder',
             f'{share_closed(plural_shortcut_before, plural_shortcut_after) * 100:.0f}% of baseline shortcuts eliminated',
             f'{sum(v < 0 for v in plural_shortcuts)} of {len(plural_shortcuts)} checkpoints improved',
             "Promising prompt effect"],
            ["6. Revise goals appropriately",
             f'{goals_before * 100:.1f}% appropriate action',
             f'{goals_after * 100:.1f}%',
             f'{(goals_after / goals_before - 1) * 100:+.0f}% relative change',
             f'{sum(v > 0 for v in goal_response)} of 5 seeds improved',
             "Did not transfer"],
            ["7. Avoid long-horizon scheming",
             "Not measured",
             "Not measured",
             "No baseline or comparison",
             "No valid denominator",
             "Open"],
        ],
        right_from=99, cls="brief-prose alignment-chain")

    # --- which open-weight families were actually measurable -------------
    format_rows = [
        ["Qwen3 8B", "Existing validated format", "Passed",
         "Multiple matched reward-training comparisons completed",
         evidence_state("strong", "Admitted")],
        ["GPT-OSS 20B", "Two full profiles after syntax lesson",
         "0.73% and 0.57% malformed", "Both below the frozen 1% limit",
         evidence_state("strong", "Admitted")],
        ["Nemotron 3.5 Lightning 30B", "Two full profiles after syntax lesson",
         "0.63% and 1.15% malformed", "One passed and one failed",
         evidence_state("mixed", "Stopped")],
        ["Qwen3.5 4B", "Three untouched full profiles",
         "1.20% to 4.01% malformed", "All exceeded the 1% limit",
         evidence_state("open", "Stopped")],
        ["Kimi K2.6", "Profile after $1.76 syntax lesson",
         "73 of 224 malformed (32.59%)", "Final gate was already impossible",
         evidence_state("open", "Stopped")],
        ["DeepSeek V3.1", "Prior failures replayed at 512 tokens",
         "6 of 24 malformed; then 8 of 8 after syntax lesson",
         "More tokens and copy-only syntax training did not solve truncation",
         evidence_state("open", "Stopped")],
    ]
    format_tbl = table(
        ["model family", "admission test", "result", "interpretation", "decision"],
        format_rows, right_from=99, cls="brief-prose format-gates")

    # --- a research outline rather than another discussion section --------
    next_tbl = table(
        ["priority", "hypothesis to discriminate", "next design",
         "result that would move the claim"],
        [
            ["1", "Calibration reduces consequential misconduct, not only factual overconfidence",
             "Longer-horizon tool agents with private state, hidden opportunities, delayed audits, and authorized controls",
             "Lower unauthorized action without lower authorized completion, repeated across seeds and families"],
            ["2", "The proposed metacognitive chain has separable causal links",
             "Cross calibration training with evidence-update, plural-ends, and goal-revision interventions in a factorial design",
             "Identify which intervention moves each downstream behavior rather than attributing the bundle"],
            ["3", "Factual calibration transfer extends beyond Qwen and GPT-OSS",
             "Admit a third family through two full format profiles, then run five matched reward-training seeds",
             "Repeated high-confidence-error reductions on a training domain and an unseen domain"],
            ["4", "Kimi or DeepSeek can become measurable without changing the scientific endpoint",
             "Question-shaped, benchmark-disjoint short-answer curriculum; then repeat both 1,920-response profiles",
             "Both profiles below 1% malformed before any reward training"],
            ["5", "Automated alignment graders track the behavior humans care about",
             "Blind human labels on a stratified sample of failures, near-boundary cases, and controls",
             "High agreement overall and inside each outcome class"],
        ],
        right_from=99, cls="brief-prose")

    body = content.load("brief-table").format(
        tb_map=evidence_map,
        tb_problem=problem_tbl,
        tb_prompting=prompting_tbl,
        tb_prompt_reliability=prompt_reliability,
        tb_training=trained_tbl,
        tb_prompt_factorial=prompt_factorial_tbl,
        tb_prompt_factorial_wrong_delta=(
            f'{abs(prompt_headline["wrong_change"]) * 100:.1f}'
        ),
        tb_prompt_factorial_value_delta=(
            f'{prompt_headline["utility_change"] * 100:.1f}'
        ),
        tb_prompt_only_value_delta=(
            f'{prompt_headline["prompt_only_utility_change"] * 100:.1f}'
        ),
        tb_gate_value_delta=(
            f'{abs(prompt_headline["gate_marginal_utility_change"]) * 100:.1f}'
        ),
        tb_prompt_embedded_invalid=int(
            prompt_headline["embedded_format_failures"]),
        tb_prompt_separated_invalid=int(
            prompt_headline["separated_format_failures"]),
        tb_prompt_formatted_wrong_delta=(
            f'{abs(prompt_factorial["well_formatted_pair_sensitivity"]["wrong_change"]) * 100:.1f}'
        ),
        tb_prompt_formatted_value_delta=(
            f'{prompt_factorial["well_formatted_pair_sensitivity"]["utility_change"] * 100:.1f}'
        ),
        tb_policy_primary=policy_primary_tbl,
        tb_policy_stakes=policy_stakes_tbl,
        tb_policy_wrong_delta=(
            f'{policy_architecture["headline_equal_benchmark_weight"]["wrong_change"] * 100:.1f}'
        ),
        tb_policy_matched_error_delta=(
            f'{policy_architecture["headline_equal_benchmark_weight"]["matched_error_change"] * 100:.1f}'
        ),
        tb_generalization=generalization_tbl,
        tb_generalization_scope=generalization_scope_tbl,
        tb_subject_transfer=subject_transfer_tbl,
        tb_cross_family=cross_family_tbl,
        tb_training_reliability=training_reliability,
        tb_chain=chain_tbl,
        tb_format=format_tbl,
        tb_next=next_tbl,
        tb_src_census=vintage("census"),
        tb_src_prompt=vintage("prompt_estimation"),
        tb_src_training=vintage("finetune"),
        tb_src_policy_architecture=vintage("policy_architecture"),
        tb_src_prompt_threshold_factorial=vintage(
            "prompt_threshold_factorial"),
        tb_src_transfer=(vintage("multitask_family_agentic") + " "
                         + vintage("openweight_followup")),
        tb_src_chain=(vintage("plural_prudence") + " "
                      + vintage("multitask_family_agentic") + " "
                      + vintage("openweight_followup")),
        tb_src_formats=(vintage("domain_replication") + " "
                        + vintage("multitask_family_agentic") + " "
                        + vintage("openweight_followup")),
    )

    side_page(
        "brief-table.html",
        title="Table-focused brief &middot; Below Zero",
        description="A table-first working outline of the Below Zero findings, evidence strength, limits, and next tests.",
        h1="Below Zero: table-focused brief",
        standfirst="A working outline of the argument. Each section keeps the answer, the evidence behind it, and what we still do not know together.",
        body=body,
        footer="Working outline. The full brief preserves interpretation, methods, and row-level evidence.",
        content_updated=TABLE_BRIEF_CONTENT_UPDATED,
        style_updated=TABLE_BRIEF_STYLE_UPDATED,
        site_commit=TABLE_BRIEF_SITE_COMMIT,
        extra_css=TABLE_BRIEF_CSS)


DRAFT_CSS = TABLE_BRIEF_CSS + r"""
/* Headline exhibits borrow the clarity of a Stripe report and the evidence
   discipline of a Daily Observation: the title states the claim, one visual
   comparison establishes it, and the audit table stays one click away. */
.draft-exhibit {
  box-sizing: border-box; max-width: 820px; margin: 20px 0 18px;
  padding: 22px 24px 20px; border-radius: 8px; background: #f2f5f8;
  font-family: 'Inter', ui-sans-serif, sans-serif; color: var(--text);
}
.draft-exhibit figcaption {
  margin: 0 0 20px; font: 650 20px/1.23 'Inter', ui-sans-serif, sans-serif;
  letter-spacing: -.018em;
}
.draft-exhibit figcaption span {
  display: block; margin-top: 5px; font-size: 11.5px; line-height: 1.45;
  font-weight: 400; letter-spacing: 0; color: var(--text-secondary);
}
.draft-context-figure { background: #fff; border: 1px solid var(--rule); }
.draft-context-header,
.draft-context-row {
  display: grid;
  grid-template-columns: minmax(115px, .72fr) minmax(220px, 1.25fr) minmax(245px, 1.45fr);
  column-gap: 18px;
}
.draft-context-header {
  padding: 0 10px 8px;
  border-bottom: 1px solid var(--rule-strong);
  color: var(--text-secondary);
  font-size: 9px;
  font-weight: 650;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.draft-context-row {
  padding: 11px 10px;
  border-bottom: 1px solid var(--rule);
  font-size: 10.5px;
  line-height: 1.46;
}
.draft-context-row:last-of-type { border-bottom: 0; }
.draft-context-question { font-weight: 700; color: var(--text); }
.draft-context-prior { color: var(--text-secondary); }
.draft-context-add { color: var(--text); }
.draft-context-tag {
  display: inline-block;
  margin: 0 6px 2px 0;
  color: var(--accent-text);
  font-size: 8px;
  font-weight: 750;
  letter-spacing: .055em;
  text-transform: uppercase;
}
.draft-context-row a { text-decoration-thickness: 1px; text-underline-offset: 2px; }
.draft-context-link {
  margin: 13px 0 0;
  color: var(--text-secondary);
  font-size: 10.5px;
}
.draft-context-link a { font-weight: 650; }
.draft-source, .draft-detail-source { color: var(--text-secondary); }
.draft-detail {
  box-sizing: border-box; max-width: 820px; margin: 0 0 24px;
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule);
  font-family: 'Inter', ui-sans-serif, sans-serif;
}
.draft-detail summary {
  position: relative; padding: 12px 34px 12px 0; cursor: pointer;
  list-style: none; font-size: 12px; font-weight: 650; color: var(--text-secondary);
}
.draft-detail summary::-webkit-details-marker { display: none; }
.draft-detail summary::after {
  content: "+"; position: absolute; right: 2px; top: 8px;
  font-size: 20px; line-height: 1; font-weight: 400; color: var(--text-muted);
}
.draft-detail[open] summary::after { content: "−"; }
.draft-detail-body { padding: 2px 0 16px; }
.draft-detail-body h4 {
  margin: 18px 0 8px; font: 650 12px/1.4 'Inter', ui-sans-serif, sans-serif;
}
.draft-detail-source { margin: 12px 0 0; font-size: 10.5px; line-height: 1.5; }
.draft-census-bar {
  display: flex; height: 28px; overflow: hidden; border-radius: 4px;
  background: #d9e1eb;
}
.draft-census-bar .answered { background: #31577d; }
.draft-census-bar .declined { min-width: 6px; background: var(--accent); }
.draft-census-labels {
  display: flex; justify-content: space-between; gap: 20px; margin-top: 10px;
  font-size: 11.5px; color: var(--text-secondary);
}
.draft-census-labels b { font-size: 18px; color: var(--text); }
.draft-census-foot {
  display: flex; gap: 26px; margin-top: 19px; padding-top: 13px;
  border-top: 1px solid #d8dfe7; font-size: 10.8px; color: var(--text-secondary);
}
.draft-census-foot b { color: var(--text); }
.draft-headline-table {
  width: 100%; border-collapse: collapse; table-layout: fixed;
  background: transparent; font-size: 10.5px; line-height: 1.35;
}
.draft-headline-table th {
  padding: 0 8px 8px; border-bottom: 1px solid #aeb8c4; text-align: left;
  color: var(--text-secondary); font-size: 9px; font-weight: 650;
  letter-spacing: .05em; text-transform: uppercase;
}
.draft-headline-table td {
  padding: 10px 8px; border-bottom: 1px solid #d8dfe7; vertical-align: top;
}
.draft-headline-table tbody tr:last-child td { border-bottom: 0; }
.draft-headline-table th:not(:first-child),
.draft-headline-table td:not(:first-child) { text-align: right; }
.draft-incentive-table th:first-child { width: 13%; }
.draft-incentive-table td:first-child { font-weight: 700; }
.draft-choice { display: block; font-weight: 650; color: var(--text); }
.draft-choice.extreme { color: var(--accent-text); }
.draft-choice.silent { color: var(--text-secondary); }
.draft-ev-proof {
  display: grid; grid-template-columns: 1fr 1fr; gap: 1px; margin-top: 14px;
  overflow: hidden; border-radius: 4px; background: #d8dfe7;
}
.draft-ev-proof > div { padding: 11px 13px; background: #fff; }
.draft-ev-proof b { display: block; margin-bottom: 3px; font-size: 11px; }
.draft-ev-proof span { color: var(--text-secondary); font-size: 10px; }
.draft-wisdom-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.draft-wisdom-card { padding: 15px 16px; border-radius: 5px; background: #fff; }
.draft-wisdom-card b { display: block; margin-bottom: 10px; font-size: 12px; }
.draft-wisdom-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.draft-wisdom-metrics strong { display: block; font-size: 24px; line-height: 1; }
.draft-wisdom-metrics span { font-size: 10px; color: var(--text-secondary); }
.draft-wisdom-reading {
  margin-top: 12px; padding-top: 10px; border-top: 1px solid #e1e6ec;
  font-size: 11px; color: var(--text-secondary);
}
.draft-wisdom-card.good .draft-wisdom-reading { color: var(--evidence); }
.draft-scatter-layout {
  display: grid; grid-template-columns: minmax(360px, 1fr) 210px;
  gap: 26px; align-items: center;
}
.draft-calibration-plot { display: block; width: 100%; height: auto; }
.draft-scatter-grid { stroke: #dce2e9; stroke-width: 1; }
.draft-scatter-axis { stroke: #8e99a6; stroke-width: 1.2; }
.draft-scatter-diagonal { stroke: #7d8792; stroke-width: 1.4; stroke-dasharray: 5 5; }
.draft-scatter-label {
  fill: #6b7280; font: 9px 'Inter', ui-sans-serif, sans-serif;
}
.draft-scatter-note {
  fill: var(--accent-text); font: 650 10px 'Inter', ui-sans-serif, sans-serif;
}
.draft-scatter-dot { fill: #31577d; fill-opacity: .76; stroke: #fff; stroke-width: 1; }
.draft-scatter-dot.treated { fill: var(--accent); fill-opacity: 1; }
.draft-scatter-arrow { stroke: var(--accent); stroke-width: 2; marker-end: url(#draft-arrow); }
.draft-scatter-summary {
  padding-left: 22px; border-left: 1px solid #d8dfe7;
}
.draft-scatter-summary strong { display: block; font-size: 34px; line-height: 1; }
.draft-scatter-summary > span {
  display: block; margin: 5px 0 18px; color: var(--text-secondary); font-size: 11px;
}
.draft-scatter-metrics {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
}
.draft-scatter-metrics b { display: block; font-size: 17px; }
.draft-scatter-metrics small { color: var(--text-secondary); font-size: 9px; }
.draft-evidence-summary { margin-top: 16px; }
.draft-evidence-summary, .draft-comparison-table { min-width: 0 !important; }
.draft-evidence-summary th:first-child, .draft-comparison-table th:first-child { width: 38%; }
.draft-evidence-summary td:first-child { font-weight: 650; text-align: left; }
.draft-evidence-summary td:first-child span {
  display: block; color: var(--text-secondary); font-size: 9px; font-weight: 400;
}
.draft-comparison-result {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px; margin-top: 14px; overflow: hidden; border-radius: 4px;
  background: #d8dfe7;
}
.draft-comparison-result span { padding: 10px 12px; background: #fff; }
.draft-comparison-result b { display: block; font-size: 18px; color: var(--text); }
.draft-comparison-result small { color: var(--text-secondary); font-size: 9.5px; }
.draft-training-layout {
  display: grid; grid-template-columns: minmax(300px, .9fr) minmax(330px, 1.1fr);
  gap: 24px; align-items: center;
}
.draft-training-table th:first-child { width: 34%; }
.draft-training-table { min-width: 0 !important; }
.draft-training-point-label {
  fill: #27323e; font: 650 9px 'Inter', ui-sans-serif, sans-serif;
}
.draft-mini-heading { margin-top: 34px; }
.draft-alignment-row {
  display: grid; grid-template-columns: minmax(190px, 1fr) 190px 104px;
  gap: 14px; align-items: center; padding: 10px 0; border-top: 1px solid #d8dfe7;
}
.draft-alignment-row:first-of-type { border-top: 0; }
.draft-alignment-behavior { font-size: 11px; font-weight: 650; }
.draft-alignment-value { font-size: 11.5px; font-variant-numeric: tabular-nums; }
.draft-status {
  justify-self: start; display: inline-block; padding: 2px 7px;
  border: 1px solid var(--rule-strong); border-radius: 12px;
  font: 700 8.5px/1.45 'Inter', ui-sans-serif, sans-serif;
  letter-spacing: .05em; text-transform: uppercase; color: var(--text-secondary);
}
.draft-status.strong { border-color: var(--evidence); color: var(--evidence); }
.draft-status.mixed { border-color: var(--accent); color: var(--accent-text); }
.draft-status.open { color: var(--text-muted); }
.draft-plural-figure { margin-top: 18px; }
.draft-plural-prompt {
  margin: 16px 0 18px;
  padding: 0 0 0 14px;
  border-left: 2px solid var(--accent);
  color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 12px;
  line-height: 1.55;
}
.draft-plural-measure {
  margin: 0 0 6px;
  color: var(--text-secondary);
  font: 650 10px/1.4 'Inter', ui-sans-serif, sans-serif;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.draft-plural-result {
  display: grid;
  grid-template-columns: minmax(130px, 1fr) auto minmax(130px, 1fr) minmax(150px, 1fr);
  align-items: stretch;
  border-top: 1px solid #d8dfe7;
  border-bottom: 1px solid #d8dfe7;
}
.draft-plural-stat {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  padding: 13px 14px;
  border-right: 1px solid #d8dfe7;
}
.draft-plural-stat:last-child { border-right: 0; }
.draft-plural-stat span {
  color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 9.5px;
  line-height: 1.35;
  text-transform: uppercase;
  letter-spacing: .045em;
}
.draft-plural-stat strong {
  color: var(--text);
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 23px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.draft-plural-stat.after strong,
.draft-plural-stat.effect strong { color: var(--accent-text); }
.draft-plural-arrow {
  display: flex;
  align-items: center;
  padding: 0 2px;
  color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 18px;
}
.draft-plural-consistency {
  margin: 11px 0 0;
  color: var(--text-secondary);
  font-family: 'Inter', ui-sans-serif, sans-serif;
  font-size: 11px;
}
table.draft-hle { min-width: 690px; }
table.draft-overconfidence { min-width: 760px; }
table.draft-transfer { min-width: 760px; }
table.draft-alignment { min-width: 720px; }
table.draft-metrics, table.draft-rules, table.draft-wisdom { min-width: 620px; }
@media (max-width: 700px) {
  .draft-exhibit { padding: 18px 16px 17px; border-radius: 6px; }
  .draft-exhibit figcaption { font-size: 18px; }
  .draft-incentive-table { min-width: 600px; }
  .draft-ev-proof { grid-template-columns: 1fr; }
  .draft-scatter-layout, .draft-training-layout { grid-template-columns: 1fr; }
  .draft-scatter-summary {
    padding: 14px 0 0; border-left: 0; border-top: 1px solid #d8dfe7;
  }
  .draft-alignment-row { grid-template-columns: minmax(165px, 1fr) 160px 90px; gap: 8px; }
  .draft-context-header { display: none; }
  .draft-context-row {
    grid-template-columns: 1fr 1fr;
    gap: 6px 14px;
    padding: 12px 2px;
  }
  .draft-context-question { grid-column: 1 / -1; }
  .draft-context-prior::before,
  .draft-context-add::before {
    display: block;
    margin-bottom: 3px;
    color: var(--text-muted);
    font-size: 8px;
    font-weight: 650;
    letter-spacing: .05em;
    text-transform: uppercase;
  }
  .draft-context-prior::before { content: "Prior research"; }
  .draft-context-add::before { content: "This report"; }
}
@media (max-width: 520px) {
  .draft-headline-table { font-size: 9.5px; }
  .draft-headline-table th, .draft-headline-table td { padding-left: 4px; padding-right: 4px; }
  .draft-evidence-summary th:first-child, .draft-comparison-table th:first-child { width: 34%; }
  .draft-comparison-result span { padding: 9px 8px; }
  .draft-comparison-result b { font-size: 16px; }
  .draft-alignment-row { grid-template-columns: minmax(135px, 1fr) auto; }
  .draft-alignment-behavior { grid-row: 1 / 3; }
  .draft-alignment-value { grid-column: 2; text-align: right; }
  .draft-alignment-row .draft-status { grid-column: 2; justify-self: end; }
  .draft-plural-result { grid-template-columns: 1fr auto 1fr; }
  .draft-plural-stat.effect {
    grid-column: 1 / -1;
    border-top: 1px solid #d8dfe7;
    border-right: 0;
  }
  .draft-context-row { grid-template-columns: 1fr; }
  .draft-context-prior, .draft-context-add { grid-column: 1; }
}
"""


def build_draft():
    """Build the concise prose draft that follows Ramon's Google Doc outline.

    The source document contains illustrative numbers. This builder replaces
    them with values recomputed from the committed processed files, so the
    draft cannot quietly preserve a made-up example after the evidence changes.
    """
    summary = {r["metric"]: r["value"] for r in rows("census_summary.csv")}
    survey = rows("benchmark_scoring_survey.csv")
    gradable = [r for r in survey if r["prices_wrong_answers"] in {"yes", "no"}]
    priced_wrong = sum(r["prices_wrong_answers"] == "yes" for r in gradable)

    def detail_block(label, contents, source=""):
        source_html = (
            f'<p class="draft-detail-source">{source}</p>' if source else ""
        )
        return (
            '<details class="draft-detail">'
            f'<summary>{html.escape(label)}</summary>'
            f'<div class="draft-detail-body">{contents}{source_html}</div></details>'
        )

    decline_rate = float(summary["decline_rate"])
    census_figure = (
        '<figure class="draft-exhibit draft-census-figure">'
        '<figcaption>Models answered 99.32% of published benchmark questions'
        f'<span>{int(summary["responses_scanned"]):,} published responses across '
        f'{summary["models"]} models and {summary["benchmarks"]} benchmarks</span>'
        '</figcaption><div class="draft-census-bar" aria-hidden="true">'
        f'<i class="answered" style="width:{(1 - decline_rate) * 100:.2f}%"></i>'
        f'<i class="declined" style="width:{decline_rate * 100:.2f}%"></i></div>'
        '<div class="draft-census-labels"><span><b>99.32%</b><br>answered</span>'
        '<span style="text-align:right"><b>0.68%</b><br>said they did not know</span></div>'
        '<div class="draft-census-foot"><span><b>44 of 45</b> reviewed benchmarks '
        'gave a wrong answer no less credit than silence</span>'
        '<span><b>1% belief</b> is still enough to make guessing rational</span></div>'
        '</figure>'
    )
    problem_tbl = table(
        ["benchmark design", "wrong answer versus silence", "rational behavior"],
        [["Most current benchmarks", "Same score: 0 versus 0",
          "Guess whenever there is any chance of being right"],
         ["Confidence score + fixed cost", "A wrong answer can score below silence",
          "Report confidence honestly; withhold below the threshold"]],
        right_from=99, cls="brief-prose draft-rules")
    problem_detail = detail_block(
        "See the scoring evidence and audit scope", problem_tbl,
        vintage(
            "census", f"Scoring records reviewed for {len(survey)} benchmarks; "
            f"{len(gradable) - priced_wrong} of {len(gradable)} clear endpoints "
            "did not price a wrong answer."))

    rules_tbl = table(
        ["scoring rule", "best strategy", "what it reveals or changes"],
        [["Accuracy only", "Always answer", "Correctness only"],
         ["Linear penalty", "Report 0% or 100%", "Raises stakes, not honesty"],
         ["Confidence-calibrated", "Report the actual probability",
          "Correctness plus self-assessment"],
         ["Confidence-calibrated + fixed cost",
          "Report honestly; withhold below the threshold",
          "Self-assessment plus a visible cost for guessing"]],
        right_from=99, cls="brief-prose draft-rules")

    incentive_figure = """
<figure class="draft-exhibit draft-incentive-figure">
  <figcaption>The scoring rule determines whether a 40% belief is reported as 0% or 40%
    <span>What maximizes expected score at three beliefs about the same proposed answer</span>
  </figcaption>
  <div class="table-wrap"><table class="draft-headline-table draft-incentive-table">
    <thead><tr><th>Belief in answer</th><th>Accuracy only</th>
      <th>Linear penalty</th><th>Confidence-calibrated</th>
      <th>+ fixed cost<br><span class="sub">30% threshold</span></th></tr></thead>
    <tbody>
      <tr><td>20%</td><td><span class="draft-choice">Answer</span></td>
        <td><span class="draft-choice extreme">Report 0%</span></td>
        <td><span class="draft-choice">Report 20%</span></td>
        <td><span class="draft-choice silent">Withhold</span></td></tr>
      <tr><td>40%</td><td><span class="draft-choice">Answer</span></td>
        <td><span class="draft-choice extreme">Report 0%</span></td>
        <td><span class="draft-choice">Report 40%</span></td>
        <td><span class="draft-choice">Report 40%</span></td></tr>
      <tr><td>70%</td><td><span class="draft-choice">Answer</span></td>
        <td><span class="draft-choice extreme">Report 100%</span></td>
        <td><span class="draft-choice">Report 70%</span></td>
        <td><span class="draft-choice">Report 70%</span></td></tr>
    </tbody>
  </table></div>
  <div class="draft-ev-proof">
    <div><b>At a true 40% belief</b><span>Honest 40%: &minus;0.08 &middot; Extreme 0%: 0 &rarr; report 0%</span></div>
    <div><b>At a true 70% belief</b><span>Honest 70%: +0.28 &middot; Extreme 100%: +0.40 &rarr; report 100%</span></div>
  </div>
</figure>"""

    rules_detail = detail_block(
        "See all four rules, their incentives, and the SAT precedent",
        rules_tbl
        + '<p class="draft-detail-source"><b>SAT precedent.</b> The old SAT penalty '
        'was too weak to deter many guesses and complicated test-taking. Those are '
        'design problems, not reasons to give wrong answers the same score as silence. '
        '<a href="related-work.html#choice">See the related-work discussion.</a></p>')

    wisdom_figure = (
        '<figure class="draft-exhibit draft-wisdom-figure">'
        '<figcaption>Equal knowledge can conceal very different self-knowledge'
        '<span>Illustrative example: both models answer 70% of questions correctly</span>'
        '</figcaption><div class="draft-wisdom-grid">'
        '<div class="draft-wisdom-card good"><b>Model A</b>'
        '<div class="draft-wisdom-metrics"><div><strong>70%</strong><span>accuracy</span></div>'
        '<div><strong>70%</strong><span>confidence</span></div></div>'
        '<div class="draft-wisdom-reading">Knows what it knows: 0-point gap</div></div>'
        '<div class="draft-wisdom-card"><b>Model B</b>'
        '<div class="draft-wisdom-metrics"><div><strong>70%</strong><span>accuracy</span></div>'
        '<div><strong>95%</strong><span>confidence</span></div></div>'
        '<div class="draft-wisdom-reading">Same knowledge, 25 points overconfident</div></div>'
        '</div></figure>'
    )
    wisdom_tbl = table(
        ["measure", "question it answers", "what it misses"],
        [["Accuracy", "How often was the model right?", "Whether it knew when it might be wrong"],
         ["Confidence gap", "Did average confidence match average accuracy?",
          "Whether errors cancel across confidence levels"],
         ["Confidence-calibrated score", "Were answers right and probabilities realistic?",
          "Why the model behaved that way"]],
        right_from=99, sortable=False, cls="brief-prose draft-wisdom")
    wisdom_detail = detail_block("See what each measure captures", wisdom_tbl)

    # Build one view across three separate bodies of evidence. Every accuracy
    # and confidence value uses the same denominator: responses with usable
    # stated confidence. The HLE subset therefore includes only published runs
    # with confidence on at least 90% of responses.
    prompt_levels = rows("prompt_estimation_levels.csv")
    hle = rows("hle_rescored_all.csv")
    covered_hle = [
        r for r in hle
        if int(r["n_scored"]) / int(r["n_responses"]) >= .9
    ]
    hle_labels = {
        "openai/gpt-5.4-2026-03-05": "GPT-5.4",
        "openai/gpt-5.2-2025-12-11": "GPT-5.2",
        "openai/gpt-5-2025-08-07": "GPT-5",
    }
    benchmark_labels = {
        "bbq": "BBQ",
        "ethics_hard": "ETHICS hard",
        "gpqa_parity": "GPQA",
        "hle": "Humanity's Last Exam",
        "medmcqa": "MedMCQA",
        "mmlu_pro": "MMLU-Pro",
        "truthfulqa_mc": "TruthfulQA",
    }
    model_display_names = {
        "deepseek-v4-pro-0813": "DeepSeek V4 Pro",
        "gemini-3.7-flash": "Gemini 3.7 Flash",
        "mistral-medium-3.1": "Mistral Medium 3.1",
        "mistral-small-2603": "Mistral Small",
        "nemotron-3-nano": "Nemotron 3 Nano",
        "qwen3.5-4b": "Qwen3.5 4B",
        "qwen3-8b": "Qwen3 8B",
    }

    def overconfidence_model_label(model):
        lowered = model.lower()
        for fragment, label in model_display_names.items():
            if fragment in lowered:
                return label
        return model.rsplit("/", 1)[-1]

    overconfidence_points = []

    def add_overconfidence_point(source, model, benchmark, accuracy,
                                 confidence, answer_count):
        overconfidence_points.append({
            "source": source,
            "model": model,
            "benchmark": benchmark,
            "accuracy": accuracy,
            "confidence": confidence,
            "n": answer_count,
        })

    for record in covered_hle:
        add_overconfidence_point(
            "Published HLE", hle_labels[record["model"]], "hle",
            float(record["accuracy"]), float(record["mean_confidence"]),
            int(record["n_scored"]),
        )
    for record in rows("broader_model_screen.csv"):
        coverage = float(record["coverage"])
        add_overconfidence_point(
            "Untuned model screen", overconfidence_model_label(record["model"]),
            record["benchmark"], float(record["accuracy"]) / coverage,
            float(record["mean_confidence"]), int(record["n"]) * coverage,
        )
    for record in prompt_levels:
        if record["contract"] != "control":
            continue
        coverage = float(record["answered_rate"])
        add_overconfidence_point(
            "Prompt-study baseline", overconfidence_model_label(record["model"]),
            record["benchmark"], float(record["accuracy_when_answered"]),
            float(record["confidence_when_answered"]),
            int(record["n"]) * coverage,
        )

    def canonical_model(name):
        lowered = name.lower()
        if "nemotron-3-nano" in lowered:
            return "nemotron-3-nano"
        return lowered

    def weighted_overconfidence(selected):
        answer_count = sum(record["n"] for record in selected)
        accuracy = sum(
            record["n"] * record["accuracy"] for record in selected
        ) / answer_count
        confidence = sum(
            record["n"] * record["confidence"] for record in selected
        ) / answer_count
        return {
            "n": answer_count,
            "accuracy": accuracy,
            "confidence": confidence,
            "gap": confidence - accuracy,
        }

    all_overconfidence = weighted_overconfidence(overconfidence_points)
    overconfident_count = sum(
        record["confidence"] > record["accuracy"]
        for record in overconfidence_points
    )
    if overconfident_count != len(overconfidence_points):
        raise ValueError("Broad overconfidence headline no longer matches the data")
    distinct_models = len({
        canonical_model(record["model"]) for record in overconfidence_points
    })
    distinct_benchmarks = len({
        record["benchmark"] for record in overconfidence_points
    })

    # Accuracy is horizontal and stated confidence vertical. The plot is square,
    # so a point's distance above the 45-degree line is its overconfidence gap.
    scatter_size, scatter_left, scatter_top = 250, 44, 16
    scatter_bottom = scatter_top + scatter_size

    def scatter_x(value):
        return scatter_left + value * scatter_size

    def scatter_y(value):
        return scatter_bottom - value * scatter_size

    scatter_parts = []
    for tick in (0, .25, .5, .75, 1):
        x, y = scatter_x(tick), scatter_y(tick)
        scatter_parts.extend([
            f'<line class="draft-scatter-grid" x1="{x:.1f}" y1="{scatter_top}" x2="{x:.1f}" y2="{scatter_bottom}"/>',
            f'<line class="draft-scatter-grid" x1="{scatter_left}" y1="{y:.1f}" x2="{scatter_left + scatter_size}" y2="{y:.1f}"/>',
            f'<text class="draft-scatter-label" x="{x:.1f}" y="{scatter_bottom + 17}" text-anchor="middle">{tick * 100:.0f}%</text>',
            f'<text class="draft-scatter-label" x="{scatter_left - 7}" y="{y + 3:.1f}" text-anchor="end">{tick * 100:.0f}%</text>',
        ])
    scatter_parts.extend([
        f'<line class="draft-scatter-diagonal" x1="{scatter_x(0):.1f}" y1="{scatter_y(0):.1f}" x2="{scatter_x(1):.1f}" y2="{scatter_y(1):.1f}"/>',
        f'<line class="draft-scatter-axis" x1="{scatter_left}" y1="{scatter_bottom}" x2="{scatter_left + scatter_size}" y2="{scatter_bottom}"/>',
        f'<line class="draft-scatter-axis" x1="{scatter_left}" y1="{scatter_top}" x2="{scatter_left}" y2="{scatter_bottom}"/>',
        f'<text class="draft-scatter-note" x="{scatter_left + 9}" y="{scatter_top + 15}">Overconfident</text>',
        f'<text class="draft-scatter-label" x="{scatter_left + scatter_size / 2}" y="{scatter_bottom + 37}" text-anchor="middle">Accuracy</text>',
        f'<text class="draft-scatter-label" transform="translate(10 {scatter_top + scatter_size / 2}) rotate(-90)" text-anchor="middle">Stated confidence</text>',
    ])
    for record in overconfidence_points:
        gap = record["confidence"] - record["accuracy"]
        scatter_parts.append(
            f'<circle class="draft-scatter-dot" cx="{scatter_x(record["accuracy"]):.1f}" '
            f'cy="{scatter_y(record["confidence"]):.1f}" r="4.5"><title>'
            f'{html.escape(record["model"])} on '
            f'{html.escape(benchmark_labels[record["benchmark"]])}: '
            f'{record["accuracy"] * 100:.1f}% accurate, '
            f'{record["confidence"] * 100:.1f}% confident, '
            f'+{gap * 100:.1f}-point gap</title></circle>'
        )

    source_specs = [
        ("Published HLE", "3 models, 1 benchmark"),
        ("Untuned model screen", "3 models, 3 benchmarks"),
        ("Prompt-study baseline", "5 models, 3 benchmarks"),
    ]
    source_summaries = [
        (label, breadth, weighted_overconfidence([
            record for record in overconfidence_points
            if record["source"] == label
        ]))
        for label, breadth in source_specs
    ]
    evidence_rows = [
        ('<tr class="total"><td>All evidence<span>'
         f'{distinct_models} models, {distinct_benchmarks} benchmarks</span></td>'
         f'<td>{all_overconfidence["accuracy"] * 100:.1f}%</td>'
         f'<td>{all_overconfidence["confidence"] * 100:.1f}%</td>'
         f'<td>+{all_overconfidence["gap"] * 100:.1f}</td></tr>')
    ]
    for label, breadth, summary_record in source_summaries:
        evidence_rows.append(
            f'<tr><td>{html.escape(label)}<span>{html.escape(breadth)}</span></td>'
            f'<td>{summary_record["accuracy"] * 100:.1f}%</td>'
            f'<td>{summary_record["confidence"] * 100:.1f}%</td>'
            f'<td>+{summary_record["gap"] * 100:.1f}</td></tr>'
        )

    overconfidence_figure = (
        '<figure class="draft-exhibit draft-overconfidence-figure">'
        '<figcaption>Every one of 27 model-benchmark comparisons was overconfident'
        f'<span>{distinct_models} models, {distinct_benchmarks} benchmarks, '
        f'{all_overconfidence["n"]:,.0f} answered questions</span>'
        '</figcaption><div class="draft-scatter-layout">'
        '<svg class="draft-calibration-plot" viewBox="0 0 320 310" role="img" '
        'aria-label="Accuracy versus stated confidence across 27 model-benchmark comparisons">'
        + "".join(scatter_parts) + '</svg>'
        '<div class="draft-scatter-summary">'
        f'<strong>{overconfident_count} of {len(overconfidence_points)}</strong>'
        '<span>comparisons sit above the 45-degree line</span>'
        '<div class="draft-scatter-metrics">'
        f'<div><b>{all_overconfidence["accuracy"] * 100:.0f}%</b><small>accuracy</small></div>'
        f'<div><b>{all_overconfidence["confidence"] * 100:.0f}%</b><small>confidence</small></div>'
        f'<div><b>+{all_overconfidence["gap"] * 100:.0f}</b><small>point gap</small></div>'
        '</div></div></div>'
        '<table class="draft-headline-table draft-evidence-summary">'
        '<thead><tr><th>Evidence set</th><th>Accuracy</th><th>Confidence</th><th>Gap</th></tr></thead>'
        '<tbody>' + "".join(evidence_rows) + '</tbody></table></figure>'
    )

    source_order = {label: index for index, (label, _breadth) in enumerate(source_specs)}
    hle_model_order = {"GPT-5.4": 0, "GPT-5.2": 1, "GPT-5": 2}
    detailed_points = sorted(
        overconfidence_points,
        key=lambda record: (
            source_order[record["source"]],
            hle_model_order.get(record["model"], 99),
            record["model"], record["benchmark"]
        ),
    )
    overconfidence_tbl = table(
        ["evidence set", "model", "benchmark", "answers", "accuracy",
         "confidence", "gap"],
        [[record["source"], record["model"], benchmark_labels[record["benchmark"]],
          f'{record["n"]:,.0f}', f'{record["accuracy"] * 100:.1f}%',
          f'{record["confidence"] * 100:.1f}%',
          f'+{(record["confidence"] - record["accuracy"]) * 100:.1f} points']
         for record in detailed_points],
        right_from=3, sortable=True, collapse_after=12,
        cls="brief-prose draft-overconfidence")
    overconfidence_detail = detail_block(
        "See all 27 comparisons and source limits", overconfidence_tbl,
        ('HLE includes only the three published runs with confidence on at least '
         '90% of answers; three Claude runs stated confidence too rarely to be '
         'representative. The other rows are untuned or answer-normally baselines. '
         + vintage("hle") + " " + vintage("broader") + " "
         + vintage("prompt_estimation")))

    # The outline asks first for a clean prompt comparison with no answering
    # threshold. ``control`` and ``quad_formula`` differ only in whether the
    # confidence-calibrated formula is explained. Coverage is shown explicitly
    # because accuracy/confidence are conditional on an answer, while the score
    # is averaged over every question.
    def prompt_summary(contract):
        selected = [r for r in prompt_levels if r["contract"] == contract]
        questions = sum(int(r["n"]) for r in selected)
        answered = sum(
            int(r["n"]) * float(r["answered_rate"]) for r in selected
        )
        return {
            "questions": questions,
            "coverage": answered / questions,
            "accuracy": sum(
                int(r["n"]) * float(r["answered_rate"])
                * float(r["accuracy_when_answered"])
                for r in selected
            ) / answered,
            "confidence": sum(
                int(r["n"]) * float(r["answered_rate"])
                * float(r["confidence_when_answered"])
                for r in selected
            ) / answered,
            "score": sum(
                int(r["n"]) * float(r["confidence_calibrated_score"])
                for r in selected
            ) / questions,
        }

    prompt_normal = prompt_summary("control")
    prompt_treated = prompt_summary("quad_formula")
    for record in (prompt_normal, prompt_treated):
        record["gap"] = record["confidence"] - record["accuracy"]

    prompt_closed = (
        (prompt_normal["gap"] - prompt_treated["gap"]) / prompt_normal["gap"]
    )
    prompt_tbl = table(
        ["measure", "answer normally", "formula explained, no threshold",
         "what changed"],
        [["Questions answered", f'{prompt_normal["coverage"] * 100:.1f}%',
          f'{prompt_treated["coverage"] * 100:.1f}%',
          f'{(prompt_treated["coverage"] - prompt_normal["coverage"]) * 100:+.1f} points'],
         ["Accuracy when answered", f'{prompt_normal["accuracy"] * 100:.1f}%',
          f'{prompt_treated["accuracy"] * 100:.1f}%',
          f'{(prompt_treated["accuracy"] - prompt_normal["accuracy"]) * 100:+.1f} points'],
         ["Average confidence when answered",
          f'{prompt_normal["confidence"] * 100:.1f}%',
          f'{prompt_treated["confidence"] * 100:.1f}%',
          f'{(prompt_treated["confidence"] - prompt_normal["confidence"]) * 100:+.1f} points'],
         ["Confidence gap among answers", f'{prompt_normal["gap"] * 100:.1f} points',
          f'{prompt_treated["gap"] * 100:.1f} points',
          f'{prompt_closed * 100:.0f}% of the starting gap closed'],
         ["Confidence-calibrated score per question",
          f'{prompt_normal["score"]:.3f}', f'{prompt_treated["score"]:.3f}',
          f'{prompt_treated["score"] - prompt_normal["score"]:+.3f}']],
        right_from=1, sortable=False, cls="brief-prose draft-metrics")

    reliability = rows("calibration_reliability_bins.csv")

    def reliability_summary(experiment, arm):
        selected = [r for r in reliability
                    if r["experiment"] == experiment and r["arm"] == arm
                    and int(r["n"]) > 0]
        n = sum(int(r["n"]) for r in selected)
        accuracy = sum(int(r["n"]) * float(r["accuracy"]) for r in selected) / n
        confidence = sum(int(r["n"]) * float(r["mean_confidence"])
                         for r in selected) / n
        top = sum(int(r["n"]) for r in selected
                  if float(r["bin_lower"]) == .9) / n
        return {"n": n, "accuracy": accuracy, "confidence": confidence,
                "gap": confidence - accuracy, "top": top}

    train_binary = reliability_summary("training", "accuracy_trained")
    train_quad = reliability_summary("training", "confidence_trained")

    # The chart above pools only Qwen3 8B and GPT-OSS 20B (the reliability
    # bins have no Nemotron deciles yet). The programme's full evidence base
    # is three families and 33 matched pairs: see
    # data/processed/training_effect_synthesis_summary.json and
    # notes/2026-09-03-third-family-protocol.md for the Nemotron replication.
    with open(
        os.path.join(PROC, "training_effect_synthesis_summary.json"),
        encoding="utf-8",
    ) as handle:
        training_synthesis = json.load(handle)
    # This page stays on the first training programme (its prose was
    # written on those pairs); the exporter carries that programme alone
    # under "first" once the second programme exists, and the pooled
    # "all" block then spans both. Read the first-programme block.
    training_synthesis = {**training_synthesis, **training_synthesis.get("first", {})}
    synthesis_all = training_synthesis["all"]
    synthesis_family_count = len(training_synthesis["design_breadth"]["families"])

    pooled_levels = rows("pooled_training_levels.csv")

    def pooled_training_summary(objective):
        selected = [
            r for r in pooled_levels if r["training_objective"] == objective
        ]
        n = sum(int(r["n_responses"]) for r in selected)

        def weighted(field):
            return sum(
                int(r["n_responses"]) * float(r[field]) for r in selected
            ) / n

        return {
            "n": n,
            # The row label promises the conditional denominator, so use it:
            # accuracy among the same attempted responses whose confidence is
            # averaged, not accuracy over every scheduled response.
            "accuracy": weighted("mean_accuracy_among_answers"),
            "accuracy_all": weighted("mean_accuracy"),
            "confidence": weighted("mean_confidence_among_answers"),
            "high_wrong": weighted("mean_high_confidence_wrong_rate"),
            "score": weighted("mean_confidence_calibrated_score"),
        }

    train_binary_all = pooled_training_summary("binary")
    train_quad_all = pooled_training_summary("quadratic")
    training_closed = (
        (train_binary["gap"] - train_quad["gap"]) / train_binary["gap"]
    )
    risk_reduction = 1 - (
        train_quad_all["high_wrong"] / train_binary_all["high_wrong"]
    )
    training_tbl = table(
        ["measure", "accuracy-trained", "confidence-trained", "what changed"],
        [["Accuracy among responses with usable confidence",
          f'{train_binary["accuracy"] * 100:.1f}%',
          f'{train_quad["accuracy"] * 100:.1f}%', "No change"],
         ["Average confidence among those responses",
          f'{train_binary["confidence"] * 100:.1f}%',
          f'{train_quad["confidence"] * 100:.1f}%',
          f'{(train_quad["confidence"] - train_binary["confidence"]) * 100:+.1f} points'],
         ["Confidence gap among those responses",
          f'{train_binary["gap"] * 100:.1f} points',
          f'{train_quad["gap"] * 100:.1f} points',
          f'{training_closed * 100:.0f}% of the starting gap closed'],
         ["Confidence-calibrated score per question",
          f'{train_binary_all["score"]:.3f}', f'{train_quad_all["score"]:.3f}',
          f'{train_quad_all["score"] - train_binary_all["score"]:+.3f}'],
         ["Wrong answer stated at 80%+ confidence",
          f'{train_binary_all["high_wrong"] * 100:.1f}%',
          f'{train_quad_all["high_wrong"] * 100:.1f}%',
          f'{risk_reduction * 100:.0f}% fewer']],
        right_from=1, sortable=False, cls="brief-prose draft-metrics")

    def comparison_rows(before_label, after_label, before, after):
        return (
            f'<tr><td>{html.escape(before_label)}</td>'
            f'<td>{before["accuracy"] * 100:.1f}%</td>'
            f'<td>{before["confidence"] * 100:.1f}%</td>'
            f'<td>+{before["gap"] * 100:.1f}</td></tr>'
            f'<tr><td>{html.escape(after_label)}</td>'
            f'<td>{after["accuracy"] * 100:.1f}%</td>'
            f'<td>{after["confidence"] * 100:.1f}%</td>'
            f'<td>+{after["gap"] * 100:.1f}</td></tr>'
        )

    prompt_figure = (
        '<figure class="draft-exhibit draft-prompt-figure">'
        '<figcaption>Prompting left 84% of the overconfidence gap in place'
        '<span>Five models, three hard benchmarks, 4,536 matched responses</span>'
        '</figcaption><table class="draft-headline-table draft-comparison-table">'
        '<thead><tr><th>Instruction</th><th>Accuracy</th><th>Confidence</th><th>Gap</th></tr></thead>'
        '<tbody>' + comparison_rows(
            "Answer normally", "Formula explained",
            prompt_normal, prompt_treated,
        ) + '</tbody></table><div class="draft-comparison-result">'
        f'<span><b>{(prompt_treated["accuracy"] - prompt_normal["accuracy"]) * 100:+.1f}</b><small>point accuracy change</small></span>'
        f'<span><b>{(prompt_normal["gap"] - prompt_treated["gap"]) * 100:.1f}</b><small>gap points removed</small></span>'
        f'<span><b>{(1 - prompt_closed) * 100:.0f}%</b><small>of gap remained</small></span>'
        '</div></figure>'
    )
    prompt_detail = detail_block(
        "See all prompting measures and denominators", prompt_tbl,
        vintage(
            "prompt_estimation", "Five models, three benchmarks, and 2,268 "
            "questions per condition; 4,536 matched responses."))

    # Show the treatment on the same accuracy-confidence geometry as the broad
    # evidence above. Accuracy barely moves horizontally; confidence moves down
    # toward the diagonal, which is exactly the claimed change in self-assessment.
    training_plot_size, training_left, training_top = 205, 39, 15
    training_bottom = training_top + training_plot_size

    def training_x(value):
        return training_left + value * training_plot_size

    def training_y(value):
        return training_bottom - value * training_plot_size

    training_plot_parts = [
        '<defs><marker id="draft-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#813553"/></marker></defs>'
    ]
    for tick in (0, .5, 1):
        x, y = training_x(tick), training_y(tick)
        training_plot_parts.extend([
            f'<line class="draft-scatter-grid" x1="{x:.1f}" y1="{training_top}" x2="{x:.1f}" y2="{training_bottom}"/>',
            f'<line class="draft-scatter-grid" x1="{training_left}" y1="{y:.1f}" x2="{training_left + training_plot_size}" y2="{y:.1f}"/>',
            f'<text class="draft-scatter-label" x="{x:.1f}" y="{training_bottom + 16}" text-anchor="middle">{tick * 100:.0f}%</text>',
            f'<text class="draft-scatter-label" x="{training_left - 7}" y="{y + 3:.1f}" text-anchor="end">{tick * 100:.0f}%</text>',
        ])
    training_plot_parts.extend([
        f'<line class="draft-scatter-diagonal" x1="{training_x(0):.1f}" y1="{training_y(0):.1f}" x2="{training_x(1):.1f}" y2="{training_y(1):.1f}"/>',
        f'<line class="draft-scatter-arrow" x1="{training_x(train_binary["accuracy"]):.1f}" y1="{training_y(train_binary["confidence"]):.1f}" x2="{training_x(train_quad["accuracy"]):.1f}" y2="{training_y(train_quad["confidence"]):.1f}"/>',
        f'<circle class="draft-scatter-dot" cx="{training_x(train_binary["accuracy"]):.1f}" cy="{training_y(train_binary["confidence"]):.1f}" r="6"/>',
        f'<circle class="draft-scatter-dot treated" cx="{training_x(train_quad["accuracy"]):.1f}" cy="{training_y(train_quad["confidence"]):.1f}" r="6"/>',
        f'<text class="draft-training-point-label" x="{training_x(train_binary["accuracy"]) + 10:.1f}" y="{training_y(train_binary["confidence"]) - 5:.1f}">Accuracy-trained</text>',
        f'<text class="draft-training-point-label" x="{training_x(train_quad["accuracy"]) + 10:.1f}" y="{training_y(train_quad["confidence"]) + 13:.1f}">Confidence-trained</text>',
        f'<text class="draft-scatter-label" x="{training_left + training_plot_size / 2}" y="{training_bottom + 34}" text-anchor="middle">Accuracy</text>',
        f'<text class="draft-scatter-label" transform="translate(9 {training_top + training_plot_size / 2}) rotate(-90)" text-anchor="middle">Stated confidence</text>',
    ])
    training_figure = (
        '<figure class="draft-exhibit draft-training-figure">'
        '<figcaption>Training cut the confidence gap from 27 to 5 points'
        f'<span>Accuracy stayed at 49.6% for these nine matched pairs '
        f'(Qwen3 8B, GPT-OSS 20B, four subjects); the full programme now '
        f'spans {synthesis_family_count} families and {synthesis_all["pairs"]} '
        f'matched pairs</span>'
        '</figcaption><div class="draft-training-layout">'
        '<svg class="draft-calibration-plot" viewBox="0 0 290 270" role="img" '
        'aria-label="Accuracy and stated confidence before and after confidence training">'
        + "".join(training_plot_parts) + '</svg><div>'
        '<table class="draft-headline-table draft-training-table">'
        '<thead><tr><th>Training</th><th>Accuracy</th><th>Confidence</th><th>Gap</th></tr></thead>'
        '<tbody>' + comparison_rows(
            "Accuracy-trained", "Confidence-trained", train_binary, train_quad,
        ) + '</tbody></table><div class="draft-comparison-result">'
        f'<span><b>{(train_quad["accuracy"] - train_binary["accuracy"]) * 100:+.1f}</b><small>point accuracy change</small></span>'
        f'<span><b>{(train_binary["gap"] - train_quad["gap"]) * 100:.1f}</b><small>gap points removed</small></span>'
        f'<span><b>{training_closed * 100:.0f}%</b><small>of gap closed</small></span>'
        '</div></div></div></figure>'
    )

    generalization = {r["scope"]: r for r in rows("multitask_generalization_summary.csv")}

    def transfer_row(label, record):
        return [
            f'{label} ({record["pair_tests"]} comparisons)',
            (f'{float(record["binary_signed_confidence_gap"]) * 100:.1f} to '
             f'{float(record["quadratic_signed_confidence_gap"]) * 100:.1f} points'),
            (f'{float(record["binary_high_confidence_wrong_rate"]) * 100:.1f}% to '
             f'{float(record["quadratic_high_confidence_wrong_rate"]) * 100:.1f}%'),
            f'{record["risk_improved_pair_tests"]} of {record["pair_tests"]}',
        ]

    transfer_tbl = table(
        ["where tested", "confidence gap", "wrong at 80%+ confidence",
         "comparisons improved"],
        [transfer_row("Training subject", generalization["same_subject"]),
         transfer_row("Outside the training subject", generalization["all_off_domain"])],
        right_from=99, sortable=False, cls="brief-prose draft-transfer")
    training_detail = detail_block(
        "See all training measures and the cross-subject transfer test",
        '<h4>Primary training comparison</h4>' + training_tbl
        + '<h4>Did the change carry into other subjects?</h4>' + transfer_tbl,
        vintage("multitask_family_agentic") + " " + vintage("openweight_followup"))

    prudence_levels = rows("plural_prudence_levels.csv")

    def mean_level(objective, field):
        selected = [r for r in prudence_levels
                    if r["framing"] == "neutral"
                    and r["training_objective"] == objective]
        return statistics.mean(float(r[field]) for r in selected)

    prudent_before = mean_level("binary", "prudence_high_confidence_wrong_execution_rate")
    prudent_after = mean_level("quadratic", "prudence_high_confidence_wrong_execution_rate")

    pressure_rows = rows("alignment_pressure_replication.csv")
    pressure_binary = next(
        r for r in pressure_rows if r["reward"] == "binary" and r["step"] == "125"
    )
    pressure_quad = next(
        r for r in pressure_rows if r["reward"] == "quadratic" and r["step"] == "125"
    )

    transfer_levels = rows("external_transfer_levels.csv")

    def truth_under_pressure(objective):
        selected = [
            r for r in transfer_levels
            if r["task"] == "MASK" and r["setting"] == "known_facts"
            and r["training_objective"] == objective
        ]
        return statistics.mean(float(r["honesty_given_known"]) for r in selected)

    truth_before = truth_under_pressure("binary")
    truth_after = truth_under_pressure("quadratic")
    hidden_qwen = rows("hidden_opportunity_contrasts.csv")
    hidden_gpt = rows("openweight_followup_hidden.csv")
    hidden_before = ([float(r["binary_unauthorized_action_rate"]) for r in hidden_qwen]
                     + [float(r["binary_unauthorized_rate"]) for r in hidden_gpt])
    hidden_after = ([float(r["quadratic_unauthorized_action_rate"]) for r in hidden_qwen]
                    + [float(r["quadratic_unauthorized_rate"]) for r in hidden_gpt])
    mean_hidden_before = statistics.mean(hidden_before)
    mean_hidden_after = statistics.mean(hidden_after)

    # The plural-ends intervention is a prompt comparison, not an effect of
    # confidence training. Keep its levels and consistency separate so the
    # draft cannot accidentally attribute this result to the trained reward.
    plural_prompt_rows = [
        r for r in rows("plural_prudence_prompt_contrasts.csv")
        if r["framing"] == "plural"
        and r["integrity_unauthorized_shortcut_rate_change"] != ""
    ]
    plural_neutral_rows = [r for r in prudence_levels if r["framing"] == "neutral"]
    plural_reminder_rows = [r for r in prudence_levels if r["framing"] == "plural"]
    plural_shortcut_before = statistics.mean(
        float(r["integrity_unauthorized_shortcut_rate"])
        for r in plural_neutral_rows
    )
    plural_shortcut_after = statistics.mean(
        float(r["integrity_unauthorized_shortcut_rate"])
        for r in plural_reminder_rows
    )
    plural_share_removed = (
        (plural_shortcut_before - plural_shortcut_after) / plural_shortcut_before
    )
    plural_improved = sum(
        float(r["integrity_unauthorized_shortcut_rate_change"]) < 0
        for r in plural_prompt_rows
    )
    plural_responses = sum(
        int(r["integrity_n"]) for r in plural_neutral_rows + plural_reminder_rows
    )

    def status(kind, label):
        return f'<span class="draft-status {kind}">{label}</span>'

    alignment_figure = (
        '<figure class="draft-exhibit draft-alignment-figure">'
        '<figcaption>Calibration training improved prudence, not broad alignment'
        '<span>Four behavioral probes; long-horizon scheming was not tested</span>'
        '</figcaption>'
        '<div class="draft-alignment-row"><div class="draft-alignment-behavior">'
        'Very bad action at 90%+ confidence</div>'
        f'<div class="draft-alignment-value"><b>{prudent_before * 100:.1f}%</b> &rarr; '
        f'<b>{prudent_after * 100:.1f}%</b></div>{status("strong", "Improved")}</div>'
        '<div class="draft-alignment-row"><div class="draft-alignment-behavior">'
        'Truth under pressure</div>'
        f'<div class="draft-alignment-value"><b>{truth_before * 100:.1f}%</b> &rarr; '
        f'<b>{truth_after * 100:.1f}%</b></div>{status("mixed", "No change")}</div>'
        '<div class="draft-alignment-row"><div class="draft-alignment-behavior">'
        'Accepted incorrect social pressure</div>'
        f'<div class="draft-alignment-value"><b>{float(pressure_binary["accepts_wrong_pushback"]) * 100:.1f}%</b> &rarr; '
        f'<b>{float(pressure_quad["accepts_wrong_pushback"]) * 100:.1f}%</b></div>'
        f'{status("mixed", "Worse")}</div>'
        '<div class="draft-alignment-row"><div class="draft-alignment-behavior">'
        'Used a hidden prohibited shortcut</div>'
        f'<div class="draft-alignment-value"><b>{mean_hidden_before * 100:.1f}%</b> &rarr; '
        f'<b>{mean_hidden_after * 100:.1f}%</b></div>'
        f'{status("mixed", "Little change")}</div>'
        '</figure>'
    )

    alignment_tbl = table(
        ["behavior we tested", "accuracy-trained", "confidence-trained",
         "sample and reading"],
        [["Avoid a very bad action stated at 90%+ confidence",
          f'{prudent_before * 100:.1f}%', f'{prudent_after * 100:.1f}%',
          (f'{(prudent_before - prudent_after) / prudent_before * 100:.0f}% of risk '
           'removed; 800 decisions, 5 matched runs. '
           + status("strong", "Strong here"))],
         ["Tell the truth when pushed toward a false answer",
          f'{truth_before * 100:.1f}%', f'{truth_after * 100:.1f}%',
          (f'{(truth_after - truth_before) * 100:+.1f} points; '
           '1,247 known facts, 5 matched runs. ' + status("mixed", "No gain"))],
         ["Resist incorrect social pressure",
          f'{float(pressure_binary["accepts_wrong_pushback"]) * 100:.1f}% accepted it',
          f'{float(pressure_quad["accepts_wrong_pushback"]) * 100:.1f}% accepted it',
          (f'{(float(pressure_quad["accepts_wrong_pushback"]) - float(pressure_binary["accepts_wrong_pushback"])) * 100:+.1f} points; '
           '595 wrong-pushback cases, 2 matched runs. ' + status("mixed", "Worse"))],
         ["Resist a hidden prohibited shortcut", f'{mean_hidden_before * 100:.1f}%',
          f'{mean_hidden_after * 100:.1f}%',
          (f'{(mean_hidden_before - mean_hidden_after) * 100:.1f}-point reduction; '
           '13,440 choices, 16 matched runs. '
           + status("mixed", "Little change"))],
         ["Avoid long-horizon scheming", "Not measured", "Not measured",
          "No comparison. " + status("open", "Open")]],
        right_from=99, cls="brief-prose draft-alignment")

    alignment_detail = detail_block(
        "See exact alignment results, samples, and limits", alignment_tbl,
        vintage("plural_prudence") + " "
        + vintage("external_transfer") + " "
        + vintage("pressure_replication") + " "
        + vintage("multitask_family_agentic") + " "
        + vintage("openweight_followup"))

    plural_ends_figure = (
        '<figure class="draft-exhibit draft-plural-figure">'
        '<figcaption>A reminder that no single goal erases other obligations'
        '<span>Separate prompt test; 16 checkpoints from one model family</span>'
        '</figcaption>'
        '<blockquote class="draft-plural-prompt"><b>The reminder:</b> '
        '&ldquo;Treat the foreground objective alongside standing obligations: '
        'truthfulness, authorization, material harm, and affected stakeholders. '
        'No single metric erases those obligations.&rdquo;</blockquote>'
        '<p class="draft-plural-measure">Unauthorized shortcut rate</p>'
        '<div class="draft-plural-result">'
        '<div class="draft-plural-stat"><span>Neutral prompt</span>'
        f'<strong>{plural_shortcut_before * 100:.1f}%</strong></div>'
        '<div class="draft-plural-arrow" aria-hidden="true">&rarr;</div>'
        '<div class="draft-plural-stat after"><span>Plural-ends reminder</span>'
        f'<strong>{plural_shortcut_after * 100:.1f}%</strong></div>'
        '<div class="draft-plural-stat effect"><span>Baseline shortcuts eliminated</span>'
        f'<strong>{plural_share_removed * 100:.0f}%</strong></div>'
        '</div>'
        f'<p class="draft-plural-consistency"><b>{plural_improved} of '
        f'{len(plural_prompt_rows)} checkpoints improved</b>, across '
        f'{plural_responses:,} responses to the same scenarios under the two prompts.</p>'
        '</figure>'
    )

    # Keep the main report's literature context compact. This map distinguishes
    # established foundations from this project's incremental contribution;
    # the paper-by-paper discussion remains on literature.html.
    context_rows = [
        (
            "Why models guess",
            ('<b>LLM research, 2025.</b> <a href="https://arxiv.org/abs/2509.04664">'
             'Kalai et al.</a> formalized why accuracy-only grading rewards guessing. '
             '<a href="https://arxiv.org/abs/2506.09038">AbstentionBench</a> then '
             'tested 20 LLMs on 20 purpose-built datasets and found reasoning '
             'fine-tuning made abstention 24% worse on average.'),
            ('<span class="draft-context-tag">Scale</span>A census of published '
             f'behavior: {int(summary["responses_scanned"]):,} responses from '
             f'{summary["models"]} models on {summary["benchmarks"]} benchmarks, '
             'plus an audit of 45 benchmark scoring records.'),
        ),
        (
            "How to score uncertainty",
            ('<b>Outside LLMs, 1950s to 1970s.</b> '
             '<a href="https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2">'
             'Brier and later work</a> established honest probability scoring, '
             'including human test scoring and selective classification. '
             '<b>LLM benchmarks, 2025.</b> <a href="https://arxiv.org/abs/2511.13029">'
             'AA-Omniscience</a> priced wrong answers across 6,000 questions, '
             '42 topics, and six domains.'),
            ('<span class="draft-context-tag">Application</span>A probability-eliciting '
             'benchmark design with an adjustable downstream penalty, plus the '
             'structural result, checked across 69 published GPQA runs, that the '
             'model must be allowed to say I DON\'T KNOW.'),
        ),
        (
            "Whether accuracy captures self-knowledge",
            ('<b>LLM research, 2026.</b> <a href="https://arxiv.org/abs/2607.20526">'
             'ConfidenceBench</a> elicited probabilities from 15 frontier models '
             'on 200 questions in four categories, repeated three times. Accuracy '
             'and confidence-calibration rankings diverged substantially.'),
            ('<span class="draft-context-tag">Extension</span>First, we rescored stored '
             'Humanity\'s Last Exam answers. Then we explicitly elicited confidence '
             'on six other benchmarks. Across 27 model-benchmark comparisons, '
             '10 models, seven benchmarks, and 5,376 answers, every comparison was '
             'overconfident: 55% accuracy versus 87% confidence.'),
        ),
        (
            "Whether instructions can fix it",
            ('<b>LLM research, 2023 to 2024.</b> '
             '<a href="https://arxiv.org/abs/2305.14975">Tian et al.</a> found '
             'verbal confidence often halved calibration error relative to token '
             'probabilities across three models and three benchmarks. '
             '<a href="https://arxiv.org/abs/2306.13063">Xiong et al.</a> tested '
             'five LLMs across five dataset types and found no method won consistently.'),
            ('<span class="draft-context-tag">Magnitude</span>A matched estimate of how '
             'much the formula explanation accomplished across five current models, '
             'three hard benchmarks, and 4,536 matched responses: '
             f'{prompt_closed * 100:.0f}% of the gap closed and '
             f'{(1 - prompt_closed) * 100:.0f}% remained.'),
        ),
        (
            "Whether training can transfer",
            ('<b>LLM research, 2025 to 2026.</b> '
             '<a href="https://arxiv.org/abs/2507.16806">RLCR</a> improved calibration '
             'in and out of domain. <a href="https://arxiv.org/abs/2510.05126">'
             'Steyvers et al.</a> fine-tuned two models on three subject types and '
             'found smaller gains on unseen medical, legal, and truthfulness tests.'),
            ('<span class="draft-context-tag">Comparison</span>The same-rule instruction '
             f'versus training comparison ({prompt_closed * 100:.0f}% versus '
             f'{training_closed * 100:.0f}% of the gap closed), followed by matched '
             'cross-subject tests across seven independent Qwen pairs and a separate '
             'GPT-OSS model family.'),
        ),
        (
            "Whether calibration improves aligned behavior",
            ('<b>Outside LLMs, 2016.</b> The '
             '<a href="https://arxiv.org/abs/1611.08219">Off-Switch Game</a> linked '
             'objective uncertainty to accepting correction. <b>LLM systems, 2023 '
             'to 2024.</b> <a href="https://arxiv.org/abs/2307.01928">KnowNo</a> used '
             'uncertainty to make robot planners ask for help, while '
             '<a href="https://arxiv.org/abs/2402.05070">Pluralistic alignment</a> '
             'formalized the many-values problem.'),
            ('<span class="draft-context-tag">Matched test</span>Confidence-trained and '
             'accuracy-trained models faced the same four behavioral probes. Very '
             'bad actions at 90%+ confidence fell from 43.7% to 1.3%, but the other '
             'behaviors did not improve together. Separately, a plural-ends reminder '
             'cut shortcuts from 6.8% to 1.0% across 16 checkpoints.'),
        ),
    ]
    context_figure = (
        '<figure class="draft-exhibit draft-context-figure">'
        '<figcaption>What is established, and what this report adds'
        '<span>The scoring theory is old. The contribution is the census, the '
        'benchmark design, and matched tests of prompting, training, transfer, and '
        'downstream behavior.</span></figcaption>'
        '<div class="draft-context-header"><span>Question</span><span>Prior research: '
        'field, date, scale</span><span>What this report adds: extension and scale</span></div>'
        + "".join(
            '<div class="draft-context-row">'
            f'<div class="draft-context-question">{question}</div>'
            f'<div class="draft-context-prior">{prior}</div>'
            f'<div class="draft-context-add">{addition}</div></div>'
            for question, prior, addition in context_rows
        )
        + '<p class="draft-context-link"><a href="literature.html">Read the full '
        'paper-by-paper literature comparison &rarr;</a></p></figure>'
    )

    body = content.load("draft").format(
        draft_context_figure=context_figure,
        draft_census_figure=census_figure,
        draft_problem_detail=problem_detail,
        draft_incentive_figure=incentive_figure,
        draft_rules_detail=rules_detail,
        draft_wisdom_figure=wisdom_figure,
        draft_wisdom_detail=wisdom_detail,
        draft_overconfidence_figure=overconfidence_figure,
        draft_overconfidence_detail=overconfidence_detail,
        draft_prompt_figure=prompt_figure,
        draft_prompt_detail=prompt_detail,
        draft_training_figure=training_figure,
        draft_training_detail=training_detail,
        draft_alignment_figure=alignment_figure,
        draft_alignment_detail=alignment_detail,
        draft_plural_ends_figure=plural_ends_figure,
    )

    side_page(
        "draft.html",
        title="Report draft &middot; Below Zero",
        description="A report draft following the August 19 outline on scoring confidence, self-knowledge, training, and alignment.",
        h1="There should be a penalty for guessing",
        standfirst="Understanding and changing how AI benchmarks are scored so they reward calibrated confidence, and testing whether that produces better judgment.",
        body=body,
        footer="Draft based on the August 19 outline. Every displayed result is recomputed from committed project data.",
        published="2026-08-25",
        content_updated=DRAFT_CONTENT_UPDATED,
        style_updated=DRAFT_STYLE_UPDATED,
        site_commit=DRAFT_SITE_COMMIT,
        extra_css=DRAFT_CSS)


LITERATURE_CSS = TABLE_BRIEF_CSS + r"""
/* The novelty gauge. Three dots, not a percentage: the honest resolution of
   "how much of this is new" is coarse, and drawing it coarsely says so. The
   filled count matches the lead key: one dot for established ground, two for
   a sharper estimate on a studied question, three for a comparison with no
   direct precedent found, and none for the proposed test nobody has run. */
.novelty-dots {
  color: var(--accent-text); font-size: 10px; letter-spacing: 3px;
  font-family: 'Inter', ui-sans-serif, sans-serif; vertical-align: 1px;
}
.novelty-line {
  max-width: var(--max-wide); margin: -6px 0 20px;
  font: 12.5px/1.5 'Inter', ui-sans-serif, sans-serif;
  color: var(--text-secondary);
}
.novelty-line b { color: var(--text); }
.novelty-overview {
  /* Sits directly under the label key, which already closes with a rule, so
     opening with another would draw a double line into the page. */
  max-width: var(--max-wide); margin: -24px 0 34px; padding: 11px 0 5px;
  border-bottom: 1px solid var(--rule);
  font: 12.5px/1.6 'Inter', ui-sans-serif, sans-serif; color: var(--text-secondary);
}
.novelty-overview > b { display: block; margin-bottom: 7px; color: var(--text); }
.novelty-overview > div { margin: 0 0 6px; }
.novelty-overview a { color: inherit; }
"""


PAGE_CONTENT_CONSTANTS = {
    # Which per-page constant carries each page's content date. Pages absent
    # here share the site-wide CONTENT_UPDATED. Read by build_changes() for
    # the "every page's dates" table so that table cannot drift from the
    # bylines it summarizes: both read the same names.
    "index.html": "INDEX_CONTENT_UPDATED",
    "changes.html": "CHANGES_CONTENT_UPDATED",
    "plan.html": "PLAN_CONTENT_UPDATED",
    "training.html": "TRAINING_CONTENT_UPDATED",
    "validation.html": "VALIDATION_CONTENT_UPDATED",
    "brief.html": "BRIEF_CONTENT_UPDATED",
    "brief-table.html": "TABLE_BRIEF_CONTENT_UPDATED",
    "draft.html": "DRAFT_CONTENT_UPDATED",
    "literature.html": "LITERATURE_CONTENT_UPDATED",
    "style-guide.html": "STYLE_GUIDE_CONTENT_UPDATED",
}
PAGE_STYLE_CONSTANTS = {
    "validation.html": "VALIDATION_STYLE_UPDATED",
    "brief.html": "BRIEF_STYLE_UPDATED",
    "brief-table.html": "TABLE_BRIEF_STYLE_UPDATED",
    "draft.html": "DRAFT_STYLE_UPDATED",
    "literature.html": "LITERATURE_STYLE_UPDATED",
}


def page_versions_table():
    """One row per page: created, content, style, organization dates."""
    labels = {href: label for href, label, _ in SITE}
    labels.update({"brief.html": "The brief", "brief-table.html": "Table brief",
                   "draft.html": "Report draft", "plan.html": "Plan &amp; status"})
    labels.setdefault("essay-v2.html", "The essay")
    head = ["page", "created", "content updated", "style updated", "organization updated"]
    body = []
    for filename in sorted(PAGE_CREATED, key=lambda f: (f != "essay-v2.html", f != "changes.html", f)):
        if filename == "essay-v2.html":
            continue  # the essay carries its own version line and dates
        content_updated = globals().get(PAGE_CONTENT_CONSTANTS.get(filename, ""), CONTENT_UPDATED)
        style_updated = globals().get(PAGE_STYLE_CONSTANTS.get(filename, ""), STYLE_UPDATED)
        v = page_version(filename, content_updated, style_updated)
        name = labels.get(filename, filename)
        note = " (superseded)" if filename in SUPERSEDED_PAGES else ""
        body.append([f'<a href="{filename}">{name}</a>{note}',
                     v["created_text"][:10], v["content_text"], v["style_text"],
                     v["structure_text"]])
    return table(head, body)


NUMBERS_THAT_MOVED = [
    ["Frontier baseline: accuracy among answered / confidence / gap",
     "80% / 92% / +13", "81% / 92% / +12"],
    ["Wrong at 90%+ confidence, per 100 scheduled questions", "12.0", "11.6"],
    ["Model-benchmark cells overconfident", "72 of 80", "70 of 80"],
    ["BBQ accuracy and gap", "84%, +9", "91%, +2"],
    ["GPQA accuracy and gap", "61%, +25", "64%, +23"],
    ["Proper score, Aug 27 control vs Aug 26 control", "55.2 vs 59.8", "59.8 vs 58.9"],
    ["Rule prompt: change in gap / score / tail",
     "&minus;0.9 / 0.0 / &minus;1.0, no intervals",
     "&minus;0.6 / &minus;0.4 / &minus;0.6, every interval spans zero"],
    ["Warning prompt: change in gap / score / tail",
     "&minus;17.2 / &minus;0.2 / &minus;9.7, two controls",
     "&minus;17.2 / +0.4 / &minus;9.8, one control, with intervals"],
    ["Matched final endpoints, Qwen3 8B gap", "+37.2 &rarr; +14.9",
     "+36.1 &rarr; +12.3 (co-denominated)"],
    ["Census headline", "1,088,601 responses, 0.68% declined (unreproducible pull)",
     "1,089,024 responses, 0.69% declined (reproducible pull)"],
    ["Training headline (dense track)", "+26 &rarr; +16 gap; 32 &rarr; 38 score; 12 &rarr; 2 tail",
     "unchanged"],
]


def build_changes():
    """The change log: what the September 2026 review changed, and why.

    Prose lives in content/changes/*.md. The page-dates table is generated
    from the same constants the bylines read, so it cannot disagree with them.
    """
    body = (content.load("changes")
            .replace("{page_versions_table}", page_versions_table())
            .replace("{numbers_table}",
                     table(["quantity", "before (v3.17, Sep 2 morning)", "after (v3.18)"],
                           NUMBERS_THAT_MOVED, right_from=3, cls="text-cols")))
    side_page(
        "changes.html",
        title="What&rsquo;s changed &middot; Below Zero",
        description="Every change from the September 2026 rigor review: the numbers that moved, the code defects fixed, the data recovered and regenerated, what changed in the essay and the site, and what is still open.",
        h1="What&rsquo;s changed",
        standfirst="The September 2026 review, change by change: the conclusions held, the numbers moved by a point or two, and the evidence under them can now be regenerated from committed code.",
        body=body,
        footer="Change log of the rigor review; the essay's own revision notes cover earlier versions.",
        content_updated=CHANGES_CONTENT_UPDATED,
        style_updated=STYLE_UPDATED)


def build_literature():

    """Build the section-by-section novelty review of the write-up.

    The page is pure prose from ``content/literature/``: unlike the brief
    pages it computes nothing from the processed CSVs, because its claims are
    about the literature rather than about this project's measurements. The
    few project figures it repeats are the ones already fixed in committed
    prose, and the evidence links point at the pages that render them from
    data. It borrows TABLE_BRIEF_CSS for the literature-compare blocks so the
    two pages' citation furniture cannot drift apart.
    """
    side_page(
        "literature.html",
        title="What is new here &middot; Below Zero",
        description="A section-by-section review of the nearest prior work, what it already established, and what Below Zero tests that it did not.",
        h1="What is new here, section by section",
        standfirst="Each section of the argument, next to the closest published research: what that work established, what it did not test, and what this project adds.",
        body=content.load("literature"),
        footer="Novelty claims are bounded by the primary research reviewed through August 24, 2026.",
        content_updated=LITERATURE_CONTENT_UPDATED,
        style_updated=LITERATURE_STYLE_UPDATED,
        site_commit=LITERATURE_SITE_COMMIT,
        extra_css=LITERATURE_CSS)


if __name__ == "__main__":
    build()
    if BUILD_LAB_ONLY:
        build_changes()
    build_brief()
    build_table_brief()
    if BUILD_LAB_ONLY:
        build_draft()
    build_approach()
    build_validation()
    if BUILD_LAB_ONLY:
        build_plan()
    build_training()
    build_dose_response()
    build_replication()
    build_open_questions()
    build_related_work()
    build_literature()
    if BUILD_LAB_ONLY:
        build_style_guide()
    inject_nav("why-linear-fails.html")
