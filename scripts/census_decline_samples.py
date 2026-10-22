"""Are the closed-form declines real declines? Evidence, not assertion.

Four closed-form benchmarks show decline rates far above the rest
(healthbench 5.33%, lingoly_nocontext 5.06%, judgebench 3.67%, hle 3.52%),
which sits oddly beside a thesis that closed-form declining is near-zero.
Three structural explanations were proposed from the benchmarks' designs; this
script gets the evidence that confirms or kills them, by re-streaming just
those four and looking at what actually matched.

    python scripts/census_decline_samples.py

writes, into data/processed/:

    census_phrase_histogram.csv        which phrase fired, per benchmark
    census_decline_samples.csv         sampled hits with surrounding text
    census_sensitivity_by_benchmark.csv  the 3x3 grid, per benchmark

The histogram is the decisive one. `unknown` is in the phrase list as a bare
word, so it matches "solve for the unknown" and "a protein of unknown
function"; if that single phrase dominates a benchmark's hits, the rate is an
artifact of vocabulary rather than a measurement of abstention, and no reading
of the samples is needed to know it.

The samples exist for the cases the histogram cannot settle, where the phrase
is genuinely about not knowing but the sentence around it is a judgement about
someone else's answer, or a hedge that ends in a confident commitment anyway.

The sensitivity grid is per benchmark because the committed
census_sensitivity.csv covers GPQA Diamond only and, as of this writing, has
no producer in the repository at all. Extending it is the cheapest way to stop
the appendix resting on a table nothing regenerates.

Reads nothing local: the per-sample files are streamed from the EvalEval
datastore and discarded, as scripts/census.py and scripts/hle_confidence.py
do. No API key, no cost, a few minutes.

REVISION pins the datastore. Between the original census and now the store
grew from 1,319 sample files to roughly 2,551, so an unpinned re-run measures
a different corpus than the published 1,088,601 / 0.68% and would quietly
disagree with the page.
"""
import collections
import csv
import json
import os
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://huggingface.co/api/datasets/evaleval/EEE_datastore"
RAW = "https://huggingface.co/datasets/evaleval/EEE_datastore/resolve/{rev}/"
REVISION = os.environ.get("BELOWZERO_EEE_REVISION", "main")

PROC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "processed")

# The four whose rates prompted the question, plus lingoly_context as the
# control: same puzzles, same models, the only difference being whether the
# context needed to solve them is supplied. If declining is a response to
# genuine unanswerability rather than a quirk of phrasing, these two should
# differ sharply, and that difference is a finding rather than a defect.
BENCHMARKS = ("healthbench", "lingoly_nocontext", "lingoly_context",
              "judgebench", "hle")

# Benchmarks whose excerpts are never written. Humanity's Last Exam's terms
# forbid redistributing the dataset, and a response's surrounding text can
# quote the question, so HLE contributes counts (the histogram and the
# sensitivity grid) but no sampled context. Each benchmark's sample draws
# from its own seeded generator, so leaving one out changes no other's rows.
NO_EXCERPTS = ("hle",)

# Individually named so a hit can be attributed to the phrase that caused it.
# Same set, same spellings, same flags as scripts/census.py: this script has
# to measure exactly what the headline measured or it is answering a different
# question.
PHRASES = {
    "i don't know": r"i\s+don'?t\s+know",
    "i do not know": r"i\s+do\s+not\s+know",
    "idk": r"\bidk\b",
    "cannot determine": r"cannot\s+(be\s+)?determin",
    "unable to determine": r"unable\s+to\s+determine",
    "not enough information": r"not\s+enough\s+information",
    "insufficient information": r"insufficient\s+information",
    "cannot be answered": r"cannot\s+be\s+answered",
    "can't answer": r"can'?t\s+answer",
    "unanswerable": r"unanswerable",
    "i'm not sure": r"i'?m\s+not\s+sure",
    "i am not sure": r"i\s+am\s+not\s+sure",
    "no way to know": r"no\s+way\s+to\s+know",
    "impossible to know/determine": r"impossible\s+to\s+(know|determine)",
    "not possible to determine": r"not\s+possible\s+to\s+determine",
    "i cannot answer": r"i\s+cannot\s+answer",
    "unknown": r"unknown\b",
    "no comment": r"\bno\s+comment\b",
    "not attempted": r"not\s+attempted",
    "i lack the information": r"i\s+lack\s+(the\s+)?(information|knowledge)",
}
COMPILED = {name: re.compile(p, re.IGNORECASE) for name, p in PHRASES.items()}
ANY = re.compile("|".join(f"(?:{p})" for p in PHRASES.values()), re.IGNORECASE)

# The three lists the appendix's sensitivity table varies. The narrow and
# moderate sets were never written down in code anywhere, which is why the
# committed sensitivity table could not be regenerated; they are pinned here.
NARROW = ["i don't know", "i do not know", "idk"]
MODERATE = NARROW + ["cannot determine", "not enough information",
                     "insufficient information", "unanswerable"]
LISTS = {"narrow (3 phrases)": NARROW,
         "moderate (7 phrases)": MODERATE,
         "broad (~18 phrases, used)": list(PHRASES)}
