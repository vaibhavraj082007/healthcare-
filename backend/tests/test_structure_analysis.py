"""
RetinaShield — Unit tests for structural analysis and dataset adapters.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

# Verify OpenCV availability
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

try:
    from pydantic import BaseModel
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

from scripts.import_structure_datasets import StructureDatasetAdapter


@unittest.skipUnless(PYDANTIC_AVAILABLE, "Pydantic is required for schema tests")
class TestStructureSchemas(unittest.TestCase):
    """Test structure analysis Pydantic models."""

    def test_default_structure_analysis(self):
        from app.schemas.analysis_result import (
            FieldOfView,
            Macula,
            OpticDisc,
            StructureAnalysis,
            Vasculature,
        )
        struct_res = StructureAnalysis()
        self.assertTrue(struct_res.is_experimental)
        self.assertFalse(struct_res.optic_disc.detected)
        self.assertFalse(struct_res.macula.detected)
        self.assertFalse(struct_res.field_of_view.is_reliable)
        self.assertEqual(struct_res.optic_disc.algorithm_version, "0.2.0-classical")
        self.assertEqual(struct_res.macula.inferred_laterality, "unknown")

    def test_explicit_failure_semantics(self):
        from app.schemas.analysis_result import OpticDisc
        od = OpticDisc(
            detected=False,
            center_x=None,
            center_y=None,
            radius=None,
            confidence=0.15,
            is_reliable=False,
            failure_reason="DISC_OUTSIDE_OR_CLIPPED_BY_FOV",
        )
        self.assertFalse(od.detected)
        self.assertIsNone(od.center_x)
        self.assertFalse(od.is_reliable)
        self.assertEqual(od.failure_reason, "DISC_OUTSIDE_OR_CLIPPED_BY_FOV")


@unittest.skipUnless(OPENCV_AVAILABLE, "OpenCV is required for structure analysis")
class TestStructureFallbackLogic(unittest.TestCase):
    """Test classical structure detection algorithm logic."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="retinashield_test_"))
        self.output_dir = self.temp_dir / "out"
        self.output_dir.mkdir()

        # Create a synthetic 400x600 fundus image (Right Eye / OD)
        h, w = 400, 600
        img = np.zeros((h, w, 3), dtype=np.uint8)
        center = (300, 200)
        radius = 180
        cv2.circle(img, center, radius, (40, 80, 140), -1)  # BGR retina

        # Optic disc on nasal side (left: x=180, y=200)
        od_center = (180, 200)
        cv2.circle(img, od_center, 35, (100, 180, 230), -1)  # Bright OD

        # Add vessel-like radial lines emerging from OD
        for angle_deg in [0, 30, -30, 60, -60, 150, -150]:
            rad = np.deg2rad(angle_deg)
            ex = int(od_center[0] + 120 * np.cos(rad))
            ey = int(od_center[1] + 120 * np.sin(rad))
            cv2.line(img, od_center, (ex, ey), (15, 30, 70), 3)

        # Fovea (dark dip temporal: right of disc, x=380, y=210)
        fovea_center = (380, 210)
        cv2.circle(img, fovea_center, 18, (20, 45, 90), -1)

        self.test_img = img

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fallback_structure_analysis(self):
        if PYDANTIC_AVAILABLE:
            from app.services.matlab_bridge import matlab_bridge
            result = matlab_bridge._fallback_structure_analysis(
                self.test_img, self.output_dir, "test_fundus"
            )
            self.assertTrue(result.is_experimental)
            self.assertTrue(result.field_of_view.is_reliable)
            self.assertGreater(result.field_of_view.area_ratio, 0.30)
            self.assertTrue(result.optic_disc.detected)
            self.assertAlmostEqual(result.optic_disc.center_x, 180, delta=45)
            self.assertTrue(result.macula.detected)
            self.assertEqual(result.macula.inferred_laterality, "OD")
            # Heuristic fovea localisation on a synthetic image may err by ≤120 px (20 %)
            self.assertAlmostEqual(result.macula.center_x, 380, delta=120)
        else:
            # Test direct OpenCV segmentation logic
            gray = cv2.cvtColor(self.test_img, cv2.COLOR_BGR2GRAY)
            _, fov_thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
            fov_ratio = np.sum(fov_thresh > 0) / (gray.shape[0] * gray.shape[1])
            self.assertGreater(fov_ratio, 0.30)
            self.assertLess(fov_ratio, 0.90)


