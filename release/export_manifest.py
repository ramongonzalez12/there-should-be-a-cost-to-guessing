"""The public-release boundary, as data.

Everything the public `below-zero` repository contains is listed here, either
as an exact path or a directory glob minus explicit denials. A file absent
from this manifest does not ship, and a file removed from it is deleted from
the public repository on the next export. The exporter
(scripts/export_public_release.py) enforces the boundary; this module only
declares it.

The boundary implements the decisions recorded in the release plan:
verification-grade disclosure (a stranger can check every published number),
lab notebook and agent/spend operations private, and (since 2026-10-22) NO
code that can send a request to a model API or a training service. What ships
is the data, the scoring code, the no-key data step that rebuilds every essay
number, and plain docs; the code that called, evaluated, and trained the
models stays in the lab. The exporter's
model-calling guard enforces that last rule, and NETWORK_ALLOWED below names
the only shipped files that may open a network connection at all.
"""

# Directories exported wholesale. Deny rules below still apply inside them.
ALLOW_DIRS = [
    "src/belowzero",
    "data/processed",
    "data/slices",
    # The essay's data: figure CSVs, tables, graded rows (tier 3, text-free,
    # canary on line 1), judge receipts, and inputs. data/essay/README.md is
    # its one description.
    "data/essay",
    "content",
    "docs",
    "tests",
    "site/below-zero",
]

# Individual files exported.
ALLOW_FILES = [
    "LICENSE",
    "LICENSE-DATA",
    "NOTICE",
    "CITATION.cff",
    "pyproject.toml",
    "PREREGISTRATION.md",
    "PLURAL_PRUDENCE_PREREGISTRATION.md",
    "data/behaviour_items.json",
    "data/models_catalog.csv",
    # -- census and scoring mathematics ------------------------------------
    "scripts/census.py",
    "scripts/census_decline_samples.py",
    "scripts/census_tables.py",
    "scripts/hle_rescore.py",
    "scripts/hle_confidence.py",
    "scripts/properness.py",
    "scripts/power.py",
    "scripts/benchmark_scoring_survey.py",
    "scripts/affine_map.py",
    # -- the essay's data step: graded rows to every table, figure, number --
    "scripts/essay_data_step.py",
    "scripts/census_exclusions.py",
    "scripts/export_warning_comparison.py",
    "scripts/export_battery_thresholds.py",
    # -- writers of the committed data/processed tables --------------------
    "scripts/export_untuned_transfer_levels.py",
    "scripts/export_training_common_battery.py",
    "scripts/export_cross_family_completion.py",
    "scripts/export_gptoss_transfer.py",
    "scripts/export_prompt_estimation.py",
    "scripts/export_finetune_matrix.py",
    "scripts/analyze_policy_architecture.py",
    "scripts/analyze_prompt_threshold_factorial.py",
    "scripts/export_sycophancy.py",
    "scripts/export_pressure_replication.py",
    "scripts/export_pressure_prompting.py",
    "scripts/export_behaviour.py",
    "scripts/summarize_broader_evals.py",
    "scripts/analyze_alignment_relationship.py",
    "scripts/export_alignment_battery.py",
    "scripts/export_plural_prudence.py",
    "scripts/export_external_transfer.py",
    "scripts/export_domain_alignment.py",
    "scripts/export_domain_replication.py",
    "scripts/export_multitask_family_agentic.py",
    "scripts/export_openweight_family.py",
    "scripts/export_openweight_followup.py",
    "scripts/analyze_seed_replication.py",
    "scripts/analyze_dose_grid_matrix.py",
    "scripts/analyze_confidence_oscillation.py",
    "scripts/analyze_notation_artifact.py",
    "scripts/build_battery_cohort.py",
    "scripts/export_prompt_extension.py",
    "scripts/export_coverage_universes.py",
    "scripts/essay_training_matrix.py",
    "scripts/essay_transfer_synthesis.py",
    "scripts/essay_reader_notes.py",
    "scripts/essay_action_gate.py",
    "scripts/verify_common_training.py",
    "scripts/export_second_programme_training.py",
    "scripts/second_programme_ready.py",
    "scripts/gate_prompt_arm_pilot.py",
    "scripts/analyze_prompt_only_calibration.py",
    "scripts/analyze_prompt_only_composition.py",
    "scripts/analyze_prompt_arm_identification.py",
    "scripts/audit_near_zero_confidence.py",
    "scripts/chart_prompt_only_calibration.py",
    "scripts/export_calibration_context.py",
    "scripts/export_pilot_levels.py",
    "scripts/export_model_coverage_extension.py",
    "scripts/export_seed_dense_knowledge.py",
    "scripts/export_base_model_prompt_arms.py",
    "scripts/replication_verdict.py",
    "scripts/summarize_tinker_seeds.py",
    "scripts/build_pooled_family_manifest.py",
    "scripts/build_broader_checkpoint_manifest.py",
    "scripts/build_domain_checkpoint_manifest.py",
    "scripts/build_dense_eval_manifest.py",
    "scripts/build_multitask_manifests.py",
    "scripts/build_pool_difficulty.py",
    # -- not shipped: code that calls a model or a training service ----------
    # The original runner and CLI, the judge-grading path and its re-grader,
    # the evaluation battery (scripts/evaluate_*), the training recipe
    # (scripts/train_*, the prepare_/select_/plan_/run_qwen_ data and launch
    # scripts, checkpoint rescue), and the model-catalog refresher all stay in
    # the lab. Listing them here by name would only advertise them; their
    # absence from this allowlist is the rule, and the exporter's
    # model-calling guard is its check.
    # -- site generators ----------------------------------------------------
    "scripts/build_site.py",
    "scripts/content.py",
    "scripts/build_essay_page.py",
    # -- the release boundary itself, published for inspection --------------
    "scripts/export_public_release.py",
    "release/export_manifest.py",
    # The lab's essay-number verifier (verify_essay_v29_numbers) stays
    # private: it imports the private essay-v2 builder. The public
    # rebuild-and-diff CI job is the stranger-facing equivalent proof.
]

