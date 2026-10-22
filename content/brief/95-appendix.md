## appendix | Methods and definitions

### What the main measures mean

- key: **Overall accuracy.** Correct answers divided by all questions. Declines
count against accuracy.
- key: **Coverage.** Questions the model answered divided by all questions.
- key: **Accuracy when answered.** Correct answers divided only by answered
questions.
- key: **Confidence when answered.** The model's average stated probability on
the questions it answered.
- key: **Calibration error among answers.** The weighted confidence-to-accuracy
gap within confidence bands. Lower is better.
- key: **Confidence-calibrated score.** The quadratic score averaged over all
questions. Higher is better. A right answer earns `2p &minus; p&sup2;`, a
wrong answer earns `&minus;p&sup2;`, and silence earns zero.

These labels state their denominators because overall accuracy and confidence
among answers are not directly subtractable when a model abstains.

:::details Dataset registry
{b_vintage}

Pull dates are source-specific. The datastore has grown since the census, so a
new census would cover a different corpus.
:::

:::details Decline-count sensitivity
A response counts as declining if any of roughly eighteen phrases appears
anywhere in it. This deliberately generous rule makes a low rate harder to
dismiss.

{b_sens}

Under the strictest reading, three clear phrases searched only near the end of
the response, the GPQA Diamond rate is zero out of 13,662.
:::

:::details Treatment and score details
Every confidence-calibrated-score column uses the plain quadratic rule, even
when the model was trained with an added answering cost. The reward used for
training and the measure used for evaluation are kept separate.

In the live pilot, &ldquo;told the rule&rdquo; combined the formula, an
explanation that honesty was optimal, and a 0.09 answering cost. The observed
contrast belongs to that package, not to any one component.
:::

:::details Reproducing the page
Every table and figure is generated from committed files. The source line under
each exhibit identifies the dataset and pull date. The registry above names the
script that regenerates each dataset. Run `python3 scripts/build_site.py` to
rebuild the page.
:::

### AI use

Claude was used substantially for analysis code, derivations, and drafting.
Ramon set the research questions and scoring design. Every displayed result is
computed from the published data files.