class TestStructureDatasetAdapters(unittest.TestCase):
    """Test structure benchmark dataset adapters."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="dataset_adapter_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_drive_adapter(self):
        # Create mock DRIVE structure
        drive_root = self.temp_dir / "DRIVE"
        train_img = drive_root / "training" / "images"
        train_manual = drive_root / "training" / "1st_manual"
        train_mask = drive_root / "training" / "mask"
        for d in [train_img, train_manual, train_mask]:
            d.mkdir(parents=True)

        # Mock image file, manual mask, FOV mask
        (train_img / "21_training.tif").write_bytes(b"mock_img")
        (train_manual / "21_manual1.gif").write_bytes(b"mock_vessel")
        (train_mask / "21_training_mask.gif").write_bytes(b"mock_mask")

        records = StructureDatasetAdapter.import_drive(drive_root)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["dataset_name"], "DRIVE")
        self.assertEqual(rec["image_id"], "21_training")
        self.assertTrue(rec["vessel_mask_path"].endswith("21_manual1.gif"))
        self.assertTrue(rec["fov_mask_path"].endswith("21_training_mask.gif"))
        self.assertIn("Niemeijer", rec["license"])

    def test_refuge_adapter(self):
        # Create mock REFUGE structure
        refuge_root = self.temp_dir / "REFUGE"
        img_dir = refuge_root / "images"
        mask_dir = refuge_root / "Disc_Cup_Masks"
        img_dir.mkdir(parents=True)
        mask_dir.mkdir(parents=True)

        (img_dir / "T0001.jpg").write_bytes(b"mock_jpg")
        (mask_dir / "T0001.png").write_bytes(b"mock_od_cup_mask")

        # Fovea CSV
        fovea_csv = refuge_root / "Fovea_Locations.csv"
        fovea_csv.write_text("ImgName,Fovea_X,Fovea_Y\nT0001.jpg,1250.5,1020.2\n")

        records = StructureDatasetAdapter.import_refuge(refuge_root)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["dataset_name"], "REFUGE")
        self.assertEqual(rec["image_id"], "T0001")
        self.assertTrue(rec["optic_disc_mask_path"].endswith("T0001.png"))
        self.assertEqual(rec["fovea_center"], [1250.5, 1020.2])
        self.assertIn("CC BY-NC-SA 4.0", rec["license"])

    def test_idrid_adapter(self):
        # Create mock IDRiD structure
        idrid_root = self.temp_dir / "IDRiD"
        img_dir = idrid_root / "1. Segmentation" / "a. Original Images"
        od_dir = idrid_root / "1. Segmentation" / "b. Optic Disc"
        fovea_dir = idrid_root / "2. Fovea Center"
        img_dir.mkdir(parents=True)
        od_dir.mkdir(parents=True)
        fovea_dir.mkdir(parents=True)

        (img_dir / "IDRiD_01.jpg").write_bytes(b"mock_jpg")
        (od_dir / "IDRiD_01_OD.tif").write_bytes(b"mock_od_mask")
        fovea_csv = fovea_dir / "IDRiD_Fovea_Center.csv"
        fovea_csv.write_text("IDRiD_01.jpg,2150.0,1420.0\n")

        records = StructureDatasetAdapter.import_idrid(idrid_root)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["dataset_name"], "IDRiD")
        self.assertEqual(rec["image_id"], "IDRiD_01")
        self.assertTrue(rec["optic_disc_mask_path"].endswith("IDRiD_01_OD.tif"))
        self.assertEqual(rec["fovea_center"], [2150.0, 1420.0])
        self.assertIn("CC BY 4.0", rec["license"])


if __name__ == "__main__":
    unittest.main()
