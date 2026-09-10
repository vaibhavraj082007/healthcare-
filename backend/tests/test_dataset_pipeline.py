import os
import sys
import zipfile
from pathlib import Path
from PIL import Image
import numpy as np

try:
    import pytest
    import pandas as pd
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    import unittest
    raise unittest.SkipTest("pytest and pandas required for test_dataset_pipeline")

# Add scripts directory to path to import the module
scripts_dir = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.append(str(scripts_dir))

from dataset_audit_pipeline import DatasetAuditor, MAX_COMPRESSION_RATIO

@pytest.fixture
def dummy_dataset_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Create dummy train.csv
    train_csv = data_dir / "train.csv"
    
    # Needs enough patients (groups) to survive train (70), dev (10), calib (10), eval (10) split
    # Let's add 10 patients
    id_codes = []
    diagnoses = []
    for i in range(10, 20):
        id_codes.extend([f"{i}_left", f"{i}_right"])
        diagnoses.extend([str(i % 5), str(i % 5)])
        
    df = pd.DataFrame({
        "id_code": id_codes,
        "diagnosis": diagnoses
    })
    df.to_csv(train_csv, index=False)
    
    # Create dummy images and zip
    train_zip = data_dir / "train.zip"
    img_dir = tmp_path / "img_temp"
    img_dir.mkdir()
    
    with zipfile.ZipFile(train_zip, 'w') as zf:
        for idx, row in df.iterrows():
            img_path = img_dir / f"{row['id_code']}.png"
            img = Image.new('RGB', (100, 100), color=(idx*10, idx*10, idx*10))
            img.save(img_path)
            zf.write(img_path, arcname=f"{row['id_code']}.png")
            
    # Create a duplicate image for testing
    dup_path = img_dir / "14_right.png"
    zf_dup = zipfile.ZipFile(data_dir / "dup.zip", 'w')
    zf_dup.write(dup_path, arcname="10_left_dup.png")
    zf_dup.close()

    return data_dir

@pytest.fixture
def auditor(tmp_path, dummy_dataset_dir):
    out_dir = tmp_path / "out"
    return DatasetAuditor(str(dummy_dataset_dir), str(out_dir))

def test_find_columns(auditor):
    df = pd.DataFrame({"image_id": ["1"], "retinopathy_grade": ["0"]})
    id_col, label_col = auditor.find_columns(df)
    assert id_col == "image_id"
    assert label_col == "retinopathy_grade"

def test_patient_id_grouping(auditor):
    assert auditor.get_patient_id("10_left") == "10"
    assert auditor.get_patient_id("1234_right") == "1234"
    assert auditor.get_patient_id("abc_left") == "abc"
    assert auditor.get_patient_id("abc") == "abc"

def test_safe_extract(auditor, dummy_dataset_dir):
    out_ext = auditor.extracted_dir / "train"
    auditor._safe_extract(dummy_dataset_dir / "train.zip", out_ext)
    assert (out_ext / "10_left.png").exists()

def test_zip_bomb_protection(auditor, dummy_dataset_dir):
    bomb_zip = dummy_dataset_dir / "bomb.zip"
    
    # Create a fake zip bomb (high compression ratio)
    with zipfile.ZipFile(bomb_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.txt", b"A" * 1024 * 1024) # 1MB of A's compresses very well
        
    with pytest.raises(ValueError, match="Zip bomb suspected"):
        auditor._safe_extract(bomb_zip, auditor.extracted_dir / "bomb")

def test_pipeline_execution(auditor):
    auditor.run()
    
    # Check outputs
    assert (auditor.audit_dir / "audit_report.md").exists()
    assert (auditor.splits_dir / "train_manifest.csv").exists()
    assert (auditor.splits_dir / "dev_manifest.csv").exists()
    assert (auditor.splits_dir / "calibration_manifest.csv").exists()
    assert (auditor.splits_dir / "eval_manifest.csv").exists()
    
    # Check that patient 10 is grouped together (either all in train, dev, eval, or calib)
    # We load all splits to find patient 10
    splits = ["train", "dev", "calibration", "eval"]
    patient_10_found_in = []
    
    for split in splits:
        df = pd.read_csv(auditor.splits_dir / f"{split}_manifest.csv", dtype=str)
        if "10" in df['patient_id'].values:
            patient_10_found_in.append(split)
            # Ensure BOTH eyes are in the same split
            assert len(df[df['patient_id'] == '10']) == 2
            
    # Patient 10 should only be in one split
    assert len(patient_10_found_in) == 1
