## census | 1. Models decline on only {b_closed_clean} of closed-form questions

**Point.** On ordinary knowledge questions, models almost always give an answer.

**Basis.** We searched every published response in the EvalEval Coalition's
&ldquo;Every Eval Ever&rdquo; datastore for roughly eighteen ways of saying
&ldquo;I don't know.&rdquo;{b_fn_census_phrases}

{b_stats}

{b_split}

**Meaning.** Models do decline when the task itself proves that an answer is
impossible. They rarely decline when a valid answer exists but they may not know
it. On the benchmark that provides the same puzzles with and without the needed
context, declines are {b_lingoly_ratio}&times; more common when the context is
missing.

**Limit.** The published {b_decline_pct} rate includes tasks where declining or
asking for clarification is the correct behavior. It is therefore a conservative
upper bound on uncertainty-driven abstention. {b_src_census}

:::details Benchmark-level results and phrase audit
{b_bench}

{b_phrase}

The four highest closed-form rates were manually inspected. Two were phrase
artifacts, and two came from questions designed to be unanswerable. The full
sensitivity grid is in [the appendix](#appendix).
:::
