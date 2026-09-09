#!/bin/bash
# =============================================================================
# RetinaShield — Dataset Download Helper
# =============================================================================
# Downloads publicly available DR datasets for model training/validation.
#
# NOTE: You may need a Kaggle account and API key for some datasets.
#       Install: pip install kaggle
#       Setup:   Place kaggle.json in ~/.kaggle/
#
# Usage: ./scripts/download_dataset.sh [dataset_name]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data/datasets"

mkdir -p "$DATA_DIR"

echo "============================================================"
echo " RetinaShield — Dataset Download"
echo "============================================================"
echo ""

DATASET="${1:-help}"

case "$DATASET" in
    aptos)
        echo "▸ Downloading APTOS 2019 Blindness Detection dataset..."
        echo "  Source: Kaggle (requires kaggle CLI and API key)"
        echo "  Size: ~11 GB"
        echo "  Classes: 5 (No DR, Mild, Moderate, Severe, Proliferative)"
        echo ""
        command -v kaggle >/dev/null 2>&1 || { echo "ERROR: kaggle CLI not found. Install: pip install kaggle"; exit 1; }
        kaggle competitions download -c aptos2019-blindness-detection -p "$DATA_DIR/aptos2019/"
        echo "  ✓ Downloaded to $DATA_DIR/aptos2019/"
        ;;

    idrid)
        echo "▸ Downloading IDRiD dataset..."
        echo "  Source: IEEE DataPort"
        echo "  Note: Requires manual download from https://ieee-dataport.org/open-access/indian-diabetic-retinopathy-image-dataset-idrid"
        echo "  Please download and extract to: $DATA_DIR/idrid/"
        ;;

    messidor)
        echo "▸ Downloading Messidor-2 dataset..."
        echo "  Source: ADCIS"
        echo "  Note: Requires registration at https://www.adcis.net/en/third-party/messidor2/"
        echo "  Please download and extract to: $DATA_DIR/messidor2/"
        ;;

    synthetic)
        echo "▸ Generating synthetic test images..."
        cd "$PROJECT_DIR"
        python3 scripts/generate_test_images.py --count 20 --output "$DATA_DIR/synthetic/" --size 512
        echo "  ✓ Generated to $DATA_DIR/synthetic/"
        echo "  ⚠ These are NOT real fundus images — for pipeline testing only"
        ;;

    *)
        echo "Available datasets:"
        echo ""
        echo "  aptos      - APTOS 2019 (Kaggle, 3,662 images, 5-class)"
        echo "  idrid       - IDRiD (IEEE DataPort, 516 images, pixel-level annotations)"
        echo "  messidor    - Messidor-2 (ADCIS, 1,748 images)"
        echo "  synthetic   - Generate synthetic test images (no download needed)"
        echo ""
        echo "Usage: $0 <dataset_name>"
        ;;
esac

echo ""
echo "============================================================"
