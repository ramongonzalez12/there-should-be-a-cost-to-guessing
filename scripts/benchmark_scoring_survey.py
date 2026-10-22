"""How is (nearly) every benchmark actually scored? Our own survey.

The page has leaned on a published survey of ten headline benchmarks. Ramon
asked the stronger question: review up to ~50 ourselves. This builds that
survey from two sources and writes it as one dataset the site renders.

    python scripts/benchmark_scoring_survey.py
        -> data/processed/benchmark_scoring_survey.csv

Source one: the 36 benchmarks in the census. For these the classification is
read off the datastore itself rather than asserted: a benchmark whose
published runs carry binary correctness labels grades right-or-wrong, and in
every one of them an abstention simply fails to be correct, which is the
definition of silence scoring like a wrong answer. Whether it asks for a
confidence is likewise measured (share of responses stating one). Benchmarks
whose runs carry no correctness label at all (rubric-graded conversation,
format compliance) are classified as not right/wrong-graded, which is its own
answer to the survey question.

Source two: sixteen prominent benchmarks outside the datastore, hand-entered
with the basis recorded per row. Every classification here traces to the
benchmark's paper or scoring code; two that were checked against current
descriptions during compilation (LiveBench, tau-bench) note it. Preference
arenas and judge-scored suites are included and classified as not
right/wrong-graded rather than being quietly dropped, because "how do
benchmarks score" has to include the ones that do not grade answers at all.

Three questions per row, the same three the page's landscape table asks:
does a wrong answer cost more than silence? does silence earn anything a
wrong answer does not? is the model asked how sure it is?
"""
import csv
import os

PROC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "processed")
SRC = os.path.join(PROC, "census_by_benchmark.csv")
OUT = os.path.join(PROC, "benchmark_scoring_survey.csv")

# Benchmarks in the census whose rows carry no binary correctness label, with
# what they grade instead. Everything else with labels grades right-or-wrong.
NOT_BINARY = {
    "healthbench": "free-form clinical advice against a physician rubric",
    "IFEval": "compliance with format instructions",
    "lingoly_context": "puzzle answers, exact match",
    "lingoly_nocontext": "puzzle answers, exact match",
}

# The external sixteen. Columns: name, how it is scored, prices wrong answers
# beyond silence, silence earns something a wrong answer does not, asks the
# model how sure it is, basis.
EXTERNAL = [
    ("MMLU", "accuracy over multiple choice", "no", "no", "no",
     "Hendrycks et al. 2021"),
    ("MATH", "accuracy, exact answer match", "no", "no", "no",
     "Hendrycks et al. 2021"),
    ("AIME (as used in evals)", "accuracy, exact answer match", "no", "no",
     "no", "standard eval usage"),
    ("HumanEval", "pass@1: code passes tests or not", "no", "no", "no",
     "Chen et al. 2021"),
    ("SWE-bench Verified", "share of issues resolved", "no", "no", "no",
     "OpenAI/Princeton scoring"),
    ("FrontierMath", "accuracy, verified answers", "no", "no", "no",
     "Epoch AI"),
    ("DROP", "F1 with partial credit", "no", "no", "no",
     "Dua et al. 2019"),
    ("TruthfulQA (MC)", "accuracy over multiple choice", "no", "no", "no",
     "Lin et al. 2022"),
    ("BIG-bench (typical tasks)", "accuracy / exact match", "no", "no", "no",
     "Srivastava et al. 2022"),
    ("LiveBench", "accuracy against objective ground truth", "no", "no", "no",
     "LiveBench paper; checked Aug 2026"),
    ("tau-bench", "pass^k: task success from final database state", "no",
     "no", "no", "Sierra tau-bench paper; checked Aug 2026"),
    ("SimpleQA", "correct / incorrect / not-attempted; headline is correct",
     "no", "tracked, but earns nothing", "no", "OpenAI 2024"),
    ("LMArena (Chatbot Arena)", "human preference Elo, no right answers",
     "&mdash;", "&mdash;", "no", "LMSYS"),
    ("MT-Bench", "LM judge quality score 1&ndash;10", "&mdash;", "&mdash;",
     "no", "Zheng et al. 2023"),
    ("AlpacaEval 2", "length-controlled win rate vs reference", "&mdash;",
     "&mdash;", "no", "Dubois et al. 2024"),
    ("AA-Omniscience", "+1 right, &minus;1 wrong, 0 declined", "yes",
     "yes, silence is free", "no", "Artificial Analysis 2025"),
]

FIELDS = ["benchmark", "source", "how_scored", "prices_wrong_answers",
          "silence_earns_more_than_wrong", "asks_confidence", "basis"]


def census_rows():
    out = []
    with open(SRC, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name = r["benchmark"]
            stated = float(r["stated_confidence_rate"])
            asks = ("asks, but never scores it" if stated > 0.05 else "no")
            if name in NOT_BINARY:
                out.append([name, "census", NOT_BINARY[name],
                            "&mdash;", "&mdash;", asks,
                            "EEE datastore: no correctness labels"])
            else:
                out.append([name, "census",
                            "right or wrong, from correctness labels",
                            "no", "no", asks,
                            ("EEE datastore correctness labels; abstention "
                            "graded not-correct")])
    return out


def main():
    rows_ = census_rows() + [[n, "external", h, p, s, a, b]
                             for n, h, p, s, a, b in EXTERNAL]
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        w.writerows(rows_)

    total = len(rows_)
    graded = [r for r in rows_ if r[3] != "&mdash;"]
    prices = [r for r in rows_ if r[3] == "yes"]
    silence = [r for r in rows_ if r[4].startswith("yes")]
    asks = [r for r in rows_ if r[5] != "no"]
    print(f"wrote {OUT}: {total} benchmarks")
    print(f"  grade answers right-or-wrong: {len(graded)}")
    print(f"  price a wrong answer beyond silence: {len(prices)}")
    print(f"  give silence anything a wrong answer gets not: {len(silence)}")
    print(f"  ask the model how sure it is: {len(asks)}")


if __name__ == "__main__":
    main()
