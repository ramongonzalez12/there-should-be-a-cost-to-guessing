"""Question banks.

Every loader normalises to the same item shape:

    {item_id, question, reference, aliases, choices, kind, stratum}

    kind = "freeform"  a short answer graded semantically (LM judge)
         = "mc"        multiple choice, graded deterministically
         = "behaviour" a constraint-temptation item with its own checker

Two properties matter more than coverage:

**Selection is stratified and frozen.** The design is paired — every scoring
contract must see exactly the same items, or item difficulty contaminates the
treatment effect. Slices are drawn deterministically (hash order within
stratum, round-robin across strata) and written to data/slices/, so re-running
a month later reproduces the same questions without an RNG seed to remember.

**Multiple choice gets an explicit abstention option.** Without one, a scoring
rule that prices error is a positive affine map of accuracy and cannot change
anything — verified numerically on 69 published GPQA runs, max deviation 1.2e-15.
The fifth option is what makes the question askable at all.
"""

from __future__ import annotations

import ast
import collections
import csv
import hashlib
import io
import json
import os
import random
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

from .http_retry import server_retry_delay

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_ROOT, "data")
CACHE = os.environ.get("BELOWZERO_CACHE", os.path.join(DATA_DIR, "cache"))
SLICES = os.path.join(DATA_DIR, "slices")

HF_ROWS = "https://datasets-server.huggingface.co/rows"
HF_REQUEST_INTERVAL_SECONDS = 0.25
HF_MAX_RETRY_SECONDS = 120.0


def _cache_path(name: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, name)


