"""The essay's public data step (scripts/essay_data_step.py) and its outputs.

Fast checks run everywhere: every exhibit has its CSV with columns and no
comment lines; the figure CSVs and key numbers rebuild exactly from the
committed tables and inputs; the manifest records every file. The full
rebuild from graded rows (about seven minutes, two bootstraps) is
`python scripts/essay_data_step.py --check`, run by its own CI step.

Lab-only (skipped where the v6.69 page is absent): every figure CSV's values
appear among the marks the published page draws, as the page prints them
(rounded labels, aria-labels and titles, data attributes, the embedded gate
data). A value passes when one of its renderings (the page's whole-number or
one-decimal rounding, or the full value within 0.006 of a full-precision
attribute) is among the exhibit's own tokens.
"""
from __future__ import annotations

import csv
import html as htmlmod
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import essay_data_step as step

DATA = ROOT / "data/essay"
# The page the marks are checked against: the published layer by default; a
# later layer's build can be named with BZ_MARKS_PAGE (a path).
PAGE = Path(os.environ.get("BZ_MARKS_PAGE") or step.LAB_LAYER / "essay-v669-retrain.html")
FIGURES = list(step.FIGURES)


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ----------------------------------------------------------------- everywhere

def test_every_exhibit_has_a_csv():
    assert len(FIGURES) == 25
    for fid in FIGURES:
        path = DATA / "figures" / f"{fid}.csv"
        assert path.is_file(), fid
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        assert not first.startswith("#"), f"{fid}: comment line"
        assert read(path), f"{fid}: no rows"
    assert sorted(p.stem for p in (DATA / "figures").glob("*.csv")) == sorted(FIGURES)


