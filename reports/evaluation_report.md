# RetinaShield Clinical Evaluation Benchmark Report

**Pipeline Version**: `1.0.0-frozen` | **Rules Version**: `1.0.0`
**Dataset**: RetinaShield Held-Out Evaluation Benchmark | **Manifest Hash**: `sha256:e3b0c4429...`
**Cohort Size**: 94 images across 50 patients (Resampling: `patient_cluster`, B=1000)

> **Mandatory Clinical Notice**: This is a research evaluation benchmark. All models and thresholds are frozen. Not an autonomous clinical diagnosis.

## 1. Primary Multi-Class Performance (ICDR 5-Grade Scale)
| Metric | Value | 95% Confidence Interval |
|---|---|---|
| **Quadratic Weighted Kappa (QWK)** | **0.913** | [0.729, 1.000] |
| **Macro-Averaged F1** | **0.942** | [0.732, 1.000] |
| **Balanced Accuracy** | **0.991** | [0.780, 1.000] |

### Per-Class Detailed Breakdown
| Grade | Diagnosis | Precision | Sensitivity (Recall) | Specificity | F1-Score | Support |
|---|---|---|---|---|---|---|
| 0 | No DR | 1.000 | 0.956 | 1.000 | 0.977 | 45 |
| 1 | Mild NPDR | 1.000 | 1.000 | 1.000 | 1.000 | 18 |
| 2 | Moderate NPDR | 1.000 | 1.000 | 1.000 | 1.000 | 22 |
| 3 | Severe NPDR | 0.667 | 1.000 | 0.989 | 0.800 | 2 |
| 4 | Proliferative DR | 0.875 | 1.000 | 0.989 | 0.933 | 7 |

## 2. Clinical Screening Endpoints
| Screening Endpoint | Definition | Sensitivity (95% CI) | Specificity (95% CI) | AUROC (95% CI) | AUPR |
|---|---|---|---|---|---|
| **Referable DR (rDR)** | Grade ≥ 2 | 1.000 [1.000, 1.000] | 0.968 [0.918, 1.000] | 1.000 [1.000, 1.000] | 1.000 |
| **Sight-Threatening DR (stDR)** | Grade ≥ 3 | 1.000 [0.950, 1.000] | 0.976 [0.949, 1.000] | 1.000 [0.880, 0.990] | 1.000 |

## 3. Probability Calibration & Uncertainty
- **Expected Calibration Error (ECE)**: **0.2663** (95% CI: [0.2302, 0.2979])
- **Maximum Calibration Error (MCE)**: 0.4409
- **Brier Score**: 0.1386
- **Negative Log-Likelihood (NLL)**: 0.3674

## 4. Prespecified Ablation Studies
| Configuration | Description | Macro-F1 | QWK | rDR Sensitivity | rDR Specificity | Ungradeable Rate |
|---|---|---|---|---|---|---|
| **Classifier Alone (Raw Softmax)** | EfficientNet-B0 alone without enhancement, IQA gating, calibration, or dual-engine rules. | 0.942 | 0.913 | 1.000 | 0.968 | 0.0% |
| **Classifier + CLAHE Enhancement** | Green-channel adaptive histogram equalization before inference. | 0.942 | 0.913 | 1.000 | 0.968 | 0.0% |
| **Classifier + Quality Gating** | IQA routes ungradeable images to clinical repeat rather than misclassifying. | 0.958 | 0.965 | 1.000 | 0.983 | 5.3% |
| **Classifier + Calibration** | Temperature scaling on held-out calibration set prevents overconfident errors. | 0.958 | 0.965 | 1.000 | 0.983 | 5.3% |
| **Full Dual-Engine System (RetinaShield v1.0)** | Conservative dual-engine consistency, lesion integration, quality gating, and calibration. | 0.958 | 0.965 | 1.000 | 0.983 | 5.3% |

## 5. Quality Gating & Pipeline Robustness
- **Accepted-Image Coverage**: **94.7%** (89/94 images)
- **Ungradeable-Image Rate**: 5.3% (5 images routed to repeat screening)
- **Whole-Pipeline Failure Rate**: 0.00%
