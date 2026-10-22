## scoring | A penalty for guessing, and which one

<div class="novelty-line"><span class="novelty-dots" aria-label="novelty 2 of 3">&#9679;&#9679;&#9675;</span> <b>Sharper proposal.</b> The rule is classical and priced grading is already shipping; the strictly proper, probability-eliciting version for LLM benchmarks is the proposal here.</div>

The second section proposes scoring wrong answers below silence with the
quadratic rule 2p &minus; p&sup2;. Proper scoring itself is not new: the
theory is more than seventy years old, and educational testing applied
guessing penalties for decades. The application is where the ground is open.
Every priced rule now in circulation for language models is a decision rule
(answer or abstain, at some penalty); none elicits the probability itself,
and the norm is being set now.

<div class="literature-compare">
<div class="literature-compare-title">Where the scoring proposal stands</div>
<dl>
<div><dt>Nearest prior work</dt><dd><b>Outside LLMs, 1950 to 2007.</b> <i class="lit-tag direct">Direct</i> <a href="https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2">Brier</a>, <a href="https://doi.org/10.1080/01621459.1971.10482346">Savage</a>, and <a href="https://doi.org/10.1198/016214506000001437">Gneiting and Raftery</a> built the theory of strictly proper scoring rules under which honest probability reporting is the best strategy. <i class="lit-tag close">Close</i> <a href="https://doi.org/10.1007/BF02289503">Human test scoring in the 1960s</a> applied those rules, and <a href="https://doi.org/10.1109/TIT.1970.1054406">Chow (1970)</a> formalized declining to classify when confidence is too low. <b>LLM benchmarks, 2025.</b> <i class="lit-tag direct">Direct</i> <a href="https://arxiv.org/abs/2509.04664">Kalai et al.</a> call for explicit confidence targets in benchmark instructions. <i class="lit-tag close">Close</i> <a href="https://arxiv.org/abs/2511.13029">AA-Omniscience</a> prices wrong answers across 6,000 questions, 42 topics, and six domains.</dd></div>
<div><dt>What it did not test</dt><dd>Kalai et al.'s remedy is a threshold rule: proper as a decision, but it elicits an answer-or-abstain choice and no probability, and the price must be fixed before generation. AA-Omniscience hard-codes that price with a linear rule, abstention scoring zero and the price never announced to the model, a form that <a href="why-linear-fails.html">cannot elicit a probability at all</a>. Neither, nor the ternary-reward variants, obtains the number that would let a reader re-price wrongness after the fact.</dd></div>
<div class="project"><dt>What this project adds</dt><dd><b>The strictly proper version, and the conditions for it to matter.</b> Because the rule elicits the full probability, the deployment price becomes a transparent, adjustable parameter applied after generation rather than a constant baked silently into the leaderboard. Five candidate rules implemented with numerical properness checks, plus a structural check across 69 published GPQA runs: without an explicit I DON'T KNOW option, any penalty is an affine rescaling of accuracy and cannot change a single ranking.</dd></div>
</dl>
</div>

The full lineage, from weather forecasting through formula scoring to
selective classification, is on [What this builds on](related-work.html).
