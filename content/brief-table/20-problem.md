## problem | 2. Benchmark design makes guessing rational

{tb_problem}

<div class="table-brief-reading"><b>Takeaway.</b> Benchmarks usually record
correctness without asking how much confidence the model placed behind the
answer. They therefore cannot distinguish a careful belief from a bluff.</div>

<div class="literature-compare">
<div class="literature-compare-title"><i class="lit-tag direct">Direct precedent</i> Benchmark incentives and abstention</div>
<dl>
<div><dt>What prior work did</dt><dd><a href="https://arxiv.org/abs/2509.04664">Kalai et al.</a> analyzed why binary accuracy grading rewards guessing. <a href="https://arxiv.org/abs/2506.09038">AbstentionBench</a> tested 20 models on 20 datasets containing unanswerable or underspecified questions.</dd></div>
<div><dt>What it found</dt><dd>Accuracy-first evaluation can make a guess score better than admitting uncertainty. AbstentionBench found that abstention remains unreliable and that reasoning fine-tuning made it 24% worse on average.</dd></div>
<div><dt>What it called for</dt><dd>Change the main benchmark incentives, not merely add another hallucination test. Treat uncertainty and justified abstention as scored behavior.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>Breadth plus observed behavior.</b> It audits 45 scoring records and 1,088,601 published answers, then uses one scoring rule in prompting and matched training experiments. The incentive diagnosis itself is not new.</dd></div>
</dl>
</div>

^ <span class="table-brief-source">{tb_src_census}</span>
