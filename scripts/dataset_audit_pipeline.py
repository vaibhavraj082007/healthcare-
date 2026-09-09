#!/usr/bin/env python3
"""
RetinaShield — Dataset Import and Audit Pipeline
Securely extracts, audits, and splits Kaggle-style DR datasets.
"""

import os
import sys
import zipfile
import hashlib
import json
import re
import argparse
import logging
from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np
from PIL import Image, ImageStat
import imagehash
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from sklearn.model_selection import GroupShuffleSplit, StratifiedShuffleSplit

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

MAX_EXTRACT_SIZE = 50 * 1024 * 1024 * 1024  # 50 GB zip bomb protection
MAX_COMPRESSION_RATIO = 100

class DatasetAuditor:
    def __init__(self, data_dir: str, output_dir: str):
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.extracted_dir = self.output_dir / "extracted"
        self.audit_dir = self.output_dir / "audit"
        self.splits_dir = self.output_dir / "splits"
        
        for d in [self.extracted_dir, self.audit_dir, self.splits_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
        self.report_data = {
            "missing_images": [],
            "corrupt_images": [],
            "exact_duplicates": [],
            "near_duplicates": [],
            "class_distribution": {},
            "dimensions": [],
            "patient_grouped": False
        }

    def _safe_extract(self, zip_path: Path, extract_to: Path):
        """Safely extract zip files preventing path traversal and zip bombs."""
        logging.info(f"Safely extracting {zip_path.name}...")
        extracted_size = 0
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for info in zf.infolist():
                # Path traversal protection
                if info.filename.startswith('/') or '..' in info.filename:
                    logging.warning(f"Skipping unsafe file path in zip: {info.filename}")
                    continue
                    
                # Zip bomb protection
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise ValueError(f"Zip bomb suspected: compression ratio {ratio} for {info.filename}")
                        
                extracted_size += info.file_size
                if extracted_size > MAX_EXTRACT_SIZE:
                    raise ValueError(f"Zip bomb suspected: total extracted size exceeded limit")
                    
                zf.extract(info, extract_to)

    def extract_archives(self):
        train_zip = self.data_dir / "train.zip"
        test_zip = self.data_dir / "test.zip"
        
        if train_zip.exists():
            self._safe_extract(train_zip, self.extracted_dir / "train")
        if test_zip.exists():
            self._safe_extract(test_zip, self.extracted_dir / "test")

    def find_columns(self, df: pd.DataFrame):
        """Inspect actual columns instead of assuming schema."""
        cols = [c.lower() for c in df.columns]
        id_col = None
        label_col = None
        
        # Heuristics for id column
        for c in df.columns:
            cl = c.lower()
            if cl in ['id_code', 'image', 'image_id', 'id', 'name']:
                id_col = c
                break
                
        # Heuristics for label column
        for c in df.columns:
            cl = c.lower()
            if cl in ['diagnosis', 'level', 'retinopathy_grade', 'class']:
                label_col = c
                break
                
        return id_col, label_col

    def get_patient_id(self, image_id: str):
        """Try to group by patient if identifiers exist (e.g. 10_left -> 10)."""
        match = re.search(r'^(.*)_(left|right)$', image_id, re.IGNORECASE)
        if match:
            return match.group(1)
        return image_id  # Fallback to image_id if no obvious grouping

    def audit_images(self, df: pd.DataFrame, id_col: str, img_dir: Path):
        logging.info("Auditing images (corruption, duplicates, hashes)...")
        
        hashes = defaultdict(list)
        phashes = []
        dimensions = []
        valid_rows = []
        
        for idx, row in tqdm(df.iterrows(), total=len(df)):
            img_id = str(row[id_col])
            
            # Find the actual image file (might be .jpg, .jpeg, .png, .tif)
            found_path = None
            for ext in ['.jpg', '.jpeg', '.png', '.tif', '.tiff']:
                p = img_dir / f"{img_id}{ext}"
                if p.exists():
                    found_path = p
                    break
                    
            if not found_path:
                self.report_data["missing_images"].append(img_id)
                continue
                
            try:
                with Image.open(found_path) as img:
                    img.verify()  # Check corruption
                    
                # Re-open to process
                with Image.open(found_path) as img:
                    # Dimensions
                    width, height = img.size
                    dimensions.append({"id": img_id, "width": width, "height": height})
                    
                    # Exact Hash (MD5)
                    img_data = found_path.read_bytes()
                    md5_hash = hashlib.md5(img_data).hexdigest()
                    hashes[md5_hash].append(img_id)
                    
                    # Perceptual Hash
                    ph = imagehash.phash(img)
                    phashes.append({"id": img_id, "hash": ph})
                    
                valid_rows.append(row)
                
            except Exception as e:
                self.report_data["corrupt_images"].append({"id": img_id, "error": str(e)})

        # Process duplicates
        for md5, ids in hashes.items():
            if len(ids) > 1:
                self.report_data["exact_duplicates"].append(ids)

        # Process near-duplicates (pHash difference <= 2)
        # O(N^2) comparison is slow, but acceptable for typical DR datasets (tens of thousands)
        # We optimize by only comparing if not already clustered
        processed = set()
        for i in range(len(phashes)):
            if phashes[i]["id"] in processed: continue
            cluster = [phashes[i]["id"]]
            for j in range(i + 1, len(phashes)):
                if phashes[j]["id"] not in processed and (phashes[i]["hash"] - phashes[j]["hash"]) <= 2:
                    cluster.append(phashes[j]["id"])
                    processed.add(phashes[j]["id"])
            if len(cluster) > 1:
                self.report_data["near_duplicates"].append(cluster)
                
        self.report_data["dimensions"] = dimensions
        return pd.DataFrame(valid_rows)

    def create_splits(self, df: pd.DataFrame, id_col: str, label_col: str):
        logging.info("Creating immutable data splits...")
        
        # Add patient ID column
        df['patient_id'] = df[id_col].apply(self.get_patient_id)
        
        # Check if patient grouping is actually useful
        num_patients = df['patient_id'].nunique()
        num_images = len(df)
        self.report_data["patient_grouped"] = (num_patients < num_images)
        
        # We need Train (70%), Dev (10%), Calib (10%), Eval (10%)
        # Step 1: Split Eval (10%) + Calib (10%) = 20% Held out
        # Step 2: From remaining (80%), split Dev (12.5% of 80% = 10% total) and Train (87.5% of 80% = 70% total)
        
        # If we have patient groups, we must use GroupShuffleSplit to keep eyes together
        if self.report_data["patient_grouped"]:
            gss1 = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
            train_dev_idx, heldout_idx = next(gss1.split(df, groups=df['patient_id']))
            train_dev = df.iloc[train_dev_idx].copy()
            heldout = df.iloc[heldout_idx].copy()
            
            # Split heldout into calib (50%) and eval (50%)
            gss2 = GroupShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
            calib_idx, eval_idx = next(gss2.split(heldout, groups=heldout['patient_id']))
            calib = heldout.iloc[calib_idx].copy()
            eval_set = heldout.iloc[eval_idx].copy()
            
            # Split train_dev into train (87.5%) and dev (12.5%)
            gss3 = GroupShuffleSplit(n_splits=1, test_size=0.125, random_state=42)
            train_idx, dev_idx = next(gss3.split(train_dev, groups=train_dev['patient_id']))
            train = train_dev.iloc[train_idx].copy()
            dev = train_dev.iloc[dev_idx].copy()
            
        else:
            # Fallback to StratifiedShuffleSplit
            sss1 = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
            train_dev_idx, heldout_idx = next(sss1.split(df, df[label_col]))
            train_dev = df.iloc[train_dev_idx].copy()
            heldout = df.iloc[heldout_idx].copy()
            
            sss2 = StratifiedShuffleSplit(n_splits=1, test_size=0.5, random_state=42)
            calib_idx, eval_idx = next(sss2.split(heldout, heldout[label_col]))
            calib = heldout.iloc[calib_idx].copy()
            eval_set = heldout.iloc[eval_idx].copy()
            
            sss3 = StratifiedShuffleSplit(n_splits=1, test_size=0.125, random_state=42)
            train_idx, dev_idx = next(sss3.split(train_dev, train_dev[label_col]))
            train = train_dev.iloc[train_idx].copy()
            dev = train_dev.iloc[dev_idx].copy()

        # Save manifests
        splits = {'train': train, 'dev': dev, 'calibration': calib, 'eval': eval_set}
        for name, split_df in splits.items():
            out_path = self.splits_dir / f"{name}_manifest.csv"
            split_df.to_csv(out_path, index=False)
            
            # Generate checksum for manifest
            manifest_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()
            (self.splits_dir / f"{name}_manifest.sha256").write_text(manifest_hash)
            
        return splits

    def generate_report(self, df: pd.DataFrame, label_col: str):
        logging.info("Generating audit report and plots...")
        
        class_counts = df[label_col].value_counts().to_dict()
        self.report_data["class_distribution"] = class_counts
        
        # Plot Class Distribution
        plt.figure(figsize=(10, 6))
        sns.barplot(x=list(class_counts.keys()), y=list(class_counts.values()))
        plt.title("Class Distribution")
        plt.xlabel("Diagnosis Class")
        plt.ylabel("Count")
        plt.savefig(self.audit_dir / "class_distribution.png")
        plt.close()
        
        # Plot Dimensions
        if self.report_data["dimensions"]:
            widths = [d["width"] for d in self.report_data["dimensions"]]
            heights = [d["height"] for d in self.report_data["dimensions"]]
            plt.figure(figsize=(10, 6))
            sns.scatterplot(x=widths, y=heights, alpha=0.5)
            plt.title("Image Dimensions")
            plt.xlabel("Width")
            plt.ylabel("Height")
            plt.savefig(self.audit_dir / "dimensions.png")
            plt.close()
            
        # Write Markdown Report
        report_md = f"""# Dataset Audit Report

## Summary
- **Total Valid Images**: {len(df)}
- **Missing Images**: {len(self.report_data['missing_images'])}
- **Corrupt Images**: {len(self.report_data['corrupt_images'])}
- **Exact Duplicates (MD5)**: {len(self.report_data['exact_duplicates'])} groups
- **Near Duplicates (pHash)**: {len(self.report_data['near_duplicates'])} groups
- **Patient Grouping Available**: {"Yes (Regex matched Left/Right eyes)" if self.report_data['patient_grouped'] else "No (Patient identity unavailable)"}

## Class Distribution
"""
        for cls, count in class_counts.items():
            report_md += f"- **Class {cls}**: {count} images\n"
            
        if self.report_data['exact_duplicates']:
            report_md += "\n## Sample Exact Duplicates\n"
            for dup in self.report_data['exact_duplicates'][:5]:
                report_md += f"- {dup}\n"
                
        if self.report_data['missing_images']:
            report_md += "\n## Missing Images\n"
            for m in self.report_data['missing_images'][:10]:
                report_md += f"- {m}\n"
                
        (self.audit_dir / "audit_report.md").write_text(report_md)
        (self.audit_dir / "audit_data.json").write_text(json.dumps(self.report_data, indent=2))
        
    def check_annotations(self):
        # Look for xml, json, or mask folders
        has_boxes = False
        has_masks = False
        
        for p in self.extracted_dir.rglob("*"):
            if p.suffix in ['.xml', '.json'] and p.is_file():
                has_boxes = True
            elif 'mask' in p.name.lower() and p.is_dir():
                has_masks = True
                
        logging.info(f"Annotations - Bounding Boxes: {has_boxes}, Lesion Masks: {has_masks}")
        return has_boxes, has_masks

    def run(self):
        logging.info("Starting Dataset Import and Audit Pipeline...")
        self.extract_archives()
        
        train_csv_path = self.data_dir / "train.csv"
        if not train_csv_path.exists():
            raise FileNotFoundError("train.csv is missing from dataset directory.")
            
        # Read as strings to preserve identifiers
        df = pd.read_csv(train_csv_path, dtype=str)
        id_col, label_col = self.find_columns(df)
        
        if not id_col or not label_col:
            raise ValueError(f"Could not automatically detect 'id' and 'label' columns. Found: {df.columns.tolist()}")
            
        logging.info(f"Detected Identifier Column: '{id_col}', Label Column: '{label_col}'")
        
        # We only use train.csv for labels. Ignoring test.csv/sample_submission.csv for labels.
        # Check actual files
        train_img_dir = self.extracted_dir / "train"
        if not train_img_dir.exists():
            # Sometimes unzipping train.zip creates a folder, sometimes it doesn't.
            # Try to find where images are.
            if list(self.extracted_dir.glob("*.jpeg")) or list(self.extracted_dir.glob("*.png")):
                train_img_dir = self.extracted_dir
            elif (self.extracted_dir / "train_images").exists():
                train_img_dir = self.extracted_dir / "train_images"
            else:
                raise FileNotFoundError("Could not locate extracted training images directory.")
                
        valid_df = self.audit_images(df, id_col, train_img_dir)
        
        self.create_splits(valid_df, id_col, label_col)
        self.generate_report(valid_df, label_col)
        self.check_annotations()
        
        logging.info("Pipeline completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset Import and Audit Pipeline")
    parser.add_argument("--data-dir", required=True, help="Directory containing train.csv, train.zip, etc.")
    parser.add_argument("--output-dir", required=True, help="Directory to store extracted files, splits, and audit report.")
    
    args = parser.parse_args()
    auditor = DatasetAuditor(args.data_dir, args.output_dir)
    auditor.run()
