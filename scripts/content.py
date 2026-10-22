"""Turn the editable prose in content/ into the site's HTML.

Why this exists. The write-up used to live inside a Python string literal in
build_site.py, tangled with the tags around it, which made editing prose a
programming task. It now lives in content/, one file per section, in a small
markup that is mostly just writing. This module is the translator.

**It is deliberately not a Markdown implementation.** It supports exactly the
constructs this site uses and nothing else, for two reasons. A general parser
would be a third-party dependency, and this repository ships none on purpose:
when the argument is "your scoring should be inspectable," the tooling should
not need a lockfile to inspect. And a general parser would silently accept
syntax this site cannot render, so a writer would get a page that looked wrong
with no error. Here, an unrecognised directive raises.

The syntax, in full:

    ## anchor | Section title      a top-level section (the id the nav links to)
    ### Sub-heading                a heading inside one

    Ordinary paragraph text.       a paragraph. Line breaks inside are kept as
    Line breaks are preserved.     written; the browser reflows them anyway.

    - key: **Lead-in.** Rest.      an item in the accented findings list.
                                   Consecutive lines form one list.

    > Quoted text.                 a blockquote.

    ^ Caption under a table.       small print, for under a figure.

    :::note Heading of the note    a callout box with a small caps label.
    Body of the note.
    :::

    :::rule                        a formula block. Lines are joined with a
    correct -> 2p                  line break, so each stays on its own row.
    wrong   -> -p
    :::

    :::details Summary line        a collapsed section the reader opens.
    Body paragraphs.
    :::

    {bench_table}                  a computed value or table, injected by
                                   build_site.py from data/processed/. Left
                                   alone here, so no figure on the page can be
                                   edited into disagreeing with its CSV.

Inline, within any of the above:

    **bold**   *emphasis*   `code`   [link text](url)

HTML entities (&mdash;, &ldquo;, &minus;) pass through untouched, and so does
raw HTML, for the rare case that needs it. Underscores are NOT emphasis: the
placeholder names are full of them, and treating them as markup would mangle
every one.
"""

from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")


class ContentError(Exception):
    """A content file used syntax this renderer does not implement.

    Raised rather than ignored. A directive that is silently dropped produces a
    page missing a paragraph nobody notices for weeks.
    """


