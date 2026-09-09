# RetinaShield — MATLAB Analysis Pipeline

> **RESEARCH SCREENING TOOL** — Not for autonomous clinical diagnosis.

## Overview

This directory contains the core MATLAB image analysis pipeline for diabetic retinopathy screening. It performs:

1. **Quality Assessment** (`quality_assessment.m`) — BRISQUE, sharpness, illumination uniformity, FOV checks
2. **Image Enhancement** (`enhance_fundus.m`) — CLAHE, green channel extraction, vessel enhancement
3. **Structure Analysis** (`segment_structures.m`) — Optic disc, macula, and vasculature segmentation
4. **DR Classification** (`classify_dr.m`) — EfficientNet-B0 severity grading (0–4)
5. **Explainability** (`generate_gradcam.m`) — Grad-CAM heatmap overlay

## Requirements

### MATLAB Installation
- **MATLAB R2023b+** (for Apple Silicon native support)
- **Image Processing Toolbox** — required for all stages
- **Deep Learning Toolbox** — required for EfficientNet-B0 classification
- **Computer Vision Toolbox** — required for BRISQUE quality metric
- **Deep Learning Toolbox Model for EfficientNet-B0** — support package

### For Python Integration
- Install MATLAB Engine for Python:
  ```bash
  cd /path/to/MATLAB/R2024a/extern/engines/python
  pip install .
  ```

## Usage

### From MATLAB
```matlab
% Add source directory to path
addpath('src');

% Run full pipeline
result = run_pipeline('path/to/fundus.jpg', './output/');

% Run individual stages
iqaResult = quality_assessment('path/to/fundus.jpg');
enhResult = enhance_fundus('path/to/fundus.jpg', './output/enhanced/');
segResult = segment_structures('path/to/fundus.jpg', './output/segments/');
clsResult = classify_dr('path/to/fundus.jpg', './models/efficientnet_b0_dr.mat');
```

### From Python (via MATLAB Engine)
```python
import matlab.engine

eng = matlab.engine.start_matlab()
eng.addpath('matlab/src', nargout=0)

result = eng.run_pipeline('path/to/fundus.jpg', './output/')
print(result)

eng.quit()
```

## Model Training

The EfficientNet-B0 model must be trained on a labelled DR dataset before it can produce real predictions. Without trained weights, `classify_dr.m` returns an `UNTRAINED` placeholder.

Recommended datasets:
- **APTOS 2019** (Kaggle) — 3,662 images, 5-class grading
- **EyePACS** — 88,702 images, 5-class grading
- **IDRiD** — 516 images with pixel-level annotations
- **Messidor-2** — 1,748 images, 4-class grading

## Testing

```matlab
cd tests
results = runtests('test_pipeline');
disp(results);
```

## Output Schema

All pipeline outputs conform to the shared `analysis_result_schema.json` in the `shared/` directory.

## Directory Structure

```
matlab/
├── src/
│   ├── quality_assessment.m    # IQA metrics
│   ├── enhance_fundus.m        # Preprocessing & enhancement
│   ├── segment_structures.m    # Retinal structure segmentation
│   ├── classify_dr.m           # EfficientNet-B0 classification
│   ├── generate_gradcam.m      # Grad-CAM explainability
│   └── run_pipeline.m          # Full pipeline orchestrator
├── models/                     # Trained weights (git-ignored)
├── tests/
│   └── test_pipeline.m         # Unit tests with synthetic images
└── README.md
```