# Paths inside ALLOW_DIRS that must NOT ship. Draft pages whose generators are
# private, and tests whose target scripts are private.
DENY = [
    "site/below-zero/essay-v625.html",
    "site/below-zero/essay-v626.html",
    "site/below-zero/essay-v624.html",
    "site/below-zero/essay-v623.html",
    "site/below-zero/essay-v622.html",
    "site/below-zero/essay-v621d.html",
    "site/below-zero/essay-v621c.html",
    "site/below-zero/essay-v621b.html",
    "site/below-zero/essay-v620c.html",
    "site/below-zero/essay-v620b.html",
    "site/below-zero/essay-v619b.html",
    "site/below-zero/essay-v618b.html",
    "site/below-zero/essay-v617b.html",
    "site/below-zero/essay-v615b.html",
    "site/below-zero/essay-v616b.html",
    "tests/test_v616b_training_matrix.py",
    "data/processed/essay_cohort_manifest.json",
    "tests/test_essay_cohort.py",
    "site/below-zero/essay-v2.html",
    "site/below-zero/essay-notes.html",
    "site/below-zero/model-status.html",
    "tests/test_essay_v612.py",
    "site/below-zero/essay-format-review.html",
    "site/below-zero/oscillation.html",
    "site/below-zero/divider-lab.html",
    "site/below-zero/design-lab.html",
    "site/below-zero/design-lab-2.html",
    # Working pages for whoever builds the site (build_site.LAB_ONLY_PAGES):
    # the change log, the report draft, the plan, the design lab, and their
    # prose. No shipped page links them, and the public tree does not build them.
    "site/below-zero/changes.html",
    "site/below-zero/draft.html",
    "site/below-zero/plan.html",
    "site/below-zero/style-guide.html",
    "content/changes/00-summary.md",
    "content/changes/10-numbers.md",
    "content/changes/20-defects.md",
    "content/changes/30-data.md",
    "content/changes/40-essay.md",
    "content/changes/50-site.md",
    "content/changes/60-open.md",
    "content/changes/65-revisions.md",
    "content/changes/70-versions.md",
    "content/draft/00-lead.md",
    "content/draft/05-context.md",
    "content/draft/10-premise.md",
    "content/draft/20-rules.md",
    "content/draft/30-models.md",
    "content/draft/40-prompting.md",
    "content/draft/50-training.md",
    "content/draft/60-alignment.md",
    "tests/test_agent_run.py",
    "tests/test_drive_seed_replication.py",
    "tests/test_reconcile_tinker_spend.py",
    "tests/test_essay_format_review.py",
    "tests/test_essay_v40.py",
    "tests/test_essay_reader_notes.py",
    "tests/test_essay_v6_keys.py",
    "tests/test_essay_v69.py",
    "tests/test_essay_mobile_reading.py",
    "tests/test_essay_v626_takeaways.py",
    # The clean retrain's private halves: the pool freeze script and the
    # experiments/confidence_only evaluation code these tests import.
    "tests/test_clean_contract_extractor.py",
    "tests/test_freeze_clean_training_pool.py",
    "tests/test_clean_retrain_rehearsal.py",
    # Imports test_clean_retrain_rehearsal (denied above).
    "tests/test_confidence_credit.py",
    # Imports the lab-side graded-rows extractor and reads the lab's
    # absent-model record (the public half is in test_essay_data_step.py).
    "tests/test_export_graded_rows_causes.py",
    # -- model-calling code. The package's runner, CLI, judge grading, preflight, credential
    # lookup, and paid-run planning; the training and evaluation libraries and
    # their spend and checkpoint bookkeeping; and every test that drives them.
    # The exporter's model-calling guard fails the export if any of this, or
    # anything like it, reaches the public tree.
    # Framing for the evaluation scripts, which no longer ship.
    "docs/alignment-battery-framing.md",
    "src/belowzero/runner.py",
    "src/belowzero/cli.py",
    "src/belowzero/doctor.py",
    "src/belowzero/grade.py",
    "src/belowzero/credentials.py",
    "src/belowzero/budget.py",
    "src/belowzero/models.py",
    "src/belowzero/spend.py",
    "src/belowzero/tinker_config.py",
    "src/belowzero/checkpoints.py",
    "src/belowzero/training_data.py",
    "src/belowzero/confidence_credit.py",
    "src/belowzero/format_warmup.py",
    "src/belowzero/transfer_battery.py",
    "src/belowzero/xstest_actions.py",
    "src/belowzero/plural_prudence.py",
    "tests/mockserver.py",
    "tests/fake_tinker.py",
    "tests/clean_fixtures.py",
    "tests/test_e2e.py",
    "tests/test_credentials.py",
    "tests/test_parity.py",
    "tests/test_grading_rigor.py",
    "tests/test_spend.py",
    "tests/test_checkpoints.py",
    "tests/test_format_warmup.py",
    "tests/test_training_data.py",
    "tests/test_transfer_battery.py",
    "tests/test_xstest_actions.py",
    "tests/test_plural_prudence.py",
    "tests/test_alignment_battery.py",
    "tests/test_backfill_failed_sampling_ceiling.py",
    "tests/test_cross_family_replication.py",
    "tests/test_evaluate_tinker.py",
    "tests/test_evaluate_tinker_grid.py",
    "tests/test_evaluate_domain_transfer.py",
    "tests/test_hidden_opportunity.py",
    "tests/test_sycophancy.py",
    "tests/test_item_order.py",
    "tests/test_plan_qwen_dose_grid.py",
    "tests/test_plan_qwen_seed_replication.py",
    "tests/test_prepare_domain_replication_data.py",
    "tests/test_prepare_domain_transfer_data.py",
    "tests/test_prepare_format_failure_replay.py",
    "tests/test_prepare_multitask_transfer.py",
    "tests/test_prepare_qwen_dose_extension.py",
    "tests/test_prepare_qwen_dose_grid.py",
    "tests/test_run_qwen_dose_grid.py",
    "tests/test_run_qwen_seed_replication.py",
    "tests/test_select_profile_cohort.py",
    "tests/test_select_training_data.py",
    "tests/test_select_training_data_tough.py",
    "tests/test_train_grpo.py",
    "tests/test_train_tinker.py",
]