def test_figures_and_key_numbers_rebuild_from_committed_tables():
    """The tables-to-figures half of the step, rebuilt in a temp dir: identical bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        step.build_figures(DATA / "tables", out)
        for fid in FIGURES:
            assert (out / f"{fid}.csv").read_bytes() == (DATA / "figures" / f"{fid}.csv").read_bytes(), fid
    audit = step.confidence_audit(step.load_graded())
    assert step.key_numbers(DATA / "tables", audit) == json.loads((DATA / "key-numbers.json").read_text())


def test_manifest_records_every_file():
    manifest = json.loads((DATA / "manifest.json").read_text())
    listed = set(manifest["files"])
    on_disk = {p.relative_to(DATA).as_posix() for sub in ("tables", "figures") for p in (DATA / sub).rglob("*")
               if p.is_file()} | {"key-numbers.json"}
    assert listed == on_disk
    for rel, entry in manifest["files"].items():
        assert step.sha(DATA / rel) == entry["sha256"], rel
    carried = {rel.split("/", 1)[1] for rel, e in manifest["files"].items() if e["status"] != "rebuilt"}
    assert carried == set(step.CARRIED)


def test_census_exclusions_give_both_figures():
    import census_exclusions as ce
    f = ce.figures()
    assert len(ce.left_out()) == 14
    assert f["all"]["benchmarks"] - f["compared"]["benchmarks"] == 14
    row = read(DATA / "figures/tbl-census.csv")[0]
    assert int(row["benchmarks"]) == f["compared"]["benchmarks"] and int(row["responses"]) == f["compared"]["responses"]


def test_battery_cohort_carries_no_lab_paths():
    rows = read(DATA / "tables/battery_cohort.csv")
    assert not [c for c in rows[0] if c.endswith("_db")]
    assert {r["max_tokens"] for r in rows} and all(r["reasoning"] for r in rows)
    text = (DATA / "tables/battery_cohort.csv").read_text()
    assert "lab/" not in text and "/Use" + "rs/" not in text


# ----------------------------------------------------------------- lab: the page's marks

def exhibit(page: str, fid: str) -> str:
    """The rendered element carrying id=fid, balanced on its own tag."""
    i = page.index(f'id="{fid}"')
    s = page.rindex("<", 0, i)
    tag = re.match(r"<(\w+)", page[s:]).group(1)
    depth = 0
    for m in re.compile(rf"<(/?){tag}\b").finditer(page, s):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return page[s:page.index(">", m.start()) + 1]
    raise AssertionError(fid)


def tokens(fragment: str) -> tuple[set[str], list[float], str]:
    """(printed number tokens, full-precision data-attribute values, visible text) of an exhibit.

    Printed tokens come from the visible text, aria-labels, titles and data-*
    attribute values (never geometry), with the minus sign normalized and
    thousands separators removed."""
    no_script = re.sub(r"<script\b.*?</script>", " ", fragment, flags=re.DOTALL)
    attrs = re.findall(r'\s(?:aria-label|title|data-[a-z0-9-]+)="([^"]*)"', no_script)
    text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", no_script))
    blob = " ".join([text] + [htmlmod.unescape(a) for a in attrs]).replace("−", "-").replace(" ", "")
    blob = re.sub(r"(?<=\d),(?=\d{3})", "", blob)
    printed = {re.sub(r"^-0$", "0", t) for t in re.findall(r"-?\d+(?:\.\d+)?", blob)}
    fulls = [float(v) for v in re.findall(r'\sdata-[a-z-]+="(-?\d+\.\d{3,})"', no_script)]
    return printed, fulls, re.sub(r"\s+", " ", text)


TYPOGRAPHY = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-",
                            "\u2014": "-", "\u2212": "-", "\u00a0": " "})


def norm(text: str) -> str:
    """Labels compared as text: curly quotes and apostrophes, dashes, and
    non-breaking spaces are typography, not data (numbers are never compared this way)."""
    return " ".join(text.translate(TYPOGRAPHY).split())


def renderings(value: float, decimals: int) -> set[str]:
    half_up = math.floor(value * 10 ** decimals + 0.5) / 10 ** decimals
    out = {f"{value:.{decimals}f}", f"{half_up:.{decimals}f}"}
    if decimals:
        out |= {s.rstrip("0").rstrip(".") for s in out}
    return {"0" if s in ("-0", "-0.0") else s for s in out}


# Per exhibit: (column, decimals as printed, factor to the full-precision attribute scale or None).
CHECKS = {
    "tbl-census": [("benchmarks", 0, None), ("responses", 0, None), ("uncertainty_or_decline_pct", 1, None)],
    "tbl-census-benchmarks": [("responses", 0, None)],
    "tbl-parity": [("published_accuracy_pct", 1, None), ("our_accuracy_pct", 1, None),
                   ("expected_range_low_pct", 1, None), ("expected_range_high_pct", 1, None)],
    "fig-scissors": [("accuracy_pct", 0, 1), ("stated_confidence_pct", 0, None), ("overconfidence_gap_pts", 0, None)],
    "fig-confsplit": [("value", 0, None)],
    "fig-every-model": [("accuracy_pct", 1, None), ("stated_confidence_pct", 1, None)],
    "fig-behaviour": [("accuracy_pct", 0, None), ("stated_confidence_pct", 0, None)],
    "fig-vintage": [("stated_confidence_pct", 0, 0.01), ("accuracy_pct", 0, 0.01)],
    "fig-students": [("right_of_100", 0, None), ("confidence_on_right_pct", 0, None),
                     ("confidence_on_wrong_pct", 0, None)],
    "tbl-ev-true": [("report_0pct", 2, None), ("report_60pct", 2, None), ("report_100pct", 2, None)],
    "fig-spread": [("adjusted_accuracy_pts", 0, 1), ("accuracy_pct", 0, 1), ("stated_confidence_pct", 0, 1)],
    "tbl-model-by-model": [("overconfidence_gap_pts", 0, None), ("wrong_at_90_plus_per_100", 0, None),
                           ("accuracy_all_questions_pct", 0, None), ("adjusted_accuracy_pts", 0, None)],
    "fig-prompt-moves": [("gap_baseline_pts", 1, None), ("gap_explaining_scoring_pts", 1, None),
                         ("gap_warning_pts", 1, None)],
    "fig-training-summary": [("effort_tokens", 0, None), ("accuracy_pct", 0, None), ("stated_confidence_pct", 0, None),
                             ("overconfidence_gap_pts", 0, None), ("adjusted_accuracy_pts", 0, None)],
    "fig-noreason-bars": [("stated_confidence_pct", 0, None), ("accuracy_pct", 0, None),
                          ("overconfidence_gap_pts", 0, None), ("adjusted_accuracy_pts", 0, None)],
    "fig-noreason-attempts": [("stated_confidence_pct", 0, None), ("score_pts", 0, None),
                              ("question_average_pts", 0, None)],
    "fig-noreason-runs": [("missed_on_every_attempt_pct", 0, None), ("gap_reduction_pts", 0, None)],
    "fig-noreason-effort": [("effort_tokens", 0, None), ("accuracy_pct", 0, None), ("stated_confidence_pct", 0, None),
                            ("overconfidence_gap_pts", 0, None)],
    "fig-noreason-approaches": [("effort_tokens", 0, None), ("accuracy_pct", 0, None),
                                ("stated_confidence_pct", 0, None), ("overconfidence_gap_pts", 0, None)],
    "fig-safer-pushback": [("stated_confidence_pct", 0, None), ("gave_in_to_wrong_answer_pct", 0, None)],
}
# Rows a chart does not print a label for, checked another way below.
SKIP_ROWS = {
    # [1.E] prints each model's values on hover (one decimal, data attributes); the period averages as labels.
    "fig-behaviour": lambda r: r["row"] == "model",
}
# Columns whose text labels must appear in the exhibit.
LABELS = {
    "tbl-census-benchmarks": "benchmark", "tbl-developers": "model_name", "tbl-parity": "model_and_published_setup",
    "fig-scissors": "benchmark", "fig-every-model": "model_name", "fig-vintage": "model_name",
    "fig-students": "student", "fig-spread": "model_name", "tbl-model-by-model": "model_name",
    "tbl-measures": "model_name", "fig-prompt-moves": "model_name", "fig-training-summary": "arm",
    "fig-noreason-bars": "arm", "fig-noreason-effort": "model",
    "fig-noreason-approaches": "approach", "fig-model-thresholds": "model_name", "fig-confsplit": "category",
}


@pytest.fixture(scope="module")
def page() -> str:
    if not PAGE.is_file():
        pytest.skip("the v6.69 essay page is not in this checkout")
    return PAGE.read_text(encoding="utf-8")


@pytest.mark.parametrize("fid", FIGURES)
def test_values_appear_in_the_page_marks(page, fid):
    fragment = exhibit(page, fid)
    if fid == "fig-scissors":
        # The Summary's copy of [1.B] draws the same marks and carries their hover labels.
        fragment += exhibit(page, "fig-scissors-summary")
    printed, fulls, text = tokens(fragment)
    rows = read(DATA / "figures" / f"{fid}.csv")
    missing = []
    skip = SKIP_ROWS.get(fid, lambda r: False)
    for col, decimals, factor in CHECKS.get(fid, []):
        for r in rows:
            if skip(r) or r[col] == "":
                continue
            v = float(r[col])
            if renderings(v, decimals) & printed:
                continue
            if factor is not None and any(abs(f - v * factor) <= 0.006 * max(factor, 1) for f in fulls):
                continue
            missing.append((col, r[col]))
    assert not missing, f"{fid}: values not among the page's marks: {missing[:8]}"
    label = LABELS.get(fid)
    if label:
        flat = norm(text)
        absent = sorted({r[label] for r in rows if r[label] and norm(r[label]) not in flat})
        assert not absent, f"{fid}: labels not printed: {absent[:8]}"


def test_model_points_match_hover_values(page):
    """[1.D] and [1.E] draw each model at data-acc / data-conf (one decimal)."""
    for fid in ("fig-every-model", "fig-behaviour"):
        marks = {m[0]: (float(m[1]), float(m[2])) for m in
                 re.findall(r'data-model="([^"]+)"[^>]*data-acc="([\d.]+)" data-conf="([\d.]+)"', exhibit(page, fid))}
        rows = [r for r in read(DATA / "figures" / f"{fid}.csv") if r.get("row", "model") == "model"]
        assert len(marks) == len(rows) == 50
    rows = {r["model"]: r for r in read(DATA / "figures/fig-every-model.csv")}
    for model, (acc, conf) in marks.items():
        assert abs(float(rows[model]["accuracy_pct"]) - acc) <= 0.06 and abs(float(rows[model]["stated_confidence_pct"]) - conf) <= 0.06


def test_gate_values_match_embedded_data(page):
    """The threshold exhibit's embedded data, model by model and threshold by threshold."""
    data = json.loads(re.search(r'<script type="application/json" id="gate-observed-data">(.*?)</script>',
                                page, re.DOTALL).group(1))
    rows = read(DATA / "figures/fig-model-thresholds.csv")
    values = {(e["id"], round(float(t) * 100)): v for e in data for t, v in e["values"].items()}
    assert len(data) == 51 and len(rows) == 51 * len(step.GATE_THRESHOLDS)
    for r in rows:
        v = values[r["model"] or "all", int(r["threshold_pct"])]
        assert abs(float(r["questions_with_allowed_answer_pct"]) - v["coverage"]) <= 0.006
        assert abs(float(r["wrong_per_100_questions"]) - v["wrong"]) <= 0.006
        if r["wrong_among_allowed_pct"] != "":
            assert abs(float(r["wrong_among_allowed_pct"]) - v["risk"]) <= 0.006


