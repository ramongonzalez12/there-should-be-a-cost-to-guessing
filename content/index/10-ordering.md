## ordering | What moves calibration, and by how much

Three interventions were compared on the same three outcomes: the overconfidence
gap (mean stated confidence minus accuracy), a proper score (accuracy minus
Brier loss, on a 0-to-100 scale), and the share of questions answered wrongly
at 90%+ confidence. The ordering is the finding.

- key: **Explaining the scoring rule: nothing.** Randomized against a plain
baseline on ten frontier models and eight benchmarks, every outcome moved by
less than a point, inside its interval.
- key: **Telling the model to hedge: the number, not the knowledge.** A
one-sentence warning about overconfidence cut the gap by 17 points and
near-certain errors by 10 per 100, but the proper score stayed flat, because a
blunt confidence cut pays back on hard questions exactly what it costs on easy
ones.
- key: **Training on the score: the knowledge.** Across ten Qwen3 8B runs the
post-warm-up gap fell from +26 to +16, the score rose from 32 to 38, and
near-certain errors fell from 12 to 2 per 100; every one of the ten runs
improved. Matched accuracy-only training moved the other way on that track
(gap +33). The improvement carried to held-out subjects consistently for Qwen3
8B and unevenly for GPT-OSS 20B, and on a decision battery it nearly eliminated
wrong actions taken at 90%+ confidence in both families without moving broader
alignment measures.

On the same 800 questions and the same two open-weight checkpoints, in
commensurate units: explaining the rule costs about 4 points of score, hedging
buys about 4, and training on the score buys about 11. Differences under about
two points are inside this design's run-to-run noise.
