"""Reader-facing source catalogue and disclosure behavior for the essay.

Keep presentation here and numerical evidence in the existing essay helpers.
Native details elements work without JavaScript; the enhancement opens nested
targets for citations, bookmarks and browser history, and expands them to print.
"""

import json

TOPICS = (
    ("sources", "Sources worth reading", "Five papers behind the argument."),
    ("census", "Counting “I don’t know”", "What our search counted, and what it missed."),
    ("battery", "Which models we tested", "How we chose them and why some were left out."),
    ("score-notes", "How to read the score", "Why honesty pays, and how unanswered questions count."),
    ("prompts-notes", "What the prompt comparison tests", "The same questions, with different instructions."),
    ("training-notes", "What the training comparison tests", "What changes when the reward changes."),
    ("limits", "What remains uncertain", "What these results cannot tell us."),
)

# A short reading list, selected for the essay's central argument. Supporting
# benchmark and method links stay beside the evidence they document.
SOURCES = (
    ("Brier (1950): scoring a probability",
     "https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2",
     "Introduced squared-error scoring for probability forecasts. We use it to compare LLM answers and to measure the effects of prompting and reward training."),
    ("Gneiting and Raftery (2007): rewarding an honest estimate",
     "https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf",
     "Explains why the rule rewards an honest probability estimate. We test whether explaining or training on that incentive makes model confidence better match accuracy."),
    ("Kalai et al. (Nature, 2026): why accuracy tests reward guessing",
     "https://www.nature.com/articles/s41586-026-10549-w",
     "Explains guessing incentives and tests announced scoring rules. We add a census of published responses and test a probability-scoring explanation and an overconfidence warning on the same models and questions."),
    ("Damani et al. (2025; revised 2026): training models to express uncertainty",
     "https://arxiv.org/abs/2507.16806v2",
     "RLCR tests the same reward, including on new tasks. We hold the short response format fixed across both training arms, repeat the comparison across model families and subjects, and test behavior beyond question answering."),
    ("Steyvers, Belem and Smyth (2025; revised 2026): taking uncertainty to new tasks",
     "https://arxiv.org/abs/2510.05126v3",
     "Finds gains on new subjects after supervised fine-tuning, with limited transfer between confidence tasks. We test reward training in every direction between math, medicine and ethics, tracking accuracy and unanswered questions alongside confidence."),
)

READER_NOTES_CSS = """
.reader-notes { width: 100%; max-width: var(--max-wide); clear: both; margin: 24px 0 36px; }
.reader-note { clear: both; margin: 0; border-bottom: 1px solid var(--rule); }
.reader-note > summary { position: relative; max-width: var(--max-text); cursor: pointer; padding: 17px 0 17px 22px; color: var(--accent-text);
  font: 600 18px/1.5 'Source Serif 4', Georgia, serif; list-style: none; }
.reader-note > summary::-webkit-details-marker { display: none; }
.reader-note > summary::before { content: '+'; position: absolute; left: 0; width: 22px; font-weight: 400; }
.reader-note[open] > summary::before { content: '−'; }
.reader-note > summary .note-description { display: block;
  color: var(--text-secondary); font: 400 14px/1.55 'Inter', sans-serif; margin-top: 3px; }
.reader-note > summary:focus-visible { outline: 2px solid var(--accent-text); outline-offset: 4px; }
/* Every expanded level moves right, including long tables, so its parent
   remains visible in the left margin. Use smaller steps on a phone. */
.reader-note-body { margin-left: 44px; padding: 3px 0 24px; min-width: 0; }
.reader-note-body .tbl-fold-body { padding-left: 24px; padding-right: 0; }
.reader-note-body .tbl-fold .tbl-fold { margin-left: 12px; }
.reader-note-body > h2:first-child { margin-top: 12px; }
.reader-note-body .wide { max-width: 100%; margin-left: 0; margin-right: 0; }
.reader-note-body .source-entry { margin: 14px 0 20px; }
.reader-note-body .source-entry .sub { display: block; margin-top: 4px; color: var(--text-secondary); font: 14px/1.6 'Inter', sans-serif; }
.reader-note-body table { font-size: 13px; }
.reader-note-body .table-wrap, .reader-note-body .tbl-scroll { max-width: 100%; }
.note-permalink { font: 12px/1.5 'Inter', sans-serif; margin: 16px 0 0; }
.reader-footer a { color: var(--on-plum); text-underline-offset: 3px; }
#part-5, .reader-note, .reader-note-body [id] { scroll-margin-top: 145px; }
/* Notes also link back to existing essay folds. Keep their titles below the
   sticky navigation when opening a prompt or a results table by fragment. */
body.with-section-nav details[id] { scroll-margin-top: 150px; }
@media (max-width: 600px) {
  .reader-note > summary { font-size: 18px; }
  .reader-note-body { margin-left: 28px; }
  .reader-note-body .tbl-fold-body { padding-left: 16px; }
  .reader-note-body .tbl-fold .tbl-fold { margin-left: 0; }
  .reader-note > summary .note-description { font-size: 13px; }
}
@media print {
  .reader-note { break-inside: auto; }
  .reader-note > summary { color: black; }
  .reader-note-body { display: block !important; }
  .note-permalink { display: none; }
}
"""