def _hf(dataset: str, config: str, split: str, cap: int = 20000):
    """Page the HuggingFace datasets-server. No auth: every dataset used here is
    open, which is deliberate — a gated dependency would make the experiment
    unreproducible for anyone who wanted to check it."""
    fname = _cache_path(f"hf_{dataset.replace('/', '__')}_{config}_{split}.json")
    if os.path.exists(fname):
        return json.load(open(fname, encoding="utf-8"))
    rows, off = [], 0
    while off < cap:
        u = (f"{HF_ROWS}?dataset={urllib.parse.quote(dataset, safe='')}"
             f"&config={config}&split={split}&offset={off}&length=100")
        # The datasets-server rate-limits anonymous callers hard. Back off and
        # keep going rather than losing a partial download.
        d = None
        for attempt in range(9):
            server_delay = 0.0
            try:
                d = json.load(urllib.request.urlopen(u, timeout=120))
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 502, 503, 504) or attempt == 8:
                    raise
                server_delay = server_retry_delay(e.headers)
            except Exception:
                if attempt == 8:
                    raise
            delay = max(min(60, 2**attempt), min(HF_MAX_RETRY_SECONDS, server_delay))
            time.sleep(delay + random.random())
        rows += [r["row"] for r in d["rows"]]
        total = d.get("num_rows_total", 0)
        off += 100
        if off >= total:
            break
        time.sleep(HF_REQUEST_INTERVAL_SECONDS)
    with open(fname, "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
    return rows


# ---------------------------------------------------------------------------
# Stratified freezing
# ---------------------------------------------------------------------------

def _freeze(items: list[dict], name: str, limit: int | None):
    """Round-robin across strata, deterministic hash order within each. Written
    to data/slices/ so the same questions come back next time."""
    if not limit or limit >= len(items):
        return items
    path = os.path.join(SLICES, f"{name}_{limit}.json")
    os.makedirs(SLICES, exist_ok=True)
    if os.path.exists(path):
        with open(path) as fh:
            keep = set(json.load(fh))
        return [i for i in items if i["item_id"] in keep]

    cells = collections.defaultdict(list)
    for it in items:
        cells[it.get("stratum") or "_"].append(it["item_id"])
    for c in cells.values():
        c.sort(key=lambda i: hashlib.sha1(i.encode()).hexdigest())
    order, keep, k = sorted(cells), [], 0
    while len(keep) < limit:
        moved = False
        for c in order:
            if k < len(cells[c]):
                keep.append(cells[c][k])
                moved = True
                if len(keep) == limit:
                    break
        if not moved:
            break
        k += 1
    with open(path, "w") as fh:
        json.dump(sorted(keep), fh)
    kept = set(keep)
    return [i for i in items if i["item_id"] in kept]


def _item(bench, idx, question, reference, *, aliases=None, choices=None,
          kind="freeform", stratum=None, extra=None):
    d = {"item_id": f"{bench}:{idx}", "question": question,
         "reference": reference, "aliases": aliases or [], "choices": choices,
         "kind": kind, "stratum": stratum}
    if extra:
        d.update(extra)
    return d


# ---------------------------------------------------------------------------
# Short-answer factual — the cleanest abstention testbed
# ---------------------------------------------------------------------------

def load_simpleqa(limit=None):
    """4,326 short factual questions with one reference answer. Free-form, so
    abstention is a natural move rather than a bolted-on fifth option."""
    p = _cache_path("simpleqa.csv")
    if not os.path.exists(p):
        urllib.request.urlretrieve(
            "https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv", p)
    out = []
    with open(p, encoding="utf-8") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            # literal_eval raises only these two on malformed input; a bare
            # `except Exception` here would also swallow bugs in this loop.
            try:
                meta = ast.literal_eval(r.get("metadata") or "{}")
            except (ValueError, SyntaxError):
                meta = {}
            out.append(_item("simpleqa", i, r["problem"], r["answer"],
                             stratum=f"{meta.get('topic','?')}|{meta.get('answer_type','?')}",
                             extra={"topic": meta.get("topic", "?"),
                                    "answer_type": meta.get("answer_type", "?")}))
    return _freeze(out, "simpleqa", limit)


def load_triviaqa(limit=None):
    """Trivia with alias sets, so deterministic grading is viable without a
    judge — a meaningful cost saving at scale and one less source of error in
    the primary outcome."""
    rows = _hf("mandarjoshi/trivia_qa", "rc.nocontext", "validation", cap=6000)
    out = []
    for i, r in enumerate(rows):
        a = r.get("answer") or {}
        val = a.get("value") or ""
        out.append(_item("triviaqa", i, r["question"], val,
                         aliases=list(a.get("normalized_aliases") or a.get("aliases") or []),
                         stratum=r.get("question_source", "?")))
    return _freeze(out, "triviaqa", limit)


def load_hotpotqa(limit=None):
    """Multi-hop questions asked WITHOUT the supporting context, so the model
    must answer from memory. Higher intrinsic uncertainty than SimpleQA, which
    is the regime where an abstention option should matter most."""
    rows = _hf("hotpotqa/hotpot_qa", "distractor", "validation", cap=4000)
    out = [_item("hotpotqa", i, r["question"], r["answer"],
                 stratum=f"{r.get('type','?')}|{r.get('level','?')}")
           for i, r in enumerate(rows)]
    return _freeze(out, "hotpotqa", limit)


def load_truthfulqa(limit=None):
    """Questions engineered so the plausible answer is a common misconception.
    The original paper scores 'No comment' as TRUE, which makes it the one
    mainstream benchmark that already treats abstention as success."""
    rows = _hf("truthfulqa/truthful_qa", "generation", "validation")
    out = [_item("truthfulqa", i, r["question"], r["best_answer"],
                 aliases=list(r.get("correct_answers") or []),
                 stratum=r.get("category", "?"))
           for i, r in enumerate(rows)]
    return _freeze(out, "truthfulqa", limit)


# ---------------------------------------------------------------------------
# Reasoning — verifiable answers, no judge needed
# ---------------------------------------------------------------------------

def load_gsm8k(limit=None):
    rows = _hf("openai/gsm8k", "main", "test")
    out = []
    for i, r in enumerate(rows):
        ref = (r["answer"].split("####")[-1]).strip().replace(",", "")
        out.append(_item("gsm8k", i, r["question"], ref, stratum="math"))
    return _freeze(out, "gsm8k", limit)


def load_math500(limit=None):
    rows = _hf("HuggingFaceH4/MATH-500", "default", "test")
    out = [_item("math500", i, r["problem"], str(r["answer"]),
                 stratum=f"{r.get('subject','?')}|L{r.get('level','?')}")
           for i, r in enumerate(rows)]
    return _freeze(out, "math500", limit)


# ---------------------------------------------------------------------------
# Multiple choice — every one gets an explicit abstention option
# ---------------------------------------------------------------------------

_LETTERS = "ABCDEFGHIJ"


def load_mmlu_pro(limit=None):
    """10-option multiple choice across 14 categories. The largest MC benchmark
    in the sweep and the one whose published decline rate is 0.02%."""
    rows = _hf("TIGER-Lab/MMLU-Pro", "default", "test", cap=12100)
    out = []
    for i, r in enumerate(rows):
        opts = list(r["options"])
        idx = r.get("answer_index")
        ref = _LETTERS[idx] if idx is not None else str(r.get("answer", ""))
        out.append(_item("mmlu_pro", i, r["question"], ref, choices=opts,
                         kind="mc", stratum=r.get("category", "?")))
    return _freeze(out, "mmlu_pro", limit)


def load_arc(limit=None):
    rows = _hf("allenai/ai2_arc", "ARC-Challenge", "test")
    out = []
    for i, r in enumerate(rows):
        ch = r["choices"]
        labels, texts = list(ch["label"]), list(ch["text"])
        key = r["answerKey"]
        if key not in labels:
            continue
        out.append(_item("arc", i, r["question"], _LETTERS[labels.index(key)],
                         choices=texts, kind="mc", stratum="science"))
    return _freeze(out, "arc", limit)


def load_medmcqa(limit=None):
    """Medical multiple choice. Included because it is the clearest case where
    the price of speaking should not be zero, which is the argument the
    assertion cost `c` exists to make concrete."""
    rows = _hf("openlifescienceai/medmcqa", "default", "validation", cap=4200)
    out = []
    for i, r in enumerate(rows):
        opts = [r.get("opa", ""), r.get("opb", ""), r.get("opc", ""), r.get("opd", "")]
        cop = r.get("cop")
        if cop is None or not all(opts):
            continue
        out.append(_item("medmcqa", i, r["question"], _LETTERS[int(cop)],
                         choices=opts, kind="mc", stratum="medicine"))
    return _freeze(out, "medmcqa", limit)


def load_boolq(limit=None):
    """Yes/no over a supplied passage. A two-option question is the hardest case
    for an abstention rule — guessing is worth 0.5 — so it bounds the effect."""
    rows = _hf("google/boolq", "default", "validation", cap=3300)
    out = []
    for i, r in enumerate(rows):
        q = f"Passage:\n{r['passage']}\n\nQuestion: {r['question']}?"
        out.append(_item("boolq", i, q, "A" if r["answer"] else "B",
                         choices=["Yes", "No"], kind="mc", stratum="reading"))
    return _freeze(out, "boolq", limit)


def load_gpqa(limit=None):
    """GPQA Diamond, reconstructed from the EvalEval per-sample dumps because
    the canonical dataset is gated. Same 198 questions, choices and reference
    letters, embedded in published runs."""
    p = _cache_path("gpqa_diamond.json")
    if not os.path.exists(p):
        src = ("https://huggingface.co/datasets/evaleval/EEE_datastore/resolve/main/"
               "data/gpqa-diamond/openai/gpt-5-5/"
               "0542bff5-1df3-4083-8bec-ee34d9854dcf_samples.jsonl")
        seen, rows = set(), []
        for line in urllib.request.urlopen(src, timeout=180).read().decode().splitlines():
            r = json.loads(line)
            q = r["input"]["raw"]
            if q in seen:
                continue
            seen.add(q)
            rows.append({"question": q, "reference": r["input"]["reference"][0],
                         "choices": r["input"]["choices"]})
        with open(p, "w") as fh:
            json.dump(rows, fh)
    with open(p) as fh:
        rows = json.load(fh)
    out = [_item("gpqa", i, r["question"], r["reference"], choices=r["choices"],
                 kind="mc", stratum="science") for i, r in enumerate(rows)]
    return _freeze(out, "gpqa", limit)


def load_gpqa_parity(limit=None):
    """Canonical GPQA Diamond rows with OpenAI simple-evals' seeded permutation.

    This is separate from ``gpqa`` because that frozen experimental slice came
    from an already-published run.  Replication needs a provenance-clean copy
    and must not mutate item identity underneath the earlier pilot.
    """
    p = _cache_path("gpqa_diamond_openai.csv")
    if not os.path.exists(p):
        urllib.request.urlretrieve(
            "https://openaipublic.blob.core.windows.net/simple-evals/gpqa_diamond.csv", p)
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rng = random.Random(0)
    out = []
    for row in rows:
        original = [row["Correct Answer"], row["Incorrect Answer 1"],
                    row["Incorrect Answer 2"], row["Incorrect Answer 3"]]
        choices = [original[i] for i in rng.sample(range(4), 4)]
        reference = _LETTERS[choices.index(row["Correct Answer"])]
        question_hash = hashlib.sha1(row["Question"].encode()).hexdigest()[:12]
        out.append(_item("gpqa_parity", question_hash, row["Question"], reference,
                         choices=choices, kind="mc", stratum="science"))
    return _freeze(out, "gpqa_parity", limit)


def load_truthfulqa_mc(limit=None):
    """Four-choice TruthfulQA, for deterministic truthfulness and calibration.

    The official dataset can contain many acceptable and unacceptable answers.
    This frozen MC1 construction keeps the best true answer and three false
    answers, then shuffles them with the seed used by the published EleutherAI
    adapter. Four choices are deliberate: the newer two-choice task is useful
    for truthfulness, but its 50% guessing floor is a weak abstention test.
    """
    p = _cache_path("truthfulqa_mc1.json")
    if not os.path.exists(p):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/sylinrl/TruthfulQA/"
            "013686a06be7a7bde5bf8223943e106c7250123c/data/mc_task.json",
            p,
        )
    with open(p, encoding="utf-8") as fh:
        rows = json.load(fh)
    rng = random.Random(42)
    out = []
    for i, row in enumerate(rows):
        targets = row.get("mc1_targets") or {}
        correct = [answer for answer, label in targets.items() if label == 1]
        incorrect = [answer for answer, label in targets.items() if label == 0]
        if len(correct) != 1 or len(incorrect) < 3:
            continue
        choices = [correct[0], *rng.sample(incorrect, 3)]
        rng.shuffle(choices)
        out.append(
            _item(
                "truthfulqa_mc",
                i,
                row["question"],
                _LETTERS[choices.index(correct[0])],
                choices=choices,
                kind="mc",
                stratum=row.get("category", "?"),
            )
        )
    return _freeze(out, "truthfulqa_mc", limit)


