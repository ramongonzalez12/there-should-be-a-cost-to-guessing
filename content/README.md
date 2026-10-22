# Editing the write-up

The prose of each content-driven findings page lives here, one file per section,
numbered so the running order of the argument is the directory listing.
`content/index/` builds the full findings page, `content/brief/` builds the
narrative brief, and `content/brief-table/` builds the table-first working
outline. `content/draft/` follows the report outline while replacing its
illustrative examples with verified results. **These files are the source.** Generated HTML under
`site/below-zero/` is replaced the next time anyone builds.

## The loop

```bash
# 1. edit whatever you like in content/index/
# 2. rebuild
python3 scripts/build_site.py
# 3. look at it
cd site/below-zero && python3 -m http.server 8077   # then open localhost:8077
```

A test fails if the committed page and these files disagree, so a rebuild you
forgot shows up as a red suite rather than as a page quietly contradicting its
own source.

## The markup

Write prose. Blank lines separate blocks. Line breaks inside a paragraph are
fine and have no effect on the rendered page, so wrap wherever it reads well.

    ## anchor | Section title     starts a section. The anchor is what the
                                  navigation rail links to; changing it means
                                  changing the rail in build_site.py too, and a
                                  test will tell you if you forget.

    ### Sub-heading               a heading inside a section

    - key: **Lead-in.** Rest.     an item in the accented findings list.
                                  Consecutive lines make one list; a line
                                  without the marker continues the item above.

    > Quoted text                 a blockquote

    ^ Caption text                small print under a table

    :::note A heading             a callout box
    Body of the note.
    :::

    :::rule                       a formula block, one row per line
    correct -> 2p - p&sup2;
    :::

    :::details Summary line       a section the reader has to open
    Body.
    :::

Inline: `**bold**`, `*emphasis*`, `` `code` ``, `[link text](page.html)`.
HTML entities such as `&mdash;`, `&ldquo;` and `&minus;` pass through as typed.
Underscores are not markup, so placeholder names are safe.

## The braces are not decoration

`{total}`, `{bench_table}`, `{ratio_lo}` and the rest are filled in at build
time from the CSVs in `data/processed/`. **Leave them alone.** They are what
makes it impossible for a number quoted in a sentence to drift away from the
table it came from. If you want to change a figure, change the data or the code
that computes it, not the sentence.

If you delete one by accident the build fails loudly, which is the intended
behaviour.

## What is not here

The masthead, the stat strip, the contents box, the tables and the footer are
built by `scripts/build_site.py`, because they are structure and figures rather
than prose. The contents box currently sits in `10-findings.md` as raw HTML; it
is the one piece of furniture that lives among the prose.