# Keep old appendix bookmarks useful after removing duplicate displays.
LEGACY_NOTE_TARGETS = {
    'note-5': 'pop-no-penalty-for-guessing',
    'note-6': 'pop-honest-confidence-scoring',
    'note-7': 'pop-brier-loss',
    'note-10': 'pop-rlcr',
    'note-14': 'pop-24-matched-pairs',
    'note-16': 'pop-same-pooled-training-checkpoints',
    'note-19': 'pop-external-gate',
    'note-21': 'pop-carries-to-other-subjects',
    'note-5-copy-2': 'scoring',
    'fig-heatmap': 'score-notes',
    'score-honest-example': 'fig-payoff-curve',
    'tbl-behaviour': 'tbl-behavior-summary',
    'tbl-coverage': 'coverage',
    'tbl-difficulty': 'fig-scissors',
    'tbl-expected-values': 'fig-payoff-curve',
    'tbl-families': 'fig-bars',
    'tbl-historical-behaviour': 'study-history',
    'tbl-hle': 'score-notes',
    'tbl-leaderboard': 'board',
    'tbl-matched-detail': 'study-history',
    'tbl-models': 'tbl-developers',
    'tbl-post-training-coverage': 'training-notes',
    'tbl-prudence': 'training-notes',
    'tbl-reader-score-rule': 'fig-score-build',
    'tbl-rule-movers': 'prompts-notes',
    'tbl-rule-scope': 'prompts-notes',
    'tbl-seed-results-gpt-oss-20b': 'training-notes',
    'tbl-seed-results-nemotron-3-nano-30b': 'training-notes',
    'tbl-seed-results-qwen3-8b': 'training-notes',
    'tbl-synthesis': 'study-history',
    'tbl-transfer': 'common-transfer',
    'tbl-transfer-synthesis': 'fig-transfer-summary',
    'tbl-untuned-rule': 'prompts-notes',
}

READER_NOTES_JS = """
(function () {
  var legacyTargets = __LEGACY_TARGETS__;
  function revealHash() {
    if (!location.hash) return;
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    var target = document.getElementById(id) || document.getElementById(legacyTargets[id]);
    if (!target) return;
    var node = target;
    while (node) {
      if (node.tagName === 'DETAILS') node.open = true;
      node = node.parentElement;
    }
    // Former numbered citations now belong to their underlined phrase. Open
    // that one note on a bookmark visit, including inside a collapsed result.
    if (target.classList.contains('fnbody')) {
      var trigger = document.querySelector('.note-trigger[aria-controls="' + target.id + '"]');
      if (trigger) requestAnimationFrame(function () {
        trigger.scrollIntoView({block: 'center'});
        if (trigger.getAttribute('aria-expanded') !== 'true') trigger.click();
      });
      return;
    }
    requestAnimationFrame(function () { target.scrollIntoView({block: 'start'}); });
  }
  window.addEventListener('hashchange', revealHash);
  // Clicking the same hash again emits no hashchange, even if its fold was closed.
  document.addEventListener('click', function (event) {
    var link = event.target.closest('a[href^="#"]');
    if (link && link.hash === location.hash) requestAnimationFrame(revealHash);
  });
  revealHash();
  var printState = [];
  window.addEventListener('beforeprint', function () {
    printState = Array.from(document.querySelectorAll('.reader-notes details')).map(function (d) {
      var state = [d, d.open]; d.open = true; return state;
    });
  });
  window.addEventListener('afterprint', function () {
    printState.forEach(function (s) { s[0].open = s[1]; }); printState = [];
  });
})();
""".replace("__LEGACY_TARGETS__", json.dumps(LEGACY_NOTE_TARGETS))


def moved_notes_html():
    """Old URLs retain their fragments; a normal link works without scripting."""
    links = ''.join(f'<li><a href="essay-v2.html#{key}">{title}</a></li>'
                    for key, title, _ in TOPICS)
    return ('<header class="essay-hero"><h1>Notes and sources have moved into the essay</h1>'
            '<p>Each topic now opens beneath its title on the essay itself.</p></header>'
            '<p><a href="essay-v2.html#part-5">Read the notes and sources</a></p>'
            f'<ul>{links}</ul>'
            '<script>location.replace("essay-v2.html" + (location.hash || "#part-5"));</script>')
