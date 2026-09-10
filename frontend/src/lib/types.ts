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
  | "cotton_wool_spot"
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

export interface FieldOfView {
  mask_path?: string | null;
  bounding_box?: number[] | null;
  center_x?: number | null;
  center_y?: number | null;
  radius?: number | null;
  area_pixels?: number | null;
  area_ratio?: number | null;
  is_reliable: boolean;
  failure_reason?: string;
  algorithm_version?: string;
}

export interface OpticDisc {
  detected: boolean;
  center_x: number | null;
  center_y: number | null;
  radius: number | null;
  mask_path?: string | null;
  confidence: number | null;
  is_reliable?: boolean;
  failure_reason?: string;
  algorithm_version?: string;
}

export interface Macula {
  detected: boolean;
  center_x: number | null;
  center_y: number | null;
  radius?: number | null;
  confidence: number | null;
  is_reliable?: boolean;
  failure_reason?: string;
  inferred_laterality?: "OD" | "OS" | "unknown";
  algorithm_version?: string;
}

export interface Vasculature {
  segmentation_mask_path?: string | null;
  vessel_density: number | null;
  tortuosity_index: number | null;
  caliber_proxy?: number | null;
  confidence?: number | null;
  is_reliable?: boolean;
  failure_reason?: string;
  algorithm_version?: string;
}

