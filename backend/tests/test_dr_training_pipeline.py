import csv
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Detect whether a deep-learning backend is available at collection time
try:
    import torch  # noqa: F401
    _DL_BACKEND_AVAILABLE = True
except ImportError:
    try:
        import tensorflow  # noqa: F401
        _DL_BACKEND_AVAILABLE = True
    except ImportError:
        _DL_BACKEND_AVAILABLE = False

from scripts.train_dr_classifier import (
    CLASS_ORDER,
    NUM_CLASSES,
    compute_class_weights,
    compute_file_sha256,
    resolve_columns_from_record,
    write_manifest_csv,
    DRClassifierTrainer,
)


class TestDRTrainingPipeline(unittest.TestCase):
    """Test DR classification training orchestration, manifest validation, and safety invariants."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.temp_dir, "dataset")
        self.splits_dir = os.path.join(self.data_dir, "splits")
        self.output_dir = os.path.join(self.temp_dir, "models")

        os.makedirs(self.splits_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # Create mock train_manifest.csv and dev_manifest.csv
        # 5-class distribution
        train_rows = [
            {"id_code": f"train_{i:03d}", "diagnosis": str(i % 5)}
            for i in range(25)
        ]
        dev_rows = [
            {"id_code": f"dev_{i:03d}", "diagnosis": str(i % 5)}
            for i in range(10)
        ]

        self.train_csv = os.path.join(self.splits_dir, "train_manifest.csv")
        self.dev_csv = os.path.join(self.splits_dir, "dev_manifest.csv")

        write_manifest_csv(self.train_csv, train_rows)
        write_manifest_csv(self.dev_csv, dev_rows)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_class_mapping_invariant(self):
        """Verify explicit 5-class ICDR severity scale."""
        self.assertEqual(NUM_CLASSES, 5)
        self.assertEqual(CLASS_ORDER[0], "No DR")
        self.assertEqual(CLASS_ORDER[1], "Mild")
        self.assertEqual(CLASS_ORDER[2], "Moderate")
        self.assertEqual(CLASS_ORDER[3], "Severe")
        self.assertEqual(CLASS_ORDER[4], "Proliferative DR")

    def test_manifest_sha256_computation(self):
        """Verify reproducible SHA-256 calculation on manifest files."""
        hash_val = compute_file_sha256(self.train_csv)
        self.assertEqual(len(hash_val), 64)
        # Verify idempotency
        self.assertEqual(hash_val, compute_file_sha256(self.train_csv))

    def test_class_weights_imbalance_handling(self):
        """Verify inverse-frequency class weights computation on imbalanced splits."""
        # 10 samples of class 0, 1 sample of class 4
        imbalanced = [0] * 10 + [1] * 5 + [2] * 3 + [3] * 2 + [4] * 1
        weights = compute_class_weights(imbalanced, num_classes=5)
        self.assertEqual(len(weights), 5)
        # Class 4 (rarest) must have highest weight, Class 0 (most common) lowest
        self.assertGreater(weights[4], weights[0])
        self.assertGreater(weights[3], weights[0])

    def test_smoke_mode_safety_guarantees(self):
        """
        Verify that Smoke Mode explicitly flags the model as untrained/smoke-run,
        never masquerading as a trained DR model.
        """
        trainer = DRClassifierTrainer(
            data_dir=self.data_dir,
            splits_dir=self.splits_dir,
            output_dir=self.output_dir,
            smoke_mode=True,
            seed=42,
        )
        meta = trainer.run_training()

        self.assertTrue(meta["is_smoke_run"])
        self.assertFalse(meta["model_trained"])
        self.assertIn("SMOKE_TEST", meta["status"])
        self.assertEqual(meta["class_order"], CLASS_ORDER)
        self.assertIn("RESEARCH SCREENING ONLY", meta["disclaimer"])
        self.assertIn("train_manifest", meta["manifest_hashes"])
        self.assertEqual(len(meta["manifest_hashes"]["train_manifest"]), 64)

    @unittest.skipUnless(_DL_BACKEND_AVAILABLE,
                         "Skipped: no deep-learning backend (torch/tensorflow) installed")
    def test_full_training_metadata_bundle(self):
        """Verify metadata bundle exported during full training."""
        trainer = DRClassifierTrainer(
            data_dir=self.data_dir,
            splits_dir=self.splits_dir,
            output_dir=self.output_dir,
            smoke_mode=False,
            input_size=(384, 384),
            seed=42,
            max_epochs=10,
        )
        meta = trainer.run_training()

        self.assertFalse(meta["is_smoke_run"])
        self.assertTrue(meta["model_trained"])
        self.assertEqual(meta["status"], "TRAINED_CONVERGED")
        self.assertEqual(meta["input_size"], [384, 384, 3])
        self.assertEqual(meta["preprocessing_version"], "1.0")
        self.assertEqual(meta["training_config"]["max_epochs"], 10)
        self.assertEqual(meta["training_config"]["seed"], 42)


if __name__ == "__main__":
    unittest.main()
