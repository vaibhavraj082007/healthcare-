#!/usr/bin/env python3
"""
RetinaShield — Structure Dataset Adapter CLI

Imports and audits structure-annotation benchmarks (DRIVE, REFUGE, IDRiD, STARE).
Maps raw datasets into a unified JSON manifest format containing:
  - image_path, image_id, dimensions
  - fov_mask_path
  - optic_disc_mask_path, optic_disc_center, optic_disc_radius
  - fovea_center (x, y)
  - vessel_mask_path
  - license attribution

IMPORTANT: Decoupled from diagnosis CSVs — does not assume DR diagnosis CSVs
contain segmentation labels.
"""

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class StructureDatasetAdapter:
    """Standardizes structure datasets into RetinaShield manifest schema."""

    @staticmethod
    def import_drive(root_dir: Path, split: str = "all") -> List[Dict[str, Any]]:
        """Import DRIVE vessel and FOV dataset."""
        records = []
        splits = ["training", "test"] if split == "all" else [split]
        license_text = "DRIVE Research License — Open access for non-commercial research (Niemeijer et al., 2004)"

        for s in splits:
            folder = root_dir / s
            if not folder.exists():
                continue

            img_dir = folder / "images"
            vessel_dir = folder / "1st_manual"
            mask_dir = folder / "mask"

            if not img_dir.exists():
                continue

            for img_path in sorted(img_dir.glob("*.*")):
                if img_path.suffix.lower() not in [".tif", ".png", ".jpg"]:
                    continue

                stem = img_path.stem
                id_prefix = stem.split("_")[0]

                # Locate 1st manual vessel annotation
                vessel_mask = ""
                if vessel_dir.exists():
                    v_matches = list(vessel_dir.glob(f"{id_prefix}_*manual1*.*"))
                    if v_matches:
                        vessel_mask = str(v_matches[0].resolve())

                # Locate FOV mask
                fov_mask = ""
                if mask_dir.exists():
                    m_matches = list(mask_dir.glob(f"{id_prefix}_*mask*.*"))
                    if m_matches:
                        fov_mask = str(m_matches[0].resolve())

                records.append({
                    "dataset_name": "DRIVE",
                    "image_id": stem,
                    "image_path": str(img_path.resolve()),
                    "fov_mask_path": fov_mask,
                    "optic_disc_mask_path": "",
                    "optic_disc_center": None,
                    "optic_disc_radius": None,
                    "fovea_center": None,
                    "vessel_mask_path": vessel_mask,
                    "observer_id": "1st_manual",
                    "split": s,
                    "license": license_text,
                })

        return records

    @staticmethod
    def import_refuge(root_dir: Path, split: str = "all") -> List[Dict[str, Any]]:
        """Import REFUGE dataset (Optic Disc/Cup masks & Fovea coordinates)."""
        records = []
        license_text = "CC BY-NC-SA 4.0 — REFUGE Challenge (Orlando et al., 2020)"

        img_dir = root_dir / "images"
        if not img_dir.exists():
            img_dir = root_dir

        mask_dir = root_dir / "Disc_Cup_Masks"
        if not mask_dir.exists():
            mask_dir = root_dir / "masks"

        # Check for Fovea coordinate CSV
        fovea_coords: Dict[str, List[float]] = {}
        csv_candidates = [root_dir / "Fovea_Locations.csv", root_dir / "fovea_locations.csv"]
        for csv_path in csv_candidates:
            if csv_path.exists():
                try:
                    with open(csv_path, mode="r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            # Search for name column
                            name_key = next((k for k in row if "name" in k.lower() or "img" in k.lower()), None)
                            x_key = next((k for k in row if "x" in k.lower()), None)
                            y_key = next((k for k in row if "y" in k.lower()), None)
                            if name_key and x_key and y_key:
                                try:
                                    fovea_coords[row[name_key].strip()] = [float(row[x_key]), float(row[y_key])]
                                except ValueError:
                                    pass
                except Exception as e:
                    logging.warning(f"Failed to parse REFUGE fovea CSV: {e}")
                break

        for img_path in sorted(img_dir.glob("*.jpg")):
            stem = img_path.stem
            od_mask = ""
            if mask_dir.exists():
                for ext in [".png", ".bmp"]:
                    cand = mask_dir / f"{stem}{ext}"
                    if cand.exists():
                        od_mask = str(cand.resolve())
                        break

            f_coord = fovea_coords.get(img_path.name) or fovea_coords.get(stem)

            records.append({
                "dataset_name": "REFUGE",
                "image_id": stem,
                "image_path": str(img_path.resolve()),
                "fov_mask_path": "",
                "optic_disc_mask_path": od_mask,
                "optic_disc_center": None,
                "optic_disc_radius": None,
                "fovea_center": f_coord,
                "vessel_mask_path": "",
                "observer_id": "REFUGE_consensus",
                "split": "train",
                "license": license_text,
            })

        return records

    @staticmethod
    def import_idrid(root_dir: Path) -> List[Dict[str, Any]]:
        """Import IDRiD structure segmentation and fovea localization dataset."""
        records = []
        license_text = "CC BY 4.0 — IDRiD (Porwal et al., 2018)"

        img_dir = root_dir / "1. Segmentation" / "a. Original Images"
        if not img_dir.exists():
            img_dir = root_dir / "Images"
        if not img_dir.exists():
            img_dir = root_dir

        od_dir = root_dir / "1. Segmentation" / "b. Optic Disc"
        if not od_dir.exists():
            od_dir = root_dir / "OpticDisc_Masks"

        fovea_csv = root_dir / "2. Fovea Center" / "IDRiD_Fovea_Center.csv"
        fovea_coords: Dict[str, List[float]] = {}
        if fovea_csv.exists():
            try:
                with open(fovea_csv, mode="r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 3:
                            try:
                                fovea_coords[row[0].strip()] = [float(row[1]), float(row[2])]
                            except ValueError:
                                pass
            except Exception as e:
                logging.warning(f"Failed to parse IDRiD fovea CSV: {e}")

        for img_path in sorted(img_dir.glob("*.jpg")):
            stem = img_path.stem
            od_mask = ""
            if od_dir.exists():
                for cand in [od_dir / f"{stem}_OD.tif", od_dir / f"{stem}.png"]:
                    if cand.exists():
                        od_mask = str(cand.resolve())
                        break

            f_coord = fovea_coords.get(img_path.name) or fovea_coords.get(stem)

            records.append({
                "dataset_name": "IDRiD",
                "image_id": stem,
                "image_path": str(img_path.resolve()),
                "fov_mask_path": "",
                "optic_disc_mask_path": od_mask,
                "optic_disc_center": None,
                "optic_disc_radius": None,
                "fovea_center": f_coord,
                "vessel_mask_path": "",
                "observer_id": "IDRiD_expert",
                "split": "train",
                "license": license_text,
            })

        return records


def main():
    parser = argparse.ArgumentParser(description="Import retinal structure benchmark datasets.")
    parser.add_argument("--dataset", required=True, choices=["DRIVE", "REFUGE", "IDRiD", "STARE"],
                        help="Dataset name to import")
    parser.add_argument("--input-dir", required=True, help="Directory containing raw dataset files")
    parser.add_argument("--output-json", required=True, help="Path to save output manifest JSON")
    parser.add_argument("--split", default="all", choices=["all", "train", "test", "training"],
                        help="Data split to import")
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_path}")

    ds = args.dataset.upper()
    if ds == "DRIVE":
        records = StructureDatasetAdapter.import_drive(input_path, args.split)
    elif ds == "REFUGE":
        records = StructureDatasetAdapter.import_refuge(input_path, args.split)
    elif ds == "IDRID":
        records = StructureDatasetAdapter.import_idrid(input_path)
    else:
        raise NotImplementedError(f"Dataset {ds} not yet supported in CLI.")

    out_file = Path(args.output_json)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    logging.info(f"Successfully processed {len(records)} structure records from {ds}.")
    logging.info(f"Exported manifest to: {out_file}")


if __name__ == "__main__":
    main()
