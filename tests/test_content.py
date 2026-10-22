"""The prose renderer, and the guarantee that content/ is the page's real source.

Two kinds of test here. The first exercise each construct the write-up uses. The
second is the one that matters: it rebuilds the page from content/ and asserts
the result matches the committed HTML, so nobody can edit the prose, forget to
rebuild, and leave the published page saying something the source does not.
"""
from __future__ import annotations

import importlib.util
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "scripts", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


content = _load("content")


# --- inline marks -----------------------------------------------------------

def test_bold_and_emphasis():
    assert content.inline("**loud** and *soft*") == "<b>loud</b> and <em>soft</em>"


def test_code_and_link():
    assert content.inline("`c` and [there](x.html)") == (
        '<code>c</code> and <a href="x.html">there</a>')


def test_marks_span_a_line_break():
    """The bug that shipped literal asterisks into the page.

    Prose here is hard-wrapped, so a bold run or a link routinely straddles a
    newline. Rendering line by line means neither half ever sees the other and
    the marks survive into the HTML as text.
    """
    assert content.inline("**one\ntwo**") == "<b>one\ntwo</b>"
    assert content.inline("[a\nb](u)") == '<a href="u">a\nb</a>'


def test_underscores_are_not_emphasis():
    """Placeholder names are full of underscores and must survive untouched."""
    assert content.inline("{fn_hle_n} and {bench_table}") == (
        "{fn_hle_n} and {bench_table}")


def test_entities_and_raw_html_pass_through():
    assert content.inline("2p &minus; p&sup2; <br> &ldquo;x&rdquo;") == (
        "2p &minus; p&sup2; <br> &ldquo;x&rdquo;")


# --- blocks -----------------------------------------------------------------

def test_paragraph_keeps_its_line_breaks():
    assert content.render("one\ntwo") == "<p>one\ntwo</p>"


def test_section_heading_carries_its_anchor():
    assert content.render("## goal | What this is for") == (
        '<h2 id="goal">What this is for</h2>')


def test_heading_without_an_anchor_is_an_error():
    """The anchor is what the section nav links to, so it cannot be optional."""
    with pytest.raises(content.ContentError, match="anchor"):
        content.render("## What this is for")


def test_key_list_and_wrapped_items():
    out = content.render("- key: **A.** one\ntwo\n- key: **B.** three")
    assert out == ('<ul class="key">\n'
                   "<li><b>A.</b> one\ntwo</li>\n"
                   "<li><b>B.</b> three</li>\n</ul>")


def test_caption_and_blockquote():
    assert content.render("^ small print") == '<p class="cap">small print</p>'
    assert content.render("> quoted") == "<blockquote>quoted</blockquote>"


def test_note_rule_and_details():
    assert content.render(":::note Heading\nbody\n:::") == (
        '<div class="note"><b>Heading</b>\nbody</div>')
    assert content.render(":::rule\na\nb\n:::") == (
        '<div class="rule">\na<br>\nb\n</div>')
    assert content.render(":::details Open me\ntext\n:::") == (
        "<details><summary>Open me</summary>\n<p>text</p>\n</details>")


def test_bare_placeholder_is_not_wrapped_in_a_paragraph():
    """A table injects its own markup; wrapping it in <p> would nest badly."""
    assert content.render("{bench_table}") == "{bench_table}"


def test_unknown_directive_raises():
    """Silently dropping a directive loses a paragraph nobody notices."""
    with pytest.raises(content.ContentError, match="unknown directive"):
        content.render(":::sidebar Hello\nbody\n:::")


def test_unclosed_fence_raises():
    with pytest.raises(content.ContentError, match="never closed"):
        content.render(":::note Heading\nbody")


# --- the page's real source -------------------------------------------------

# Every content directory and the page it renders into, with the minimum
# section count that page promises. A new content-driven page joins this list
# or it silently escapes all three guarantees below.
CONTENT_PAGES = [
    ("index", "index.html", 6),
    ("changes", "changes.html", 8),
    ("brief", "brief.html", 5),
    ("brief-table", "brief-table.html", 7),
    ("draft", "draft.html", 6),
    ("literature", "literature.html", 6),
]
# The working pages' prose (changes, draft) stays in the lab; the public tree
# has neither the directories nor the pages.
CONTENT_PAGES = [c for c in CONTENT_PAGES if os.path.isdir(os.path.join(ROOT, "content", c[0]))]


@pytest.mark.parametrize("directory,page,minimum", CONTENT_PAGES)
def test_every_section_has_prose_and_an_anchor(directory, page, minimum):
    sections = content.sections(directory)
    assert len(sections) >= minimum
    for anchor, title in sections:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", anchor), anchor
        assert title.strip()


@pytest.mark.parametrize("directory,page,minimum", CONTENT_PAGES)
def test_section_nav_matches_the_content_files(directory, page, minimum):
    """The rail and the prose cannot disagree about what is on the page.

    Renaming a section in content/ without updating the nav would leave a link
    pointing at an anchor that no longer exists, which is silent in a browser.
    """
    build = _load("build_site")
    rail = [anchor for anchor, _ in build.SECTION_NAV[page]]
    assert rail == [anchor for anchor, _ in content.sections(directory)]


@pytest.mark.parametrize("directory,page,minimum", CONTENT_PAGES)
def test_committed_page_matches_the_content_files(directory, page, minimum):
    """The published HTML is what content/ currently renders to.

    This is the test that makes content/ the source rather than a copy. Edit the
    prose, forget to run build_site.py, and this fails instead of the site
    quietly disagreeing with its own source.
    """
    body = content.load(directory)
    with open(os.path.join(ROOT, "site", "below-zero", page),
              encoding="utf-8") as fh:
        committed = fh.read()
    # Compare the prose region only: everything else on the page is furniture
    # this test has no opinion about.
    for chunk in re.findall(r"<p>[^<{]{40,}?</p>", body):
        assert chunk in committed, (
            f"content/ contains prose that the committed page does not:\n"
            f"{chunk[:160]}...\nRun: python3 scripts/build_site.py")
