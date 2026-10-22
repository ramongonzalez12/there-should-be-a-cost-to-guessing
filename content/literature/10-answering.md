## answering | Models answer everything and rarely doubt themselves

<div class="novelty-line"><span class="novelty-dots" aria-label="novelty 1 of 3">&#9679;&#9675;&#9675;</span> <b>Established ground.</b> The incentive diagnosis is prior work's; the census of published behavior at scale is the addition.</div>

The write-up opens with a behavioral claim: in published benchmark runs,
models almost never decline to answer, and their stated confidence runs far
ahead of their accuracy. The diagnosis behind that behavior is established.
The census that measures how completely it holds in the wild is the newer
part.

<div class="literature-compare">
<div class="literature-compare-title">Where the always-answering claim stands</div>
<dl>
<div><dt>Nearest prior work</dt><dd><b>LLM research, 2025 to 2026.</b> <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2509.04664">Kalai et al. (2025)</a> show formally that binary accuracy grading rewards guessing over admitting uncertainty. <i class="lit-tag close">Close</i> <a href="https://arxiv.org/abs/2506.09038">AbstentionBench (2025)</a> finds abstention unreliable across 20 models and 20 purpose-built datasets, and that reasoning fine-tuning makes it 24% worse on average. <i class="lit-tag close">Close</i> <a href="https://arxiv.org/abs/2607.20526">ConfidenceBench (2026)</a> elicits probabilities from 15 frontier models on 200 questions across four categories, repeated three times. Accuracy and confidence-calibration rankings diverge substantially.</dd></div>
<div><dt>What it did not test</dt><dd>How often models actually decline in the benchmark runs that laboratories publish. AbstentionBench asks specially built questions designed to need abstention; it does not count behavior on ordinary benchmark items, which is where the incentive to guess actually operates.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A census of published behavior, followed by new confidence-eliciting tests.</b> Across 1,089,024 graded responses from 104 models on 36 benchmarks, 0.69% ever decline and 0.25% state a probability. Alongside it, an audit of 45 benchmark scoring records shows how rarely a wrong answer scores below silence. We then go beyond stored Humanity's Last Exam answers by explicitly eliciting confidence on six other benchmarks. Across 27 model-benchmark comparisons, 10 models, seven benchmarks, and 5,376 answers, every comparison was overconfident: 55% accuracy versus 87% confidence.</dd></div>
</dl>
</div>

The counts themselves are on the [findings page](index.html) and in the
[table brief](brief-table.html#problem).
