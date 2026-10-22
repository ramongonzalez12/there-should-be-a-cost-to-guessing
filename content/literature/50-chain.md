## chain | Calibration improves prudence, not alignment in general

<div class="novelty-line"><span class="novelty-dots" aria-label="novelty 3 of 3">&#9679;&#9679;&#9679;</span> <b>New comparison.</b> No direct matched test of the calibration-to-behavior chain was found in this review.</div>

The closing section is the honest one: calibrated models gate their own risky
answers far better, and that is where the good news stops. The idea that
uncertainty makes agents safer has a long theoretical pedigree. The matched
experiment that checks each link of that chain after calibration training is
what this review could not find.

<div class="literature-compare">
<div class="literature-compare-title">Where the behavior chain stands</div>
<dl>
<div><dt>Nearest prior work</dt><dd><b>Outside LLMs, 2016.</b> <i class="lit-tag adjacent">Adjacent</i> The <a href="https://arxiv.org/abs/1611.08219">Off-Switch Game</a> and <a href="https://arxiv.org/abs/1606.03137">CIRL</a> show formally that objective uncertainty can make agents accept correction. <b>LLM systems and alignment, 2023 to 2025.</b> <i class="lit-tag close">Close</i> <a href="https://arxiv.org/abs/2307.01928">KnowNo (2023)</a> converts calibrated uncertainty into asking for help across simulated and real robot tasks, at runtime and without fine-tuning. <i class="lit-tag close">Close</i> <a href="https://arxiv.org/abs/2507.03120">Kumaran et al. (2025)</a> measure how commitment and criticism distort confidence and evidence updating. <i class="lit-tag adjacent">Adjacent</i> <a href="https://arxiv.org/abs/2402.05070">Pluralistic alignment (2024)</a> defines three forms of pluralism and three benchmark families for the many-values problem.</dd></div>
<div><dt>What it did not test</dt><dd>Whether training a model to be calibrated about facts changes any downstream behavior: risky decisions, evidence updating, goal revision, or taking a prohibited shortcut. The theory papers assume the link; the measurement papers observe single pieces without intervening on calibration.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>A matched test of several links at once, mostly negative.</b> Confidence training removed 97% of overconfident wrong actions in a structured decision test. It did not improve evidence updating or goal revision, and it removed only 2% of prohibited hidden shortcuts. A one-line plural-ends reminder did far more for shortcuts, cutting them from 6.8% to 1.0% across all 16 tested checkpoints.</dd></div>
<div class="limit"><dt>What it still cannot show</dt><dd>The shortcut scenarios are short and transparent. They measure rule-following under mild temptation, not scheming, and <a href="https://arxiv.org/abs/2506.15740">SHADE-Arena</a> remains the stronger model of the behavior that matters.</dd></div>
</dl>
</div>

The chain results are in the [table brief](brief-table.html#chain).