def test_formula_curves_match_their_paths(page):
    """[2.B] and [2.C] draw 101 points; their CSVs hold the same 101 reports, and the labeled values agree."""
    for fid, labels in (("fig-score-build", {"0.25", "0.75", "1", "2"}), ("fig-payoff-curve", {"0.36", "0.2"})):
        fragment = exhibit(page, fid)
        paths = re.findall(r'<(?:path|polyline)[^>]*(?: d| points)="([^"]+)"', fragment)
        assert any(len(re.findall(r"-?\d+\.?\d*", d)) // 2 == 101 for d in paths), fid
        assert len(read(DATA / "figures" / f"{fid}.csv")) == 101
        printed, _f, _t = tokens(fragment)
        assert labels <= printed, (fid, labels - printed)
    rows = {int(r["confidence_reported_pct"]): float(r["expected_points"]) for r in read(DATA / "figures/fig-payoff-curve.csv")}
    assert renderings(rows[60], 2) & {"0.36"} and renderings(rows[100], 2) & {"0.20", "0.2"}


def test_measures_card_all_models(page):
    """The measures card's default (all models) tiles."""
    printed, _f, _t = tokens(exhibit(page, "tbl-measures"))
    row = read(DATA / "figures/tbl-measures.csv")[0]
    for col in ("overconfidence_gap_pts", "wrong_at_90_plus_per_100", "accuracy_pct", "adjusted_accuracy_pts"):
        assert renderings(float(row[col]), 0) & printed, col


def test_attempt_panels_match_the_page_that_named_them():
    """[3.x]'s panel heads track the essay's copy: inputs record the page commit
    and item that last changed them, and that page prints exactly those heads."""
    lit = json.loads((DATA / "inputs/figure-inputs.json").read_text())["code_literals"]["attempt_panels"]
    proc = subprocess.run(["git", "show", f"{lit['commit']}:{lit['source']}"], cwd=ROOT, capture_output=True,
                          text=True, check=False)
    if proc.returncode:
        pytest.skip("the page commit that named the panels is not in this checkout")
    flat = norm(tokens(exhibit(proc.stdout, "fig-noreason-attempts"))[2])
    rows = read(DATA / "figures/fig-noreason-attempts.csv")
    assert list(dict.fromkeys(r["panel"] for r in rows)) == lit["titles"]
    assert all(norm(t) in flat for t in lit["titles"])


def test_roster_reasons_follow_the_recorded_causes():
    """Each left-out model's reason is the roster's sentence for it: it opens
    with the label of its recorded cause, quotes its own count, and
    inputs/models.csv carries the same text."""
    lit = json.loads((DATA / "inputs/figure-inputs.json").read_text())["code_literals"]["roster_exclusion_reasons"]
    assert lit["source"] and lit["commit"] and lit["item"] and lit["cause_source"]["sha256"]
    left_out = [r for r in read(DATA / "figures/tbl-developers.csv") if r["status"] == "not included"]
    assert {r["model"] for r in left_out} == set(lit["reasons"])
    reasons = {r["model"]: r["exclusion_reason"] for r in read(DATA / "inputs/models.csv") if r["exclusion_reason"]}
    for r in left_out:
        expected = step.exclusion_reason(lit["reasons"][r["model"]], int(r["baseline_responses_returned"]),
                                         int(r["baseline_responses_scheduled"]))
        assert r["why_not_included"] == expected == reasons[r["model"]], r["model"]


def test_roster_reasons_match_the_page_that_worded_them():
    """The page commit the inputs name prints exactly these sentences."""
    lit = json.loads((DATA / "inputs/figure-inputs.json").read_text())["code_literals"]["roster_exclusion_reasons"]
    proc = subprocess.run(["git", "show", f"{lit['commit']}:{lit['source']}"], cwd=ROOT, capture_output=True,
                          text=True, check=False)
    if proc.returncode:
        pytest.skip("the page commit that worded the reasons is not in this checkout")
    flat = norm(tokens(exhibit(proc.stdout, "tbl-developers"))[2])
    absent = [m for m, r in lit["reasons"].items() if norm(r["text"]) not in flat]
    assert not absent, absent


@pytest.mark.parametrize("reason,returned", [
    ({"cause": "outage", "text": "Outage: x (80 of 800 responses by the October 8 freeze)."}, 80),
    ({"cause": "usability_gate", "text": "Provider failure on its OpenRouter route: x (80 of 800 responses by the October 8 freeze)."}, 80),
    ({"cause": "usability_gate", "text": "Usability check: x (81 of 800 responses by the October 8 freeze)."}, 80),
    ({"cause": "unfinished", "text": "Unfinished at the freeze: x (80 of 800 responses by the October 9 freeze)."}, 80),
])
def test_exclusion_reason_fails_on_a_wrong_label_or_count(reason, returned):
    with pytest.raises(SystemExit, match="exclusion cause"):
        step.exclusion_reason(reason, returned, 800)


def test_open_weight_models_match_the_page(page):
    """[1.F] boxes the models whose weights are published: the CSV flags exactly
    the models the page marks (12 on v6.69 to v6.71), no more and no fewer."""
    marked = {}
    for flag, model in re.findall(r'<g class="vl-model" data-open-weight="(true|false)" data-model="([^"]+)"',
                                  exhibit(page, "fig-vintage")):
        marked.setdefault(model, flag == "true")
    flagged = {r["model"] for r in read(DATA / "figures/fig-vintage.csv") if r["open_weight"] == "yes"}
    assert marked and flagged == {m for m, v in marked.items() if v}, sorted(flagged ^ {m for m, v in marked.items() if v})


def test_census_benchmark_rates(page):
    """The census fold prints each rate as 0%, <0.1%, or to one decimal."""
    _p, _f, text = tokens(exhibit(page, "tbl-census-benchmarks"))
    flat = norm(text)
    for r in read(DATA / "figures/tbl-census-benchmarks.csv"):
        rate = float(r["uncertainty_or_decline_pct"])
        shown = "0%" if rate == 0 else "<0.1%" if rate < 0.1 else f"{rate:.1f}%"
        assert norm(f"{r['benchmark']} {int(r['responses']):,} {shown}") in flat, r["benchmark"]


def test_roster_counts(page):
    """The roster's left-out models: every response count the page quotes
    ("(N of 800") is one of this file's counts, as often as the file has it."""
    from collections import Counter
    _p, _f, text = tokens(exhibit(page, "tbl-developers"))
    printed = Counter(re.findall(r"\((\d+) of (\d+)", norm(text)))
    ours = Counter((r["baseline_responses_returned"], r["baseline_responses_scheduled"])
                   for r in read(DATA / "figures/tbl-developers.csv") if r["status"] == "not included")
    assert printed and not printed - ours, sorted(printed - ours)


BINDING = ROOT / "lab/data_sharing/exhibits-binding.csv"


@pytest.mark.skipif(not BINDING.is_file(), reason="the lab's exhibit binding is not in this checkout")
def test_binding_covers_every_download():
    """Every exhibit in the inventory's binding has a file, except the three empty
    anchors and the Summary's copy of [1.B] (which links the [1.B] file)."""
    ids = [r["exhibit_id"].split(" ")[0] for r in read(BINDING)]
    no_file = {"tbl-response-coverage", "tbl-survey", "tbl-retest", "fig-scissors-summary"}
    assert sorted(set(ids) - no_file) == sorted(FIGURES)


def test_readme_counts_match_the_data():
    """Every count the data README states, recomputed from the files it describes."""
    import census_exclusions as ce
    text = (DATA / "README.md").read_text()
    graded = step.load_graded()
    models = {r["model"] for r in graded}
    items = {r["item_id"] for r in graded}
    benches = {r["benchmark"] for r in graded}
    prompts = {r["contract"] for r in graded}
    f = ce.figures()
    manifest = json.loads((DATA / "manifest.json").read_text())
    tables = [k for k in manifest["files"] if k.startswith("tables/")]
    carried = [k for k in tables if manifest["files"][k]["status"] != "rebuilt"]
    receipts = gzip_rows(DATA / "graded/receipts/math500-judge-replacement.csv.gz")
    words = {15: "Fifteen", 14: "Fourteen"}
    claims = {
        f"{len(models)} models answering the same\n{len(items)} questions (100 from each of {['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight'][len(benches)]} benchmarks) under {['zero', 'one', 'two', 'three', 'four'][len(prompts)]} prompts",
        f"| {len(FIGURES)} files |", f"| {len(tables)} files |", f"| {len(graded):,} rows |", f"| {receipts:,} rows |",
        f"| {len([p for p in (DATA / 'inputs').iterdir() if p.is_file()])} files |",
        f"{words[len(tables) - len(carried)]} tables are rebuilt from the graded rows. {words[len(carried)]} are carried",
        f"{f['all']['responses']:,} published responses on {f['all']['benchmarks']} benchmarks",
        f"{f['all']['rate'] * 100:.2f}% contain an uncertainty or decline phrase",
        f"[1.A] compares the {f['compared']['benchmarks']}",
        f"{f['compared']['responses']:,}\nresponses, {f['compared']['rate'] * 100:.2f}%",
        f"The {len(ce.left_out())} left out are rubric-graded\nor not closed-form ({len(ce.LEFT_OUT['rubric'])}) and agentic tasks where the model can see an action\nfail ({len(ce.LEFT_OUT['agent'])})",
        f"the {len(step.skips())} item skips",
    }
    flat = " ".join(text.split())
    missing = [c for c in claims if " ".join(c.split()) not in flat]
    assert not missing, missing


def gzip_rows(path: Path) -> int:
    import gzip
    import io
    text = gzip.decompress(path.read_bytes()).decode("utf-8")
    return len(list(csv.DictReader(io.StringIO(text.split("\n", 1)[1]))))


# --------------------------------------------------------------------------
# The two behavior benchmarks (graded/behaviour/): rebuilt numbers bind the essay
# --------------------------------------------------------------------------

def test_behaviour_records_rebuild_the_essays_behaviour_numbers():
    assert step.check_behaviour() == []


def test_behaviour_check_fires_when_a_grade_changes(monkeypatch):
    """Negative control: flip one wrong-arm conversation's second answer and the
    rebuilt adoption no longer matches the essay's inputs."""
    real = step.load_behaviour

    def tampered(name):
        rows = real(name)
        if name == "pushback.csv.gz":
            r = next(r for r in rows if r["arm"] == "wrong" and r["condition"] == "base"
                     and r["first_formatted"] == r["second_formatted"] == "1"
                     and r["second_answer"] != r["asserted_answer"])
            r["second_answer"] = r["asserted_answer"]
        return rows
    monkeypatch.setattr(step, "load_behaviour", tampered)
    problems = step.check_behaviour()
    assert any("behaviour_summary_qn.base.wrong_adoption" in p for p in problems)
    assert any("fig-safer-pushback.csv: Before training" in p for p in problems)


def test_behaviour_records_carry_no_text():
    """Ids, model, condition, and grades only: every column is a short token."""
    for name in ("pushback.csv.gz", "shortcuts.csv.gz"):
        for row in step.load_behaviour(name):
            assert all(len(v) <= 64 and "\n" not in v for v in row.values()), name
