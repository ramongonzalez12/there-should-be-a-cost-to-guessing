## summary | Summary

How a test is scored matters. Almost every AI benchmark pays one point for a
correct answer and nothing for a wrong one or for silence, so a model that is
unsure has no reason to say so. This site measures how completely that is true,
proposes a score that prices confident error, and tests what changes a model's
calibration: telling it the rule, telling it to hedge, or training it on the
score.

- key: **Models almost never decline.** Across {total} published responses
from {n_models} models on {n_bench} benchmarks, {decline_pct} contain any
admission of not knowing.
- key: **Confidence does not track difficulty.** Ten current models, asked for
a probability with every answer on the same frozen questions, ran about 12
points more confident than accurate, 22 points on the three hardest benchmarks,
and were wrong at 90%+ stated confidence on 12 of every 100 questions.
- key: **Only training on the score moves the score.** Explaining the rule in
the prompt changes nothing measurable. Telling the model to be less confident
closes the gap but overshoots and leaves the proper score flat. Fine-tuning on
the score cut the gap from +26 to +16 points across ten runs, raised the score
from 32 to 38, and cut near-certain wrong answers from 12 to 2 per 100.

The full account, with every number asserted against the committed data, is
[the essay]({essay_page}). This page is the short version and the map.