# The only shipped files allowed to open a network connection, each with the
# reason. Every one reads a public data archive or a benchmark's own published
# source; none calls a model or a training service, and the model-calling
# guard still applies to them in full. Any other shipped code that imports a
# network client fails the export.
NETWORK_ALLOWED = {
    "src/belowzero/datasets.py":
        "downloads the benchmark question banks from their original public sources",
    "scripts/census.py":
        "streams the public evaleval/EEE_datastore archive from Hugging Face (the census)",
    "scripts/census_decline_samples.py":
        "reads the same public archive for the census's decline excerpts",
    "scripts/hle_rescore.py":
        "reads the same public archive for the HLE rescoring",
    "scripts/hle_confidence.py":
        "reads the same public archive for the HLE stated-confidence check",
    "scripts/affine_map.py":
        "reads the same public archive for the affine-map check",
}

# Files whose PUBLIC version lives in release/public/ and overrides (or has no
# counterpart in) the lab tree. Keys are paths in release/public/, values are
# destinations in the public repository.
OVERLAY = {
    "README.md": "README.md",
    "REPRODUCING.md": "REPRODUCING.md",
    "gitignore": ".gitignore",
    "ci.yml": ".github/workflows/ci.yml",
    # The lab Makefile drives private regeneration (run databases, the essay
    # builder and its verifier); the public one runs what a stranger can.
    "Makefile": "Makefile",
    # Reviewed gitleaks false positives, one finding per line (file:rule:line).
    "gitleaksignore": ".gitleaksignore",
}

# Strings that may legitimately contain the author's name in the export
# (everything else containing it fails the leak guard).
NAME_ALLOWED_IN = [
    "LICENSE",
    "CITATION.cff",
    "README.md",
    "pyproject.toml",
]
