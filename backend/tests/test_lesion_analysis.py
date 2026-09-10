"""
RetinaShield — Unit tests for Lesion Analysis, IDRiD Importer, Tiled Inference, and Schemas.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

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

from scripts.import_idrid_lesions import IDRiDLesionImporter
from scripts.yolo_tiled_inference import (
    compute_iou,
    nms_merge_detections,
    generate_tiles,
    compute_approximate_extent,
    run_tiled_inference,
)
from app.services.yolo_service import YOLOService


class TestLesionSchemas(unittest.TestCase):
    """Test lesion analysis Pydantic schemas and serialization."""

    @unittest.skipUnless(PYDANTIC_AVAILABLE, "Pydantic is required for schema tests")
    def test_lesion_detection_result_unavailable_state(self):
        from app.schemas.analysis_result import (
            LesionDetectionResult,
            LesionDetection,
            LesionBBox,
            ApproximateExtent,
        )

        result = LesionDetectionResult(
            model="yolov8x-retina-tiles-v0.2.0",
            status="unavailable",
            message="Lesion detector unavailable — Trained YOLOv8 weights not found",
            detections=[],
            model_estimated_count={"microaneurysm": 0, "hemorrhage": 0, "hard_exudate": 0, "cotton_wool_spot": 0},
            model_trained=False,
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(len(result.detections), 0)
        self.assertFalse(result.model_trained)
        self.assertEqual(result.model_estimated_count["microaneurysm"], 0)

    @unittest.skipUnless(PYDANTIC_AVAILABLE, "Pydantic is required for schema tests")
    def test_lesion_detection_with_extent_and_candidate_flag(self):
        from app.schemas.analysis_result import (
            LesionDetection,
            LesionBBox,
            ApproximateExtent,
        )

        lesion = LesionDetection(
            lesion_type="microaneurysm",
            bbox=LesionBBox(x_min=100.0, y_min=150.0, x_max=120.0, y_max=170.0),
            confidence=0.88,
            approximate_extent=ApproximateExtent(
                area_pixels=400.0,
                equivalent_diameter=22.56,
                width=20.0,
                height=20.0,
            ),
            is_heuristic_candidate=False,
        )
        self.assertEqual(lesion.lesion_type, "microaneurysm")
        self.assertEqual(lesion.approximate_extent.area_pixels, 400.0)
        self.assertFalse(lesion.is_heuristic_candidate)

        cws = LesionDetection(
            lesion_type="cotton_wool_spot",
            bbox=LesionBBox(x_min=300.0, y_min=200.0, x_max=360.0, y_max=260.0),
            confidence=0.75,
            is_heuristic_candidate=True,
        )
        self.assertEqual(cws.lesion_type, "cotton_wool_spot")
        self.assertTrue(cws.is_heuristic_candidate)


import asyncio

class TestYOLOServiceSafety(unittest.TestCase):
    """Verify YOLOService safety invariants: no random boxes when weights missing."""

    def test_detector_unavailable_when_weights_missing(self):
        # Point to a guaranteed non-existent weights path
        service = YOLOService(weights_path="non_existent_weights_dir/best.pt")
        self.assertFalse(service.is_available())

        # Calling detect_lesions on a dummy image must return empty detections with unavailable status
        dummy_img = np.zeros((1000, 1000, 3), dtype=np.uint8)
        result = asyncio.run(service.detect_lesions(dummy_img))

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(len(result.detections), 0)
        self.assertFalse(result.model_trained)
        self.assertIn("unavailable", result.message.lower())
        # Model estimated counts should all be 0
        for count in result.model_estimated_count.values():
            self.assertEqual(count, 0)


@unittest.skipUnless(OPENCV_AVAILABLE, "OpenCV is required for importer and tiling tests")
class TestTiledInferenceAndNMS(unittest.TestCase):
    """Test sliding-window tiling, coordinate mapping, and NMS box merging."""

    def test_compute_iou(self):
        b1 = [0, 0, 10, 10]  # area 100
        b2 = [5, 0, 15, 10]  # area 100, intersection [5,0,10,10] = 50, union = 150
        iou = compute_iou(b1, b2)
        self.assertAlmostEqual(iou, 50.0 / 150.0, places=4)

        # Disjoint boxes
        b3 = [20, 20, 30, 30]
        self.assertEqual(compute_iou(b1, b3), 0.0)

    def test_nms_merge_detections(self):
        # Two overlapping microaneurysms
        dets = [
            {
                "lesion_type": "microaneurysm",
                "bbox": {"x_min": 100.0, "y_min": 100.0, "x_max": 120.0, "y_max": 120.0},
                "confidence": 0.90,
                "approximate_extent": {"area_pixels": 400.0, "equivalent_diameter": 22.56, "width": 20.0, "height": 20.0},
            },
            {
                "lesion_type": "microaneurysm",
                "bbox": {"x_min": 102.0, "y_min": 101.0, "x_max": 122.0, "y_max": 121.0},
                "confidence": 0.85,
                "approximate_extent": {"area_pixels": 400.0, "equivalent_diameter": 22.56, "width": 20.0, "height": 20.0},
            },
            # Non-overlapping hemorrhage
            {
                "lesion_type": "hemorrhage",
                "bbox": {"x_min": 300.0, "y_min": 300.0, "x_max": 350.0, "y_max": 350.0},
                "confidence": 0.92,
                "approximate_extent": {"area_pixels": 2500.0, "equivalent_diameter": 56.42, "width": 50.0, "height": 50.0},
            },
        ]
        merged = nms_merge_detections(dets, iou_thresh=0.30)
        self.assertEqual(len(merged), 2)
        types = [d["lesion_type"] for d in merged]
        self.assertIn("microaneurysm", types)
        self.assertIn("hemorrhage", types)
        # Highest confidence detection should be retained for microaneurysm
        ma_det = next(d for d in merged if d["lesion_type"] == "microaneurysm")
        self.assertEqual(ma_det["confidence"], 0.90)

    def test_generate_tiles(self):
        tiles = generate_tiles(img_w=1000, img_h=800, tile_size=640, overlap=0.20)
        self.assertGreater(len(tiles), 1)
        for x1, y1, x2, y2 in tiles:
            self.assertGreaterEqual(x1, 0)
            self.assertGreaterEqual(y1, 0)
            self.assertLessEqual(x2, 1000)
            self.assertLessEqual(y2, 800)
            self.assertEqual(x2 - x1, 640)
            self.assertEqual(y2 - y1, 640)


@unittest.skipUnless(OPENCV_AVAILABLE, "OpenCV is required for IDRiD importer tests")
class TestIDRiDLesionImporter(unittest.TestCase):
    """Test IDRiD mask-to-YOLO dataset import, train/val/test splits, and extent calculation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.temp_dir, "raw_idrid")
        self.out_dir = os.path.join(self.temp_dir, "yolo_dataset")

        # Create mock IDRiD structure:
        # 1. Original Images
        img_dir = os.path.join(self.raw_dir, "A. Segmentation", "1. Original Images", "a. Training Set")
        os.makedirs(img_dir, exist_ok=True)
        # Create 2 mock training images
        for name in ["IDRiD_01.jpg", "IDRiD_02.jpg"]:
            dummy = np.zeros((800, 1000, 3), dtype=np.uint8)
            cv2.imwrite(os.path.join(img_dir, name), dummy)

        # 2. All Groundtruths
        gt_dir = os.path.join(self.raw_dir, "A. Segmentation", "2. All Segmentation Groundtruths", "a. Training Set")
        ma_dir = os.path.join(gt_dir, "1. Microaneurysms")
        he_dir = os.path.join(gt_dir, "2. Haemorrhages")
        ex_dir = os.path.join(gt_dir, "3. Hard Exudates")
        se_dir = os.path.join(gt_dir, "4. Soft Exudates")
        for d in [ma_dir, he_dir, ex_dir, se_dir]:
            os.makedirs(d, exist_ok=True)

        # Create synthetic masks for IDRiD_01
        # MA: circle at (200, 200) with r=5
        ma_mask = np.zeros((800, 1000), dtype=np.uint8)
        cv2.circle(ma_mask, (200, 200), 5, 255, -1)
        # Also add a 1-pixel noise to test noise filter
        ma_mask[50, 50] = 255
        cv2.imwrite(os.path.join(ma_dir, "IDRiD_01_MA.tif"), ma_mask)

        # HE: ellipse at (400, 400)
        he_mask = np.zeros((800, 1000), dtype=np.uint8)
        cv2.ellipse(he_mask, (400, 400), (30, 15), 0, 0, 360, 255, -1)
        cv2.imwrite(os.path.join(he_dir, "IDRiD_01_HE.tif"), he_mask)

        # EX: rectangle at (600, 300)
        ex_mask = np.zeros((800, 1000), dtype=np.uint8)
        cv2.rectangle(ex_mask, (600, 300), (630, 340), 255, -1)
        cv2.imwrite(os.path.join(ex_dir, "IDRiD_01_EX.tif"), ex_mask)

        # SE (cotton-wool spot): rectangle at (700, 500)
        se_mask = np.zeros((800, 1000), dtype=np.uint8)
        cv2.rectangle(se_mask, (700, 500), (750, 550), 255, -1)
        cv2.imwrite(os.path.join(se_dir, "IDRiD_01_SE.tif"), se_mask)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_idrid_import_and_tiling(self):
        importer = IDRiDLesionImporter(
            root_dir=self.raw_dir,
            output_dir=self.out_dir,
        )
        report = importer.process(
            tile_size=640,
            overlap=0.20,
        )

        self.assertEqual(report["total_images"], 2)
        total_lesions = sum(report["lesion_counts"].values())
        self.assertGreater(total_lesions, 0)

        # Verify output directory structure
        for split in ["train", "val", "test"]:
            self.assertTrue(os.path.exists(os.path.join(self.out_dir, "images", split)))
            self.assertTrue(os.path.exists(os.path.join(self.out_dir, "labels", split)))

        # Verify dataset.yaml
        yaml_path = os.path.join(self.out_dir, "dataset.yaml")
        self.assertTrue(os.path.exists(yaml_path))

        # Verify manifest json
        manifest_path = os.path.join(self.out_dir, "lesion_manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r") as f:
            manifest_data = json.load(f)

        self.assertEqual(manifest_data["dataset_name"], "IDRiD_Lesion_Segmentation")
        self.assertEqual(manifest_data["license"], "CC BY 4.0")

        # Verify that IDRiD_01 has extracted lesions with extent
        idrid_01_rec = next((r for r in manifest_data["records"] if r["image_id"] == "IDRiD_01"), None)
        self.assertIsNotNone(idrid_01_rec)
        extracted_types = {les["lesion_type"] for les in idrid_01_rec["detections"]}
        self.assertIn("microaneurysm", extracted_types)
        self.assertIn("hemorrhage", extracted_types)
        self.assertIn("hard_exudate", extracted_types)
        self.assertIn("soft_exudate", extracted_types)

        # Verify extent metrics
        for les in idrid_01_rec["detections"]:
            ext = les["approximate_extent"]
            self.assertGreater(ext["area_pixels"], 0)
            self.assertGreater(ext["equivalent_diameter"], 0)
            self.assertGreater(ext["width"], 0)
            self.assertGreater(ext["height"], 0)


if __name__ == "__main__":
    unittest.main()
