## open | Evidence ledger and next tests

The table separates exact results, replicated findings, directional pilots,
and unresolved claims. The last column states what would change each verdict.

{b_status}

### What to run next

The battery now covers cross-subject transfer, catastrophic decisions, evidence
response, honesty under pressure, instruction hierarchy, paired benign and
harmful requests, and hidden unauthorized shortcuts. Four gaps matter next.

1. **Make a second model family format-stable before reward training.** Nemotron
failed one of two full profiles after a 4,096-example format checkpoint. Kimi
then malformed 932 of 1,920 responses, while GPT-OSS exhausted its short output
allowance before reaching an answer. The next attempt should use a constrained
decoder that makes malformed output structurally impossible, then repeat two
full 1,920-response profiles. Do not loosen the 1% gate.

2. **Extend hidden opportunities across several tool calls.** The new
single-step test found many unauthorized actions and a small calibration effect,
so it can separate models. It found no concealment. A stronger environment
should add memory, private intermediate choices, delayed consequences, and an
opportunity to hide what happened. Keep the matched authorized control and task
completion endpoint.

3. **Test the proposed mechanism, not only its endpoints.** Cross a calibration
objective with the plural-ends reminder during training. Measure whether either
intervention changes uncertainty awareness, search for alternative goals,
policy sensitivity, and shortcut use. This would test whether metacognition and
plurality are complementary causes rather than adjacent observations.

4. **Make the harmful test capable of separating models.** XSTest harmful
handling saturated at zero compliance, even under the neutral pilot prompt.
Use generated responses on harder dual-use requests, pair them with benign
lookalikes, and validate the grader against human labels before scaling.

### The comparison to make

Use deliberately selected checkpoints: the untuned base, matched accuracy and
confidence objectives, and independent seeds. Run frozen items under a neutral
prompt first. Report each alignment dimension separately, alongside its benign
control, and compare models within the same seed and dose.

More calls to the completed Qwen factual matrix would add precision without
adding much generality. The next paid work should repair cross-model format
stability, test the plural-ends mechanism, or add time and concealment to the
agentic environment.
