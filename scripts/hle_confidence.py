"""What confidence do models CLAIM on Humanity's Last Exam, on average?

data/processed/hle_quadratic.csv rescores the published HLE runs with the
models' own stated confidences, but carries only the squared-error
decomposition of those numbers. The first moment, the average confidence a
model states for itself, was never written down, and it cannot be recovered
from Brier components. The brief's rescoring table wants to print it next to
the accuracy so a reader can see the gap by eye, so this script recovers it
from the source.

Reads nothing local: the per-sample HLE files are streamed from the EvalEval
datastore and discarded, exactly as scripts/census.py and scripts/affine_map.py
do. No API key, no cost, well under a minute — HLE is 6,306 responses of the
datastore's million.

    python scripts/hle_confidence.py  ->  data/processed/hle_stated_confidence.csv

A response's stated confidence is the LAST match of the same pattern
scripts/census.py counts, because HLE's prompt asks for the confidence at the
end of the answer and earlier matches are usually the model quoting the
instruction back. Means here are over responses that state a number at all,
which is the same population hle_quadratic.csv scores.
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

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "processed",
                   "hle_stated_confidence.csv")


def text_of(r):
    """Concatenate everything the model actually emitted, both schema versions."""
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
    """Stream one published HLE run; return per-model confidence tallies."""
    try:
        data = urllib.request.urlopen(RAW + path, timeout=300).read()
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable: {path} ({exc})", file=sys.stderr)
        return None
    stats = collections.defaultdict(lambda: [0, 0, 0.0])  # n, n_stated, sum
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        model = r.get("model_id") or ""
        row = stats[model]
        row[0] += 1
        matches = CONF.findall(text_of(r))
        if not matches:
            continue
        value = float(matches[-1])
        if value > 100:
            continue
        row[1] += 1
        row[2] += value / 100.0
    return stats


def main():
    files = [s["rfilename"]
             for s in json.load(urllib.request.urlopen(API, timeout=120))["siblings"]
             if s["rfilename"].endswith("_samples.jsonl")
             and s["rfilename"].split("/")[1] == "hle"]
    print(f"{len(files)} published hle runs", file=sys.stderr)

    totals = collections.defaultdict(lambda: [0, 0, 0.0])
    with ThreadPoolExecutor(8) as pool:
        for stats in pool.map(scan, files):
            if not stats:
                continue
            for model, (n, n_stated, total) in stats.items():
                agg = totals[model]
                agg[0] += n
                agg[1] += n_stated
                agg[2] += total

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "n_responses", "n_stated",
                    "mean_stated_confidence"])
        for model in sorted(totals):
            n, n_stated, total = totals[model]
            mean = f"{total / n_stated:.4f}" if n_stated else ""
            w.writerow([model, n, n_stated, mean])
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
