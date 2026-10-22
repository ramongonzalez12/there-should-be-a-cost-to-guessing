"""Stream every per-sample file in the EEE datastore and ask one question:
does ANY model, on ANY benchmark, ever decline to answer?
Files are downloaded, scanned, and discarded — nothing is kept on disk."""
import collections
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API="https://huggingface.co/api/datasets/evaleval/EEE_datastore"
RAW="https://huggingface.co/datasets/evaleval/EEE_datastore/resolve/main/"

# Phrases that constitute a decline. Deliberately broad — we are trying hard to
# FIND abstention, so false positives are acceptable and false negatives are not.
DECLINE = re.compile(r"""(
 i\s+don'?t\s+know | i\s+do\s+not\s+know | \bidk\b | cannot\s+(be\s+)?determin
 | unable\s+to\s+determine | not\s+enough\s+information | insufficient\s+information
 | cannot\s+be\s+answered | can'?t\s+answer | unanswerable | i'?m\s+not\s+sure
 | i\s+am\s+not\s+sure | no\s+way\s+to\s+know | impossible\s+to\s+(know|determine)
 | not\s+possible\s+to\s+determine | i\s+cannot\s+answer | unknown\b
 | \bno\s+comment\b | not\s+attempted | i\s+lack\s+(the\s+)?(information|knowledge)
)""", re.IGNORECASE | re.VERBOSE)
CONF = re.compile(r"confidence\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%", re.IGNORECASE)

FAILED_FILES: list = []


def text_of(r):
    """Concatenate everything the model actually emitted, both schema versions."""
    parts=[]
    o=r.get("output") or {}
    for c in (o.get("raw") or []):
        if isinstance(c,str): parts.append(c)
    for m in (r.get("messages") or []):
        if m.get("role")=="assistant" and isinstance(m.get("content"),str):
            parts.append(m["content"])
    return "\n".join(parts)

def scan(path):
    bench = path.split("/")[1]
    stats = collections.Counter()
    data = None
    # Retry each file a few times with a pause: the Aug-28 re-stream lost 258
    # of 1,319 files to transient HTTP errors and reported only a bare
    # file_error count, so nobody could tell which files were missing or
    # that 14% of the datastore had silently dropped out of the headline.
    # Every failure is now named in sweep.json and summarised at the end.
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(RAW+path, timeout=300).read().decode("utf-8","replace")
            break
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
            time.sleep(3 * (attempt + 1))
    if data is None:
        FAILED_FILES.append({"file": path, "error": last_error})
        return bench, collections.Counter({"file_error":1}), None
    model=None
    for line in data.splitlines():
        try: r=json.loads(line)
        except json.JSONDecodeError:
            stats["bad_line"]+=1; continue
        model = model or r.get("model_id")
        ev=r.get("evaluation") or {}
        if ev.get("is_correct") is None: 
            stats["ungraded"]+=1; continue
        t=text_of(r)
        stats["n"]+=1
        stats["correct"]+= bool(ev["is_correct"])
        if not t.strip(): stats["empty"]+=1
        if DECLINE.search(t or ""): stats["decline_phrase"]+=1
        if CONF.search(t or ""):    stats["stated_conf"]+=1
        aa=(r.get("answer_attribution") or [{}])
        ex=(aa[0].get("extracted_value") if aa else None)
        if ex in (None,"","None"): stats["unextracted"]+=1
    return bench, stats, model

files=[s["rfilename"] for s in json.load(urllib.request.urlopen(API,timeout=120))["siblings"]
       if s["rfilename"].endswith("_samples.jsonl")]
# Skip the game-playing arenas: no notion of a correct answer to decline on.
files=[f for f in files if not re.search(r"/(objects|wordle_arena|fibble\d*_arena)/", f)]
print(f"{len(files)} files to scan", file=sys.stderr)

by_bench=collections.defaultdict(collections.Counter)
by_model=collections.defaultdict(collections.Counter)
# One datastore file IS one (model, benchmark) cell, so the matrix is the
# natural unit of this sweep. The marginals above aggregate it away, which is
# how a model scanned on 2 unusual benchmarks ended up ranked against models
# scanned on 30 (the claude-3-5-sonnet mix-shift problem): decline rates are
# only comparable across models when computed on the same benchmark set, and
# that restriction needs the pair-level counts.
by_pair=collections.defaultdict(collections.Counter)
with ThreadPoolExecutor(16) as ex:
    for i,(bench,st,model) in enumerate(ex.map(scan, files),1):
        by_bench[bench].update(st)
        if model:
            by_model[model].update(st)
            by_pair[f"{model}||{bench}"].update(st)
        if i%100==0: print(f"  {i}/{len(files)}", file=sys.stderr)

# Written under data/processed/ (not CWD) so the sweep output is kept beside
# the CSVs derived from it; the previous run's sweep.json was lost to CWD.
import datetime as _dt
import pathlib

_out = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed" / "sweep.json"
with open(_out,"w") as _fh:
    json.dump({"pulled": _dt.datetime.now(_dt.timezone.utc).date().isoformat(),
               "files_listed": len(files),
               "files_failed": len(FAILED_FILES),
               "failed_files": FAILED_FILES,
               "by_bench":{k:dict(v) for k,v in by_bench.items()},
               "by_model":{k:dict(v) for k,v in by_model.items()},
               "by_pair":{k:dict(v) for k,v in by_pair.items()}},
              _fh, indent=1)
print(f"wrote {_out}", file=sys.stderr)
if FAILED_FILES:
    # Loud, not fatal: the partial sweep is still useful for the matrix, but
    # a headline must not be promoted from it without reading this line.
    print(f"WARNING: {len(FAILED_FILES)} of {len(files)} files failed after 4 attempts; "
          "see failed_files in sweep.json before promoting any headline", file=sys.stderr)
    sys.exit(2)
