"""Rescore every published HLE run whose model states usable confidences.

data/processed/hle_quadratic.csv covers four models. Ramon asked the obvious
question: are those the only ones? This sweeps all published HLE runs and
rescoring every model with enough stated confidences to mean anything, so the
table's membership is a threshold, not a curation.

    python scripts/hle_rescore.py -> data/processed/hle_rescored_all.csv

Per model, over the responses that carry BOTH a parseable stated confidence
and a correctness label: accuracy, mean stated confidence, the
confidence-calibrated (quadratic) score, and the same with the fixed cost at
c = 0.09 and c = 0.25. Every response in that subset answered, so the cost
applies to all of them.

The n_total and n_scored columns are the disclosure that matters: most models
CANNOT be rescored, because their published runs almost never state a number.
That is not missing data; it is the census finding showing up again, and the
table's caption should say so rather than hiding the models that don't
qualify.

Streams and discards, no key, about a minute. Same regex and text handling as
scripts/census.py so this measures what the census measured.
"""
import collections
import csv
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://huggingface.co/api/datasets/evaleval/EEE_datastore"
RAW = "https://huggingface.co/datasets/evaleval/EEE_datastore/resolve/main/"
CONF = re.compile(r"confidence\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%", re.IGNORECASE)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "processed", "hle_rescored_all.csv")

MIN_SCORED = 50   # below this the estimates are noise; rows are still written
                  # with a below_threshold flag so nothing is silently dropped


def text_of(r):
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
    try:
        data = urllib.request.urlopen(RAW + path, timeout=300).read()
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable: {path} ({exc})", file=sys.stderr)
        return {}
    stats = collections.defaultdict(
        lambda: {"n": 0, "scored": 0, "correct": 0, "conf": 0.0,
                 "quad": 0.0})
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        model = r.get("model_id") or ""
        s = stats[model]
        s["n"] += 1
        is_correct = (r.get("evaluation") or {}).get("is_correct")
        matches = CONF.findall(text_of(r))
        if is_correct is None or not matches:
            continue
        p = float(matches[-1]) / 100.0
        if p > 1:
            continue
        s["scored"] += 1
        s["correct"] += bool(is_correct)
        s["conf"] += p
        s["quad"] += (2 * p - p * p) if is_correct else (-p * p)
    return stats


def main():
    files = [s["rfilename"]
             for s in json.load(urllib.request.urlopen(API, timeout=120))["siblings"]
             if s["rfilename"].endswith("_samples.jsonl")
             and s["rfilename"].split("/")[1] == "hle"]
    print(f"{len(files)} published hle runs", file=sys.stderr)

    totals = collections.defaultdict(
        lambda: {"n": 0, "scored": 0, "correct": 0, "conf": 0.0, "quad": 0.0})
    with ThreadPoolExecutor(8) as pool:
        for stats in pool.map(scan, files):
            for model, s in stats.items():
                t = totals[model]
                for k in s:
                    t[k] += s[k]

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "n_responses", "n_scored", "accuracy",
                    "mean_confidence", "quad", "quad_c09", "quad_c25",
                    "below_threshold"])
        for model in sorted(totals, key=lambda m: -totals[m]["scored"]):
            t = totals[model]
            if not t["scored"]:
                continue
            n = t["scored"]
            quad = t["quad"] / n
            w.writerow([model, t["n"], n,
                        f'{t["correct"] / n:.4f}',
                        f'{t["conf"] / n:.4f}',
                        f'{quad:.4f}',
                        f'{quad - 0.09:.4f}',
                        f'{quad - 0.25:.4f}',
                        int(n < MIN_SCORED)])
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
