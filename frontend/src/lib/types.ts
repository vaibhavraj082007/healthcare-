/**
 * RetinaShield — Shared TypeScript Types
 *
 * Mirrors the backend Pydantic schemas and shared/analysis_result_schema.json.
 * All analysis outputs include the mandatory research disclaimer.
 */

// ---------------------------------------------------------------------------
// Analysis Result Types
// ---------------------------------------------------------------------------

export const DISCLAIMER =
  "RESEARCH SCREENING RESULT — Not a clinical diagnosis. Must be reviewed by a qualified ophthalmologist.";

export type QualityVerdict = "good" | "acceptable" | "poor" | "rejected";
export type ReferralUrgency = "none" | "routine" | "priority" | "urgent";
export type DRGradeLabel =
  | "No DR"
  | "Mild NPDR"
  | "Moderate NPDR"
  | "Severe NPDR"
  | "Proliferative DR";
export type LesionType =
  | "microaneurysm"
  | "hemorrhage"
  | "hard_exudate"
  | "soft_exudate"
  | "neovascularization";
export type ScreeningStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "rejected";

export interface QualityAssessment {
  overall_quality: QualityVerdict;
  brisque_score: number | null;
  sharpness_score: number | null;
  illumination_uniformity: number | null;
  field_of_view_adequate: boolean | null;
  artifacts_detected: string[];
}

export interface Enhancement {
  method: string | null;
  enhanced_image_path: string | null;
  green_channel_path: string | null;
}

export interface OpticDisc {
  detected: boolean;
  center_x: number | null;
  center_y: number | null;
  radius: number | null;
  confidence: number | null;
}

export interface Macula {
  detected: boolean;
  center_x: number | null;
  center_y: number | null;
  confidence: number | null;
}

export interface Vasculature {
  segmentation_mask_path: string | null;
  vessel_density: number | null;
  tortuosity_index: number | null;
}

export interface StructureAnalysis {
  optic_disc: OpticDisc;
  macula: Macula;
  vasculature: Vasculature;
}

export interface SeverityClassification {
  model: string;
  predicted_grade: number | null;
  grade_label: string | null;
  confidence: number | null;
  class_probabilities: number[] | null;
  gradcam_heatmap_path: string | null;
  model_trained: boolean;
}

export interface LesionBBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface LesionDetection {
  lesion_type: LesionType;
  bbox: LesionBBox;
  confidence: number;
}

export interface LesionDetectionResult {
  model: string;
  detections: LesionDetection[];
  model_trained: boolean;
}

export interface ReferralRecommendation {
  urgency: ReferralUrgency;
  reason: string;
  suggested_followup_weeks: number | null;
}

export interface AnalysisResult {
  analysis_id: string;
  image_id: string | null;
  patient_id: string | null;
  facility_id: string | null;
  pipeline_version: string;
  timestamp: string;
  disclaimer: string;
  quality_assessment: QualityAssessment | null;
  enhancement: Enhancement | null;
  structure_analysis: StructureAnalysis | null;
  severity_classification: SeverityClassification | null;
  lesion_detection: LesionDetectionResult | null;
  referral_recommendation: ReferralRecommendation | null;
  processing_time_seconds: number | null;
}

// ---------------------------------------------------------------------------
// Patient Types
// ---------------------------------------------------------------------------

export interface Patient {
  id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  gender: string | null;
  phone: string | null;
  aadhaar_last4: string | null;
  diabetes_type: string | null;
  diabetes_duration_years: number | null;
  on_insulin: boolean | null;
  hba1c_latest: number | null;
  notes: string | null;
  facility_id: string | null;
  created_at: string;
  updated_at: string;
  screening_count: number;
}

export interface PatientCreate {
  first_name: string;
  last_name: string;
  date_of_birth?: string | null;
  gender?: string | null;
  phone?: string | null;
  aadhaar_last4?: string | null;
  diabetes_type?: string | null;
  diabetes_duration_years?: number | null;
  on_insulin?: boolean | null;
  hba1c_latest?: number | null;
  notes?: string | null;
  facility_id?: string | null;
}

// ---------------------------------------------------------------------------
// Screening Types
// ---------------------------------------------------------------------------

export interface Screening {
  id: string;
  patient_id: string;
  facility_id: string | null;
  screener_name: string | null;
  eye: string;
  status: ScreeningStatus;
  quality_verdict: string | null;
  dr_grade: number | null;
  dr_grade_label: string | null;
  dr_confidence: number | null;
  referral_urgency: string | null;
  model_trained: boolean;
  disclaimer: string;
  analysis_result: AnalysisResult | null;
  screened_at: string;
  analyzed_at: string | null;
  created_at: string;
  synced: boolean;
}

export interface ScreeningSummary {
  id: string;
  patient_id: string;
  patient_name: string | null;
  eye: string;
  status: ScreeningStatus;
  dr_grade: number | null;
  dr_grade_label: string | null;
  referral_urgency: string | null;
  model_trained: boolean;
  screened_at: string;
}

export interface ScreeningCreate {
  patient_id: string;
  facility_id?: string | null;
  screener_name?: string | null;
  eye: "left" | "right" | "both";
}

// ---------------------------------------------------------------------------
// Pipeline Info
// ---------------------------------------------------------------------------

export interface PipelineInfo {
  pipeline_version: string;
  matlab_mode: string;
  matlab_available: boolean;
  yolo_available: boolean;
  yolo_model_trained: boolean;
  efficientnet_model_trained: boolean;
  disclaimer: string;
}

// ---------------------------------------------------------------------------
// DR Severity Code Mapping
// ---------------------------------------------------------------------------

export interface DRSeverityCode {
  grade: number;
  label: string;
  icd10: string;
  description: string;
  referral_urgency: ReferralUrgency;
  followup_weeks: number;
  color_hex: string;
}

export const DR_SEVERITY_CODES: Record<number, DRSeverityCode> = {
  0: {
    grade: 0,
    label: "No DR",
    icd10: "E11.3x1",
    description: "No apparent diabetic retinopathy",
    referral_urgency: "none",
    followup_weeks: 52,
    color_hex: "#22c55e",
  },
  1: {
    grade: 1,
    label: "Mild NPDR",
    icd10: "E11.321",
    description: "Mild non-proliferative diabetic retinopathy",
    referral_urgency: "routine",
    followup_weeks: 26,
    color_hex: "#eab308",
  },
  2: {
    grade: 2,
    label: "Moderate NPDR",
    icd10: "E11.331",
    description: "Moderate non-proliferative diabetic retinopathy",
    referral_urgency: "priority",
    followup_weeks: 13,
    color_hex: "#f97316",
  },
  3: {
    grade: 3,
    label: "Severe NPDR",
    icd10: "E11.341",
    description: "Severe non-proliferative diabetic retinopathy",
    referral_urgency: "priority",
    followup_weeks: 4,
    color_hex: "#ef4444",
  },
  4: {
    grade: 4,
    label: "Proliferative DR",
    icd10: "E11.351",
    description: "Proliferative diabetic retinopathy",
    referral_urgency: "urgent",
    followup_weeks: 1,
    color_hex: "#dc2626",
  },
};