export interface StructureAnalysis {
  is_experimental?: boolean;
  field_of_view?: FieldOfView | null;
  optic_disc: OpticDisc;
  macula: Macula;
  fovea?: Macula | null;
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

export interface PreprocessingTransform {
  original_size?: [number, number] | null;
  model_input_size?: [number, number] | null;
  scale_factor_h?: number | null;
  scale_factor_w?: number | null;
  crop_box?: number[] | null;
  pad_offsets?: number[] | null;
}

export interface GradCAMExplanation {
  status: "available" | "unavailable" | "error";
  reason?: string;
  gradcam_heatmap_path?: string | null;
  gradcam_overlay_path?: string | null;
  gradcam_raw_path?: string | null;
  target_layer?: string | null;
  target_class?: string | null;
  predicted_class?: string | null;
  preprocessing_transform?: PreprocessingTransform | null;
  algorithm_version: string;
  disclaimer: string;
  pointing_game_hit?: boolean | null;
  expert_iou?: number | null;
  energy_pointing_game?: number | null;
}

export interface ApproximateExtent {
  area_pixels?: number | null;
  equivalent_diameter?: number | null;
  width?: number | null;
  height?: number | null;
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
  approximate_extent?: ApproximateExtent | null;
  is_heuristic_candidate?: boolean;
}

export interface LesionDetectionResult {
  model: string;
  status?: "ready" | "unavailable" | "heuristic_only";
  message?: string;
  detections: LesionDetection[];
  model_estimated_count?: Record<string, number>;
  model_trained: boolean;
}

export type ConsistencyStatus =
  | "concordant"
  | "discordant_classifier_high"
  | "discordant_lesions_high"
  | "uncertain_prediction"
  | "quality_compromised"
  | "component_unavailable";

export interface ConfidenceCalibration {
  status: "calibrated" | "uncalibrated_raw_softmax" | "fallback_uniform";
  temperature: number | null;
  max_calibrated_probability: number | null;
  confidence_margin: number | null;
  shannon_entropy: number | null;
  is_uncertain: boolean;
}

export interface ConsistencyAnalysis {
  consistency_status: ConsistencyStatus;
  finding_label: string;
  human_review_required: boolean;
  review_reasons: string[];
  recommended_grade: number | null;
  recommended_urgency: ReferralUrgency;
  rules_version: string;
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
  gradcam_explanation?: GradCAMExplanation | null;
  confidence_calibration?: ConfidenceCalibration | null;
  lesion_detection: LesionDetectionResult | null;
  consistency_analysis?: ConsistencyAnalysis | null;
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
// Consent Types (DPDP Act 2023)
// ---------------------------------------------------------------------------

export interface ConsentCreate {
  patient_id: string;
  consent_type?: string;
  granted: boolean;
  obtained_by_name?: string;
  witness_name?: string;
  notes?: string;
}

export interface ConsentRecord {
  id: string;
  patient_id: string;
  consent_type: string;
  granted: boolean;
  obtained_by_name: string | null;
  witness_name?: string | null;
  granted_at: string;
  withdrawn_at: string | null;
  is_active: boolean;
}

// ---------------------------------------------------------------------------
// Smartphone + 20D Condensing Lens Quality Assessment
// ---------------------------------------------------------------------------

export interface QualityAssessmentDetail {
  overall_quality: QualityVerdict;
  is_acceptable: boolean;
  sharpness_score: number;
  illumination_uniformity: number;
  field_of_view_adequate: boolean;
  artifacts_detected: string[];
  recapture_guidance: string[];
}

export interface UploadImageResponse {
  image_id: string;
  original_filename: string;
  eye: "left" | "right";
  lens_type: string;
  width: number;
  height: number;
  file_size_bytes: number;
  sha256_hash: string;
  quality_assessment: QualityAssessmentDetail;
}

// ---------------------------------------------------------------------------
// Inference Job Types
// ---------------------------------------------------------------------------

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface JobCreateRequest {
  screening_id: string;
  image_id?: string | null;
  run_matlab?: boolean;
  run_yolo?: boolean;
  timeout_seconds?: number;
  idempotency_key?: string | null;
}

export interface JobReadResponse {
  id: string;
  screening_id: string;
  image_id?: string | null;
  facility_id?: string | null;
  idempotency_key: string;
  status: JobStatus;
  priority: number;
  retry_count: number;
  max_retries: number;
  timeout_seconds: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  worker_id?: string | null;
  parameters?: Record<string, any> | null;
  result?: AnalysisResult | null;
  timings?: Record<string, number> | null;
  model_metadata?: Record<string, any> | null;
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
    description: "Proliferative diabetic retinopathy (neovascularization)",
    referral_urgency: "urgent",
    followup_weeks: 1,
    color_hex: "#ef4444",
  },
};

// ---------------------------------------------------------------------------
// Reproducible Evaluation Suite Types
// ---------------------------------------------------------------------------

export interface MetricWithCI {
  value: number;
  ci_lower: number;
  ci_upper: number;
  confidence_level?: number;
}

export interface PerClassMetric {
  grade: number;
  class_name: string;
  precision: number;
  recall: number;
  specificity: number;
  f1_score: number;
  support: number;
}

export interface ConfusionMatrixData {
  matrix: number[][];
  class_labels: string[];
}

export interface ScreeningEndpointMetrics {
  endpoint_name: string;
  threshold_rule: string;
  sensitivity: MetricWithCI;
  specificity: MetricWithCI;
  ppv?: number | null;
  npv?: number | null;
  auroc?: MetricWithCI | null;
  aupr?: number | null;
  f1_score?: number | null;
  support_positive: number;
  support_negative: number;
}

export interface EvaluationCalibrationMetrics {
  status: "calibrated" | "uncalibrated_raw_softmax" | "fallback_uniform";
  ece: MetricWithCI;
  mce: number;
  brier_score: number;
  negative_log_likelihood: number;
}

export interface QualityCoverageMetrics {
  total_images: number;
  accepted_images: number;
  ungradeable_images: number;
  ungradeable_rate: number;
  accepted_coverage: number;
  whole_pipeline_failures: number;
  whole_pipeline_failure_rate: number;
}

export interface AblationResult {
  ablation_id: string;
  ablation_name: string;
  description: string;
  macro_f1: number;
  quadratic_weighted_kappa: number;
  rdr_sensitivity: number;
  rdr_specificity: number;
  ungradeable_rate: number;
  notes?: string;
}

export interface SubgroupResult {
  subgroup_name: string;
  category: string;
  sample_size: number;
  is_insufficient_sample: boolean;
  macro_f1?: number | null;
  quadratic_weighted_kappa?: number | null;
  rdr_sensitivity?: number | null;
  rdr_specificity?: number | null;
  notes?: string;
}

export interface DegradationPoint {
  corruption_type: string;
  severity_label: string;
  severity_value: number;
  macro_f1: number;
  quadratic_weighted_kappa: number;
  rdr_sensitivity: number;
}

export interface EvaluationReport {
  report_id: string;
  timestamp: string;
  pipeline_version: string;
  rules_version: string;
  dataset_name: string;
  evaluation_manifest_hash: string;
  is_frozen: boolean;
  total_images: number;
  total_patients: number;
  resampling_method: "patient_cluster" | "image_level";
  bootstrap_iterations: number;
  quadratic_weighted_kappa: MetricWithCI;
  macro_f1: MetricWithCI;
  balanced_accuracy: MetricWithCI;
  per_class_metrics: PerClassMetric[];
  confusion_matrix: ConfusionMatrixData;
  referable_dr: ScreeningEndpointMetrics;
  sight_threatening_dr: ScreeningEndpointMetrics;
  calibration: EvaluationCalibrationMetrics;
  quality_coverage: QualityCoverageMetrics;
  ablations: AblationResult[];
  subgroup_analysis: SubgroupResult[];
  degradation_analysis: DegradationPoint[];
  disclaimer: string;
}

// ---------------------------------------------------------------------------
// Clinical Reports & Voice Types
// ---------------------------------------------------------------------------

export interface ReportRead {
  id: string;
  screening_id: string;
  generated_by_id: string | null;
  signed_by_id: string | null;
  report_type: string;
  status: "draft" | "signed" | "archived" | string;
  summary_json: Record<string, any>;
  file_path: string | null;
  created_at: string;
}

export interface ReportGenerateRequest {
  report_type: "technical_report" | "patient_summary" | "screening_summary" | "ophthalmology_referral";
  language?: "en" | "hi";
  is_signed?: boolean;
}

export interface VoicePlaybackRequest {
  voice_consent: boolean;
  language: "en" | "hi";
}

export interface VoicePlaybackResponse {
  voice_supported: boolean;
  fallback_to_text: boolean;
  voice_name: string | null;
  language: string;
  audio_base64: string | null;
  audio_format: string | null;
  spoken_text: string;
  status_message: string;
}

