"""Regression checks for the GPT-OSS subject-transfer essay artifact."""

from __future__ import annotations

import csv
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class GptOssTransferExportTests(unittest.TestCase):
    """Keep the visible family comparison tied to the admitted run census."""

    @classmethod
    def setUpClass(cls) -> None:
        pair_path = (
            ROOT / "data" / "processed" / "gptoss_subject_transfer_pairs.csv"
        )
        with pair_path.open(encoding="utf-8", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))
        manifest_path = (
            ROOT / "data" / "processed" / "gptoss_subject_transfer_manifest.json"
        )
        cls.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_export_preserves_three_independent_admitted_pairs(self) -> None:
        identities = {
            (row["training_domain"], int(row["training_seed"]))
            for row in self.rows
        }
        self.assertEqual(
            identities,
            {("ethics", 0), ("ethics", 1), ("medicine", 1)},
        )
        self.assertTrue(all(row["model_family"] == "GPT-OSS 20B" for row in self.rows))
        self.assertEqual(self.manifest["planned_training_pairs"], 6)
        self.assertEqual(self.manifest["admitted_training_pairs"], 3)

    def test_every_pair_covers_the_same_four_evaluation_domains(self) -> None:
        for row in self.rows:
            self.assertEqual(int(row["same_subject_pair_tests"]), 1)
            self.assertEqual(int(row["other_trained_subject_pair_tests"]), 2)
            self.assertEqual(int(row["unseen_gpqa_pair_tests"]), 1)
            self.assertEqual(int(row["same_subject_questions_per_arm"]), 300)
            self.assertEqual(int(row["other_trained_subject_questions_per_arm"]), 600)
            self.assertEqual(int(row["unseen_gpqa_questions_per_arm"]), 198)

    def test_pair_level_changes_are_not_misreported_as_twelve_replications(self) -> None:
        # One pair improves the score on GPQA; two do not. The twelve crossed
        # evaluation routes therefore remain evidence about three training
        # replications, not twelve independent fine-tuning runs.
        gpqa_changes = [
            float(row["unseen_gpqa_confidence_calibrated_score_change"])
            for row in self.rows
        ]
        self.assertEqual(sum(change > 0 for change in gpqa_changes), 1)
        self.assertEqual(sum(change <= 0 for change in gpqa_changes), 2)


if __name__ == "__main__":
    unittest.main()
