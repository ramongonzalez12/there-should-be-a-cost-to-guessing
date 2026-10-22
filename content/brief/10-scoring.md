## scoring | 2. None of {b_survey_graded} graded benchmarks both score confidence and reward silence

**Point.** A model that is only 1% confident still maximizes its expected score
by answering when a wrong answer and silence both earn zero.

**Basis.** We reviewed how {b_survey_total} benchmarks are scored. Of the
{b_survey_graded} that grade answers right or wrong, none both asks for
confidence and makes silence better than a wrong answer.

{b_landscape}

**Meaning.** The usual benchmark score measures whether an answer was right. It
cannot distinguish a cautious 51% belief from a 99% belief because it never asks
for either number.

**A common false fix.** Subtracting a fixed penalty for each wrong answer, while
still requiring every item to be answered, only rescales accuracy. We verified
this by rescoring all {b_affine_runs} published GPQA Diamond runs at three
penalty levels. The ranking never changed, and the largest numerical departure
from the algebraic prediction was {b_affine_dev}.

**Limit.** Preference arenas, rubric-scored conversations, and agentic tasks do
not reduce cleanly to right, wrong, or silent. The claim applies to benchmarks
with objectively graded answers.

:::details All {b_survey_total} scoring systems and their sources
{b_survey}

Each census row is classified from the datastore's grading labels. Each
external row is classified from the benchmark paper or scoring code.
:::
