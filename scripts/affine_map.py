"""Why a penalty for wrong answers changes nothing unless abstention is possible.

This reproduces the claim that the historical protocol rests on, and that the site states
as the reason every multiple-choice item must get an appended "I DON'T KNOW"
option. Until now the number lived only in prose.

The argument. Take a published benchmark run: every item was answered, because
there was nothing else the model could do. Score it under a rule that penalises a
wrong answer p points and pays 1 for a right one. With N items and n_c correct:

    mean score = [n_c - p(N - n_c)] / N
               = acc - p(1 - acc)
               = (1 + p) * acc - p

which is a positive affine function of accuracy alone. The penalty p appears, but
only as a scale and an offset applied identically to every run, so it cannot move
any run past any other. Rescoring an archive of forced-answer runs under ANY
penalty produces the same leaderboard, in the same order, every time.

That is why the experiment cannot be run on archived data, and why removing the
abstention option would make it structurally incapable of detecting its own effect.

What this script does. It does not trust the algebra. For each of the 69 published
GPQA Diamond runs it accumulates the score one item at a time in floating point,
then compares that sum against the closed form above. If the two agree to machine
precision, the identity holds on real data and not merely on paper. Any deviation
materially above ~1e-15 would mean the identity is wrong, and the site's central
methodological rule with it.

Reads nothing local: the per-sample files are streamed from the EvalEval datastore
and discarded, exactly as scripts/census.py does. No API key, no cost, ~1 minute.

    python scripts/affine_map.py    ->  data/processed/affine_map.csv
"""
import csv
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://huggingface.co/api/datasets/evaleval/EEE_datastore"
RAW = "https://huggingface.co/datasets/evaleval/EEE_datastore/resolve/main/"

# The benchmark whose published runs the site quotes. 69 files, one per model run.
# `gpqa_diamond` (underscore) is a separate, smaller collection in the same
# datastore and is deliberately not mixed in.
BENCH = "gpqa-diamond"

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "processed",
                   "affine_map.csv")

# The three break-even confidences the site discusses. A rule that says "answer
# only if more than t confident" has to charge t/(1-t) for a wrong answer to make
# t the indifference point, so these are the penalties a maintainer would actually
# pick, not arbitrary numbers.
THRESHOLDS = (0.50, 0.75, 0.90)


def penalty_for(t):
    """Cost of a wrong answer that puts the break-even confidence at t.

    Same function as belowzero.contracts.penalty_for, restated here so this
    script stays runnable from a bare clone without the package installed.
    """
    return t / (1.0 - t)


def tally(path):
    """Stream one published run and count graded items and correct answers.

    Returns (model_id, n, n_correct) or None if the file could not be read.
    One unreachable file out of 69 should not abort the sweep, but it MUST
    reduce the run count rather than pass silently -- the whole point of the
    output is "this held across all 69".
    """
    try:
        data = urllib.request.urlopen(RAW + path, timeout=300).read()
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable: {path} ({exc})", file=sys.stderr)
        return None

    model, n, n_correct = None, 0, 0
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        model = model or r.get("model_id")
        # Ungraded rows carry no correctness label, so they are not part of any
        # score under any rule. Excluded from the denominator, matching census.py.
        is_correct = (r.get("evaluation") or {}).get("is_correct")
        if is_correct is None:
            continue
        n += 1
        n_correct += bool(is_correct)
    return (model, n, n_correct) if n else None


def main():
    files = [s["rfilename"]
             for s in json.load(urllib.request.urlopen(API, timeout=120))["siblings"]
             if s["rfilename"].endswith("_samples.jsonl")
             and s["rfilename"].split("/")[1] == BENCH]
    print(f"{len(files)} published {BENCH} runs", file=sys.stderr)

    with ThreadPoolExecutor(16) as pool:
        runs = [(path, res) for path, res in zip(files, pool.map(tally, files)) if res]
    print(f"{len(runs)} runs readable and graded", file=sys.stderr)

    out_rows, worst = [], 0.0
    for path, (model, n, n_correct) in sorted(runs, key=lambda r: (r[1][0] or "", r[0])):
        accuracy = n_correct / n
        for t in THRESHOLDS:
            p = penalty_for(t)

            # The honest way: walk the items and accumulate, so the result carries
            # whatever rounding error real summation introduces. Doing this as
            # n_correct - p * (n - n_correct) would be testing the algebra against
            # itself and would agree to the bit every time.
            total = 0.0
            for _ in range(n_correct):
                total += 1.0
            for _ in range(n - n_correct):
                total -= p
            summed = total / n

            affine = (1.0 + p) * accuracy - p
            deviation = abs(summed - affine)
            worst = max(worst, deviation)

            out_rows.append({
                # Vendor, model, AND the run's own identifier. Three of the 69
                # files are repeat runs of a model that already appears, so
                # keying on vendor/model alone silently merges them and makes
                # any count of distinct runs read 66.
                "run": path.rsplit("/", 1)[-1].split("_samples")[0],
                "model_path": path.split("/", 2)[2].rsplit("/", 1)[0],
                "model": model or "",
                "threshold": f"{t:.2f}",
                "penalty": f"{p:.6f}",
                "n": n,
                "n_correct": n_correct,
                "accuracy": f"{accuracy:.6f}",
                "score_summed": repr(summed),
                "score_affine": repr(affine),
                "deviation": f"{deviation:.3e}",
            })

    # The consequence that actually matters. The identity is only interesting
    # because it means the ORDER is fixed, so check the order directly rather
    # than inviting the reader to take the algebra on trust.
    #
    # Checked pairwise rather than by comparing two sorted lists. 15 of the 69
    # runs share an accuracy with another run, and accumulating their scores over
    # different item counts separates those ties by ~1e-16. Sorting turns that
    # noise into an apparent reordering, which is an artefact of the comparison,
    # not of the rule: runs that are tied on accuracy are tied under the penalty
    # too, to within the precision of the sum. So only pairs whose accuracies
    # genuinely differ can testify about order.
    inversions, tied_pairs = 0, 0
    for t in THRESHOLDS:
        at_t = [r for r in out_rows if r["threshold"] == f"{t:.2f}"]
        for i in range(len(at_t)):
            for j in range(i + 1, len(at_t)):
                a_i, a_j = float(at_t[i]["accuracy"]), float(at_t[j]["accuracy"])
                s_i, s_j = float(at_t[i]["score_summed"]), float(at_t[j]["score_summed"])
                if a_i == a_j:
                    tied_pairs += 1
                    if abs(s_i - s_j) > 1e-12:
                        inversions += 1  # a real separation of a genuine tie
                elif (a_i < a_j) != (s_i < s_j):
                    inversions += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    print(f"wrote {os.path.normpath(OUT)}: {len(out_rows)} rows "
          f"({len(runs)} runs x {len(THRESHOLDS)} thresholds)", file=sys.stderr)
    print(f"max deviation from (1+p)*acc - p: {worst:.3e}", file=sys.stderr)
    if inversions:
        print(f"RANK ORDER CHANGED: {inversions} inverted pairs -- the identity "
              f"does NOT hold and the appended-option rule needs revisiting", file=sys.stderr)
        return 1
    print(f"rank order identical to accuracy at every threshold "
          f"({tied_pairs} tied pairs stayed tied)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