_BBQ_CATEGORIES = (
    "Age",
    "Disability_status",
    "Gender_identity",
    "Nationality",
    "Physical_appearance",
    "Race_ethnicity",
    "Race_x_SES",
    "Race_x_gender",
    "Religion",
    "SES",
    "Sexual_orientation",
)
_BBQ_COMMIT = "bea11bd97d79217245b5871acd247b9d6eb24598"


def load_bbq(limit=None):
    """BBQ's paired ambiguous/disambiguated social-bias questions.

    The official scoring script excludes 16 rows whose target metadata is
    absent. We do the same and retain ``target_loc`` so the evaluator can report
    BBQ's bias endpoint as well as answer accuracy and confidence calibration.
    """
    metadata_path = _cache_path("bbq_additional_metadata.csv")
    if not os.path.exists(metadata_path):
        urllib.request.urlretrieve(
            f"https://raw.githubusercontent.com/nyu-mll/BBQ/{_BBQ_COMMIT}/"
            "analysis_scripts/additional_metadata.csv",
            metadata_path,
        )
    with open(metadata_path, encoding="utf-8") as fh:
        metadata = {
            (row["category"], row["question_index"], int(row["example_id"])): row
            for row in csv.DictReader(fh)
            if row.get("target_loc") not in {None, "", "NA"}
        }

    out = []
    for category in _BBQ_CATEGORIES:
        cache_path = _cache_path(f"bbq_{category}.jsonl")
        if not os.path.exists(cache_path):
            urllib.request.urlretrieve(
                f"https://raw.githubusercontent.com/nyu-mll/BBQ/{_BBQ_COMMIT}/"
                f"data/{category}.jsonl",
                cache_path,
            )
        with open(cache_path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        for row in rows:
            key = (category, str(row["question_index"]), int(row["example_id"]))
            meta = metadata.get(key)
            if meta is None:
                continue
            choices = [row["ans0"], row["ans1"], row["ans2"]]
            question = f"Context:\n{row['context']}\n\nQuestion: {row['question']}"
            out.append(
                _item(
                    "bbq",
                    f"{category}:{row['example_id']}",
                    question,
                    _LETTERS[int(row["label"])],
                    choices=choices,
                    kind="mc",
                    stratum=f"{category}|{row['context_condition']}",
                    extra={
                        "bbq_category": category,
                        "context_condition": row["context_condition"],
                        "question_polarity": row["question_polarity"],
                        "target_loc": int(float(meta["target_loc"])),
                        "unknown_loc": next(
                            index
                            for index, answer in enumerate(row["answer_info"].values())
                            if answer[1] == "unknown"
                        ),
                    },
                )
            )
    return _freeze(out, "bbq", limit)


def load_ethics_hard(limit=None):
    """All five ETHICS hard-test tasks, normalized to deterministic MC.

    These adversarial splits were constructed to remove easy lexical cues. The
    task remains a measure of agreement with the dataset's widespread human
    judgments, not a claim that a binary label settles a moral question.
    """
    out = []
    task_rows = _ethics_hard_rows()
    for i, row in enumerate(task_rows["commonsense"]):
        out.append(
            _item(
                "ethics_hard",
                f"commonsense:{i}",
                f"Is the following action morally wrong?\n\n{row['input']}",
                "B" if int(row["label"]) else "A",
                choices=["No", "Yes"],
                kind="mc",
                stratum="commonsense",
                extra={"ethics_task": "commonsense"},
            )
        )
    for task in ("deontology", "justice", "virtue"):
        for i, row in enumerate(task_rows[task]):
            if task == "deontology":
                question = (
                    "Does the response give a reasonable justification for not "
                    f"fulfilling the stated duty?\n\nDuty: {row['scenario']}\n"
                    f"Response: {row['excuse']}"
                )
            elif task == "justice":
                question = f"Is this statement reasonable and just?\n\n{row['scenario']}"
            else:
                scenario, trait = row["scenario"].rsplit("[SEP]", 1)
                question = (
                    f"Does the behavior display the character trait '{trait.strip()}'?"
                    f"\n\n{scenario.strip()}"
                )
            out.append(
                _item(
                    "ethics_hard",
                    f"{task}:{i}",
                    question,
                    "A" if int(row["label"]) else "B",
                    choices=["Yes", "No"],
                    kind="mc",
                    stratum=task,
                    extra={"ethics_task": task},
                )
            )
    for i, row in enumerate(task_rows["utilitarianism"]):
        out.append(
            _item(
                "ethics_hard",
                f"utilitarianism:{i}",
                "Which scenario would usually produce greater overall well-being?",
                "A",
                choices=[row["baseline"], row["less_pleasant"]],
                kind="mc",
                stratum="utilitarianism",
                extra={"ethics_task": "utilitarianism"},
            )
        )
    return _freeze(out, "ethics_hard", limit)


_ETHICS_ARCHIVE_SHA256 = (
    "40acbf1ac0da79a2aabef394d58889136b8d38b05be09482006de2453fb06333"
)
_ETHICS_HARD_MEMBERS = {
    "commonsense": "ethics/commonsense/cm_test_hard.csv",
    "deontology": "ethics/deontology/deontology_test_hard.csv",
    "justice": "ethics/justice/justice_test_hard.csv",
    "virtue": "ethics/virtue/virtue_test_hard.csv",
    "utilitarianism": "ethics/utilitarianism/util_test_hard.csv",
}


def _ethics_hard_rows() -> dict[str, list[dict[str, object]]]:
    """Read the checksum-pinned official ETHICS archive without extracting it."""
    archive_path = _cache_path("ethics_40acbf1a.tar")
    if not os.path.exists(archive_path):
        urllib.request.urlretrieve(
            "https://people.eecs.berkeley.edu/~hendrycks/ethics.tar",
            archive_path,
        )
    digest = hashlib.sha256()
    with open(archive_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != _ETHICS_ARCHIVE_SHA256:
        raise ValueError("the ETHICS archive does not match its frozen checksum")

    result: dict[str, list[dict[str, object]]] = {}
    with tarfile.open(archive_path) as archive:
        for task, member_name in _ETHICS_HARD_MEMBERS.items():
            member = archive.extractfile(member_name)
            if member is None:
                raise ValueError(f"the ETHICS archive is missing {member_name}")
            with io.TextIOWrapper(member, encoding="utf-8", newline="") as handle:
                if task == "utilitarianism":
                    result[task] = [
                        {"baseline": row[0], "less_pleasant": row[1]}
                        for row in csv.reader(handle)
                        if len(row) == 2
                    ]
                else:
                    result[task] = list(csv.DictReader(handle))
    return result


# ---------------------------------------------------------------------------
# Behaviour track
# ---------------------------------------------------------------------------

def load_behaviour(limit=None):
    """Constraint-temptation items: a task, an explicit prohibition, an easy way
    to violate it, and a deterministic checker. Not agentic on purpose — one API
    call each, and it still isolates whether an announced consequence changes
    whether a model breaks a stated rule."""
    with open(os.path.join(DATA_DIR, "behaviour_items.json"), encoding="utf-8") as fh:
        rows = json.load(fh)
    out = [{"item_id": f"behaviour:{r['id']}", "question": r["prompt"],
            "reference": r.get("reference", ""), "aliases": [], "choices": None,
            "kind": "behaviour", "stratum": r.get("cat", "?"), "check": r["check"]}
           for r in rows]
    return out[:limit] if limit else out


BENCHMARKS = {
    # short-answer factual
    "simpleqa": load_simpleqa,
    "triviaqa": load_triviaqa,
    "hotpotqa": load_hotpotqa,
    "truthfulqa": load_truthfulqa,
    # reasoning, verifiable
    "gsm8k": load_gsm8k,
    "math500": load_math500,
    # multiple choice
    "mmlu_pro": load_mmlu_pro,
    "gpqa": load_gpqa,
    "gpqa_parity": load_gpqa_parity,
    "arc": load_arc,
    "medmcqa": load_medmcqa,
    "boolq": load_boolq,
    "truthfulqa_mc": load_truthfulqa_mc,
    "bbq": load_bbq,
    "ethics_hard": load_ethics_hard,
    # constraints
    "behaviour": load_behaviour,
}

# Which benchmarks can be graded without an LM judge. Deterministic grading is
# cheaper and, more importantly, removes a source of error from the primary
# outcome — the judge is the one link in the chain that cannot be unit-tested.
DETERMINISTIC = {"gsm8k", "math500", "mmlu_pro", "gpqa", "gpqa_parity",
                 "arc", "medmcqa",
                 "boolq", "triviaqa", "truthfulqa_mc", "bbq", "ethics_hard"}
