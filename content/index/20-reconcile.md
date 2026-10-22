## reconcile | Announcing a rule can change whether a model answers, not how well it knows

Two results on this site look like they disagree and do not. In the free-form
existence check of August 15 (50 SimpleQA questions, six models), announcing
the score together with a 30% abstention threshold raised explicit "I don't
know" answers by 34 points for two of the six models and by 14 for a third,
with matching drops in error. On the eight multiple-choice benchmarks of the
main study, the same rule leaves confidence, accuracy, and the proper score
where they were.

Both are true. A rule can move the decision to answer a hard open question; it
does not move the calibration of the answers a model gives, because nothing in
a prompt tells the model which of its answers are the wrong ones. That is what
training on the score does, and why it is the intervention that moves the
score.

On September 2, 2026 a review of the grading code found that two benchmarks in
the main study had been graded against a stand-in item with no answer choices,
so every answer of "A" was recorded as an abstention and the real abstention
letter as a wrong answer; a second defect meant MMLU-Pro abstentions could
never count. Every retained run was re-parsed and re-graded from its stored raw
text, no model was re-queried, and the tables on this site and in the essay
carry the corrected numbers. The headline gap moved from +13 to +12 and the
training result did not move at all.