SCOPES = {"whole generation": None, "final 300 characters": 300,
          "final 100 characters": 100}

SAMPLES_PER_BENCHMARK = 20
CONTEXT = 120


def text_of(r):
    """Everything the model emitted, both schema versions. From census.py."""
    parts = []
    o = r.get("output") or {}
    for c in (o.get("raw") or []):
        if isinstance(c, str):
            parts.append(c)
    for m in (r.get("messages") or []):
        if m.get("role") == "assistant" and isinstance(m.get("content"), str):
            parts.append(m["content"])
    return "\n".join(parts)


def scan(path):
    """Stream one published run; return (benchmark, counters, samples)."""
    bench = path.split("/")[1]
    phrase_counts = collections.Counter()
    grid = collections.Counter()
    n = 0
    samples = []
    seen_hits = 0
    rng = random.Random(path)          # deterministic per file, no global seed
    try:
        data = urllib.request.urlopen(
            RAW.format(rev=REVISION) + path, timeout=300).read()
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable: {path} ({exc})", file=sys.stderr)
        return bench, phrase_counts, grid, 0, []

    for line in data.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        text = text_of(r)
        if not text:
            continue

        # The 3x3 grid, counted the same way the headline counts.
        for scope_name, tail in SCOPES.items():
            window = text if tail is None else text[-tail:]
            for list_name, names in LISTS.items():
                if any(COMPILED[nm].search(window) for nm in names):
                    grid[(scope_name, list_name)] += 1

        hit = ANY.search(text)
        if not hit:
            continue
        for name, rx in COMPILED.items():
            if rx.search(text):
                phrase_counts[name] += 1

        # Reservoir sample so a long file cannot crowd out a short one.
        seen_hits += 1
        first = min((m for m in (rx.search(text) for rx in COMPILED.values())
                     if m), key=lambda m: m.start())
        row = {
            "benchmark": bench,
            "model": r.get("model_id") or "",
            "matched_phrase": next(nm for nm, rx in COMPILED.items()
                                   if rx.search(text)),
            "context": " ".join(
                text[max(0, first.start() - CONTEXT):
                     first.end() + CONTEXT].split()),
            "ends_with": " ".join(text[-200:].split()),
            "is_correct": (r.get("evaluation") or {}).get("is_correct"),
        }
        if len(samples) < SAMPLES_PER_BENCHMARK:
            samples.append(row)
        else:
            j = rng.randrange(seen_hits)
            if j < SAMPLES_PER_BENCHMARK:
                samples[j] = row
    return bench, phrase_counts, grid, n, samples


def main():
    files = [s["rfilename"]
             for s in json.load(urllib.request.urlopen(API, timeout=120))["siblings"]
             if s["rfilename"].endswith("_samples.jsonl")
             and s["rfilename"].split("/")[1] in BENCHMARKS]
    print(f"{len(files)} runs across {len(BENCHMARKS)} benchmarks",
          file=sys.stderr)

    phrases = collections.defaultdict(collections.Counter)
    grids = collections.defaultdict(collections.Counter)
    totals = collections.Counter()
    samples = collections.defaultdict(list)
    with ThreadPoolExecutor(8) as pool:
        for bench, pc, grid, n, samp in pool.map(scan, files):
            phrases[bench] += pc
            grids[bench] += grid
            totals[bench] += n
            samples[bench].extend(samp)

    os.makedirs(PROC, exist_ok=True)

    with open(os.path.join(PROC, "census_phrase_histogram.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["benchmark", "phrase", "responses_matching",
                    "share_of_matched_responses"])
        for bench in BENCHMARKS:
            counts = phrases[bench]
            total = sum(counts.values())
            for phrase, count in counts.most_common():
                w.writerow([bench, phrase, count,
                            f"{count / total:.4f}" if total else ""])

    with open(os.path.join(PROC, "census_decline_samples.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["benchmark", "model",
                                           "matched_phrase", "context",
                                           "ends_with", "is_correct"])
        w.writeheader()
        for bench in BENCHMARKS:
            if bench in NO_EXCERPTS:
                continue
            rng = random.Random(bench)
            pool_ = samples[bench]
            rng.shuffle(pool_)
            w.writerows(pool_[:SAMPLES_PER_BENCHMARK])

    with open(os.path.join(PROC, "census_sensitivity_by_benchmark.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["benchmark", "search_scope", "phrase_list", "n_responses",
                    "n_declines", "decline_rate"])
        for bench in BENCHMARKS:
            n = totals[bench]
            for scope in SCOPES:
                for lst in LISTS:
                    hits = grids[bench][(scope, lst)]
                    w.writerow([bench, scope, lst, n, hits,
                                f"{hits / n:.5f}" if n else ""])

    for bench in BENCHMARKS:
        counts = phrases[bench]
        total = sum(counts.values()) or 1
        top = counts.most_common(3)
        print(f"{bench:20s} n={totals[bench]:6,}  top phrases: "
              + ", ".join(f"{p} {c / total:.0%}" for p, c in top),
              file=sys.stderr)


if __name__ == "__main__":
    main()
