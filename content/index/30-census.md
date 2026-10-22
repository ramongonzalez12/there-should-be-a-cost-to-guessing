## census | How often models decline

The census scans every per-question model output in the public EvalEval
datastore for roughly eighteen ways of saying "I don't know", anywhere in the
generation. Decline language clusters where the environment can show the model
that it failed; on closed-form question answering it is nearly absent.

{split_table}

^ Agentic tasks decline at {agentic_rate}; closed-form exams at {closed_rate}.
The pooled headline of {decline_pct} counts every response. The essay carries
the full benchmark-by-benchmark table and a model-by-model comparison on one
shared suite.
