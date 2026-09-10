"""
RetinaShield — Batch Prediction & Submission Pipeline Tests

Verifies:
  - Exact preservation of sample_submission.csv column headers, row counts, and ID ordering
  - Strict blocking when images are missing or corrupt (zero label invention)
  - Validation checks: integer classes (0..4), no NaN/missing, no duplicate IDs, no extra index columns
  - Decoupling of clinical mode (abstains on ungradeable) vs competition mode (predicts all + exports sidecar)
  - SHA-256 reproducibility hashes in submission_metadata.json
"""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from app.services.batch_prediction_service import (
    BatchPredictionService,
    SubmissionBlockedError,
    SubmissionValidationError,
)


class TestBatchPrediction(unittest.TestCase):
    """Test suite for batch prediction, submission formatting, and validation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.images_dir = self.root / "test_images"
        self.images_dir.mkdir()
        self.output_dir = self.root / "output"
        self.output_dir.mkdir()

        self.service = BatchPredictionService()

        # Create mock test images
        self.sample_ids = ["img_001", "img_002", "img_003", "img_004", "img_005"]
        for img_id in self.sample_ids:
            img = Image.new("RGB", (64, 64), color=(100, 150, 200))
            img.save(self.images_dir / f"{img_id}.png")

        # Create sample_submission.csv with dummy diagnosis values (e.g. all 0)
        self.sample_csv_path = self.root / "sample_submission.csv"
        with open(self.sample_csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id_code", "diagnosis"])
            for img_id in self.sample_ids:
                writer.writerow([img_id, 0])

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_sample_submission_preserves_order(self):
        """sample_submission parser strictly extracts exact headers and ordered IDs."""
        headers, id_col, label_col, ordered_ids = self.service.parse_sample_submission(
            self.sample_csv_path
        )
        self.assertEqual(headers, ["id_code", "diagnosis"])
        self.assertEqual(id_col, "id_code")
        self.assertEqual(label_col, "diagnosis")
        self.assertEqual(ordered_ids, self.sample_ids)

    def test_missing_image_blocks_submission(self):
        """Missing required image raises SubmissionBlockedError — zero label invention."""
        # Remove img_003
        (self.images_dir / "img_003.png").unlink()

        with self.assertRaises(SubmissionBlockedError) as ctx:
            self.service.audit_and_resolve_images(self.sample_ids, self.images_dir)

        self.assertIn("missing images", str(ctx.exception).lower())
        self.assertIn("img_003", str(ctx.exception))

    def test_corrupt_image_blocks_submission(self):
        """Corrupt or undecodable image strictly blocks submission."""
        # Overwrite img_002 with garbage bytes
        with open(self.images_dir / "img_002.png", "wb") as f:
            f.write(b"NOT_A_VALID_IMAGE_FILE_DATA_GARBAGE")

        with self.assertRaises(SubmissionBlockedError) as ctx:
            self.service.audit_and_resolve_images(self.sample_ids, self.images_dir)

        self.assertIn("corrupt", str(ctx.exception).lower())

    def test_competition_batch_submission_generation_and_validation(self):
        """Generates compliant submission.csv, sidecar metadata, and passes validation."""
        sub_path, sidecar_path, meta_path = self.service.generate_batch_submission(
            sample_csv_path=self.sample_csv_path,
            images_dir=self.images_dir,
            output_dir=self.output_dir,
            mode="competition",
        )

        self.assertTrue(sub_path.exists())
        self.assertTrue(sidecar_path.exists())
        self.assertTrue(meta_path.exists())

        # Validate rows and formatting
        with open(sub_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
            headers = reader[0]
            rows = reader[1:]

        self.assertEqual(headers, ["id_code", "diagnosis"])
        self.assertEqual(len(rows), len(self.sample_ids))

        # Check row-by-row order and integer diagnoses
        for i, row in enumerate(rows):
            self.assertEqual(row[0], self.sample_ids[i])
            diag = int(row[1])
            self.assertIn(diag, {0, 1, 2, 3, 4})

        # Run standalone validation
        is_valid, issues = self.service.validate_submission(sub_path, self.sample_csv_path)
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)

        # Check sidecar content
        with open(sidecar_path, "r") as f:
            sidecar = json.load(f)
        self.assertEqual(sidecar["total_images"], 5)
        self.assertEqual(len(sidecar["records"]), 5)

        # Check metadata content
        with open(meta_path, "r") as f:
            meta = json.load(f)
        self.assertIn("submission_csv_hash", meta)
        self.assertEqual(meta["total_rows"], 5)

    def test_validation_detects_extra_index_column(self):
        """Validator rejects candidate submission containing extra index column (e.g. Unnamed: 0)."""
        bad_sub = self.output_dir / "bad_index_submission.csv"
        with open(bad_sub, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Unnamed: 0", "id_code", "diagnosis"])
            for idx, img_id in enumerate(self.sample_ids):
                writer.writerow([idx, img_id, 0])

        with self.assertRaises(SubmissionValidationError) as ctx:
            self.service.validate_submission(bad_sub, self.sample_csv_path)
        self.assertIn("Header mismatch", str(ctx.exception))

    def test_validation_detects_float_diagnoses(self):
        """Validator rejects floating point diagnosis values."""
        bad_sub = self.output_dir / "float_submission.csv"
        with open(bad_sub, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id_code", "diagnosis"])
            for img_id in self.sample_ids:
                writer.writerow([img_id, "2.0"])  # Float string

        with self.assertRaises(SubmissionValidationError) as ctx:
            self.service.validate_submission(bad_sub, self.sample_csv_path)
        self.assertIn("not a clean integer", str(ctx.exception))

    def test_validation_detects_row_order_mismatch(self):
        """Validator rejects scrambled row ordering."""
        bad_sub = self.output_dir / "scrambled_submission.csv"
        scrambled_ids = list(reversed(self.sample_ids))
        with open(bad_sub, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id_code", "diagnosis"])
            for img_id in scrambled_ids:
                writer.writerow([img_id, 1])

        with self.assertRaises(SubmissionValidationError) as ctx:
            self.service.validate_submission(bad_sub, self.sample_csv_path)
        self.assertIn("ordering mismatch", str(ctx.exception).lower())

    def test_clinical_mode_abstains_on_ungradeable(self):
        """Clinical mode sets diagnosis to empty/None on ungradeable images."""
        # Create an almost blank black image that triggers 'rejected' IQA quality
        black_img_id = "img_black"
        black_img = Image.new("RGB", (64, 64), color=(0, 0, 0))
        black_img.save(self.images_dir / f"{black_img_id}.png")

        # Single image sample submission
        sample_path = self.root / "single_sample.csv"
        with open(sample_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id_code", "diagnosis"])
            writer.writerow([black_img_id, 0])

        sub_path, sidecar_path, _ = self.service.generate_batch_submission(
            sample_csv_path=sample_path,
            images_dir=self.images_dir,
            output_dir=self.output_dir,
            mode="clinical",
        )

        with open(sidecar_path, "r") as f:
            sidecar = json.load(f)
        self.assertTrue(sidecar["records"][0]["abstained_in_clinic"])
        self.assertIsNone(sidecar["records"][0]["final_diagnosis"])


if __name__ == "__main__":
    unittest.main()