def inline(text: str) -> str:
    """Apply the inline marks. Order matters: ** before *, or bold eats italic."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text,
                  flags=re.DOTALL)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text, flags=re.DOTALL)
    # Link text may itself contain marks, so this runs last and only rewrites
    # the wrapper. The URL is left exactly as typed.
    text = re.sub(r"\[(.+?)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text, flags=re.DOTALL)
    return text


def _blocks(text: str):
    """Split into blocks on blank lines, keeping ::: fences whole.

    A fence can contain blank lines, so the usual "split on \\n\\n" would tear a
    note in half and lose its closing marker.
    """
    lines = text.split("\n")
    block, fence, i = [], False, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(":::"):
            if not fence:
                fence = True
            elif line.strip() == ":::":
                fence = False
                block.append(line)
                yield block
                block = []
                i += 1
                continue
        if not fence and not line.strip():
            if block:
                yield block
                block = []
        else:
            block.append(line)
        i += 1
    if fence:
        raise ContentError("a ::: block was opened and never closed")
    if block:
        yield block


def _fence(block: list[str]) -> str:
    """Render one ::: directive."""
    head = block[0][3:].strip()
    kind, _, title = head.partition(" ")
    body = block[1:-1]

    if kind == "note":
        if not title:
            raise ContentError(":::note needs a heading after it")
        return (f'<div class="note"><b>{inline(title)}</b>\n'
                + inline("\n".join(body)) + "</div>")

    if kind == "rule":
        # Each line is its own row of the formula, so they are joined with a
        # break rather than left to reflow as prose.
        # Each row is its own line here, so per-row inlining is correct: a
        # formula does not wrap.
        return ('<div class="rule">\n'
                + "<br>\n".join(inline(b) for b in body) + "\n</div>")

    if kind == "details":
        if not title:
            raise ContentError(":::details needs a summary line after it")
        inner = "\n".join(render("\n".join(body)).split("\n"))
        return (f"<details><summary>{inline(title)}</summary>\n{inner}\n</details>")

    raise ContentError(
        f"unknown directive ':::{kind}'. Known: note, rule, details.")


def render(text: str) -> str:
    """Render a content file body to HTML."""
    out = []
    for block in _blocks(text):
        first = block[0]

        if first.startswith(":::"):
            out.append(_fence(block))

        elif first.startswith("## "):
            anchor, sep, title = first[3:].partition("|")
            if not sep:
                raise ContentError(
                    f"'{first}' needs an anchor: '## anchor | Title'. The "
                    f"anchor is what the section navigation links to.")
            out.append(f'<h2 id="{anchor.strip()}">{inline(title.strip())}</h2>')

        elif first.startswith("### "):
            out.append(f"<h3>{inline(first[4:].strip())}</h3>")

        elif first.startswith("> "):
            # Joined BEFORE inlining, not after. Inlining line by line means a
            # **bold** or [link](url) that wraps across a line break never sees
            # both of its halves, and the marks survive into the page as
            # literal asterisks. Hard-wrapped prose does this constantly.
            out.append("<blockquote>"
                       + inline("\n".join(b.removeprefix("> ")
                                          for b in block))
                       + "</blockquote>")

        elif first.startswith("^ "):
            out.append('<p class="cap">'
                       + inline("\n".join(b.removeprefix("^ ")
                                          for b in block))
                       + "</p>")

        elif first.startswith("- key: "):
            items, current = [], None
            for line in block:
                if line.startswith("- key: "):
                    if current is not None:
                        items.append(current)
                    current = line[len("- key: "):]
                else:
                    # A wrapped continuation of the item above it.
                    current = f"{current}\n{line}"
            items.append(current)
            out.append('<ul class="key">\n'
                       + "\n".join(f"<li>{inline(i)}</li>" for i in items)
                       + "\n</ul>")

        elif first.lstrip().startswith("<"):
            # Raw HTML, passed through untouched. The escape hatch for the few
            # pieces of structural furniture that are not prose and would only
            # be obscured by inventing syntax for them. Deliberately narrow: if
            # you find yourself reaching for this to write a paragraph, the
            # paragraph wants real syntax instead.
            out.append("\n".join(block))

        elif re.fullmatch(r"\{\w+\}", first.strip()) and len(block) == 1:
            # A table or computed block, injected later. Emitted bare so it
            # does not end up wrapped in a paragraph.
            out.append(first.strip())

        else:
            out.append("<p>" + inline("\n".join(block)) + "</p>")

    return "\n".join(out)


def load(page: str) -> str:
    """Render every content file for a page, in filename order.

    Files are numbered (10-answer.md, 20-scoring.md) so the running order of
    the argument is visible in the directory listing and changing it is a
    rename rather than an edit to code.
    """
    directory = os.path.join(CONTENT, page)
    if not os.path.isdir(directory):
        raise ContentError(f"no content directory at {directory}")
    names = sorted(f for f in os.listdir(directory) if f.endswith(".md"))
    if not names:
        raise ContentError(f"no .md files in {directory}")
    parts = []
    for name in names:
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            body = fh.read().strip("\n")
        try:
            parts.append(render(body))
        except ContentError as exc:
            raise ContentError(f"{page}/{name}: {exc}") from exc
    return "\n".join(parts)


def sections(page: str) -> list[tuple[str, str]]:
    """The (anchor, title) of every top-level section, in order.

    The section navigation and the table of contents are both built from this,
    so adding a section to a content file adds it to both without touching the
    builder, and the three can never disagree about what is on the page.
    """
    found = []
    directory = os.path.join(CONTENT, page)
    for name in sorted(f for f in os.listdir(directory) if f.endswith(".md")):
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("## "):
                    anchor, sep, title = line[3:].partition("|")
                    if sep:
                        found.append((anchor.strip(), title.strip()))
    return found
