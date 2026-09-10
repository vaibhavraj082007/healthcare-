#!/usr/bin/env python3
"""
RetinaShield — Batch Prediction & Submission CLI

Generates competition and clinical predictions strictly conforming to sample_submission.csv:
  - Preserves exact header names, identifier ordering, and row counts
  - Rejects missing/undecodable images (zero label invention)
  - Separates competition mode (predicts all + exports sidecar) from clinical mode (abstains on ungradeables)
  - Generates submission_metadata.json with SHA-256 reproducibility hashes
  - Validates submission formatting with '--validate'

Usage:
  # Generate submission:
  python3 scripts/batch_predict_submission.py \
      --sample-submission data/sample_submission.csv \
      --images-dir data/test_images/ \
      --output-dir submissions/

  # Validate existing submission:
  python3 scripts/batch_predict_submission.py \
      --validate submissions/submission.csv \
      --sample-submission data/sample_submission.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure backend is in python path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.batch_prediction_service import (
    batch_prediction_service,
    SubmissionBlockedError,
    SubmissionValidationError,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="RetinaShield Batch Prediction & Submission Tool")
    parser.add_argument("--sample-submission", type=str, required=True, help="Path to sample_submission.csv")
    parser.add_argument("--images-dir", type=str, default=None, help="Directory containing test images")
    parser.add_argument("--test-csv", type=str, default=None, help="Optional path to test.csv")
    parser.add_argument("--model-path", type=str, default=None, help="Path to frozen trained model weights")
    parser.add_argument("--output-dir", type=str, default="submissions", help="Directory for output submission files")
    parser.add_argument("--mode", choices=["competition", "clinical"], default="competition", help="Prediction mode")
    parser.add_argument("--seed", type=int, default=42, help="Reproducibility seed")
    parser.add_argument("--validate", type=str, default=None, help="Validate an existing submission.csv against sample_submission.csv")

    args = parser.parse_args()

    # Mode 1: Validation only
    if args.validate:
        logging.info("=" * 60)
        logging.info(" RetinaShield — Submission Validation")
        logging.info("=" * 60)
        logging.info(f" Validating submission:   {args.validate}")
        logging.info(f" Against sample template: {args.sample_submission}")
        try:
            batch_prediction_service.validate_submission(args.validate, args.sample_submission)
            print("\n✅ VALIDATION SUCCESSFUL: submission.csv is 100% compliant with competition requirements.")
            sys.exit(0)
        except SubmissionValidationError as e:
            print(f"\n❌ {e}")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Unexpected error during validation: {e}")
            sys.exit(1)

    # Mode 2: Batch Prediction Generation
    if not args.images_dir:
        parser.error("--images-dir is required when generating predictions")

    logging.info("=" * 60)
    logging.info(" RetinaShield — Batch Prediction & Submission Generation")
    logging.info("=" * 60)
    logging.info(f" Mode:              {args.mode.upper()}")
    logging.info(f" Sample template:   {args.sample_submission}")
    logging.info(f" Images directory:  {args.images_dir}")
    logging.info(f" Output directory:  {args.output_dir}")

    try:
        sub_path, sidecar_path, meta_path = batch_prediction_service.generate_batch_submission(
            sample_csv_path=args.sample_submission,
            images_dir=args.images_dir,
            output_dir=args.output_dir,
            test_csv_path=args.test_csv,
            model_path=args.model_path,
            mode=args.mode,
            seed=args.seed,
        )

        logging.info("=" * 60)
        logging.info(" ✓ Batch Prediction Completed Successfully")
        logging.info(f"   Submission CSV:  {sub_path}")
        logging.info(f"   Quality Sidecar: {sidecar_path}")
        logging.info(f"   Reproducibility: {meta_path}")
        logging.info("=" * 60)

    except SubmissionBlockedError as e:
        logging.error(f"\n❌ {e}")
        sys.exit(2)
    except Exception as e:
        logging.error(f"\n❌ Batch prediction failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
