## next | The decisive test exists and has not been run

<div class="novelty-line"><span class="novelty-dots" aria-label="novelty not yet run">&#9675;&#9675;&#9675;</span> <b>Open ground.</b> No precedent and no result either; this is where the next increment of novelty is available.</div>

The write-up closes by arguing that scoring has more than one axis. The
literature already supplies the environments where that claim gets its real
test; what is missing is running matched calibration-trained checkpoints
inside them.

<div class="literature-compare">
<div class="literature-compare-title">Where the next step stands</div>
<dl>
<div><dt>Nearest prior work</dt><dd><i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2506.15740">SHADE-Arena</a> pairs long benign tasks with hidden sabotage objectives under monitoring. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2506.04018">AgentMisalignment</a> elicits shutdown resistance, sandbagging, and power seeking. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2304.03279">MACHIAVELLI</a> exposes reward-versus-ethics tradeoffs across 134 games. <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2410.09024">AgentHarm</a> tests harmful compliance alongside retained competence.</dd></div>
<div><dt>What it did not test</dt><dd>Every one of these compares models, prompts, or personas. None compares training objectives: the same checkpoint trained with accuracy-only reward against the same checkpoint trained with a proper confidence reward, dropped into the same hidden-opportunity environment.</dd></div>
<div class="project"><dt>What this project should add next</dt><dd><b>The missing combination.</b> Run the matched accuracy-trained and confidence-trained pairs in these environments, keep benign controls so lower misconduct cannot be bought with general refusal, and treat the independently trained pair as the replication unit. That experiment would test the alignment claim directly. Enlarging the current shortcut battery would not.</dd></div>
</dl>
</div>

The candidate designs are on the [open questions page](open-questions.html)
and at the end of the [table brief](brief-table.html#next).
