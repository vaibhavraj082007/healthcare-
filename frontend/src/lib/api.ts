/**
 * RetinaShield — Typed API Client
 *
 * Connects the Next.js frontend to the FastAPI backend.
 * Integrates token authentication, patient registration, consent recording,
 * 20D condensing lens fundus upload, IQA, and background inference jobs.
 */

import type {
  Patient,
  PatientCreate,
  Screening,
  ScreeningCreate,
  ScreeningSummary,
  AnalysisResult,
  PipelineInfo,
  ConsentCreate,
  ConsentRecord,
  UploadImageResponse,
  JobCreateRequest,
  JobReadResponse,
  ReportRead,
  VoicePlaybackResponse,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Auth token helper
// ---------------------------------------------------------------------------

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("retinashield_token");
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }
  return headers;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const authHeaders = getAuthHeaders();

  const res = await fetch(url, {
    ...options,
    headers: {
      ...authHeaders,
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API Error: ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ---------------------------------------------------------------------------
// Patients (DPDP Act 2023 Compliant)
// ---------------------------------------------------------------------------

export const patientsApi = {
  list: (params?: { skip?: number; limit?: number; search?: string }) => {
    const query = new URLSearchParams();
    if (params?.skip) query.set("skip", String(params.skip));
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.search) query.set("search", params.search);
    return apiFetch<Patient[]>(`/api/patients/?${query}`);
  },

  get: (id: string) => apiFetch<Patient>(`/api/patients/${id}`),

  create: (data: PatientCreate) =>
    apiFetch<Patient>("/api/patients/", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  update: (id: string, data: Partial<PatientCreate>) =>
    apiFetch<Patient>(`/api/patients/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  delete: (id: string) =>
    apiFetch<void>(`/api/patients/${id}`, { method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Consent Management
// ---------------------------------------------------------------------------

export const consentApi = {
  record: (data: ConsentCreate) =>
    apiFetch<ConsentRecord>("/api/consent/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// ---------------------------------------------------------------------------
// Screenings & Smartphone + 20D Condensing Lens Ingestion
// ---------------------------------------------------------------------------

export const screeningsApi = {
  list: (params?: {
    patient_id?: string;
    facility_id?: string;
    status?: string;
    skip?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.patient_id) query.set("patient_id", params.patient_id);
    if (params?.facility_id) query.set("facility_id", params.facility_id);
    if (params?.status) query.set("status", params.status);
    if (params?.skip) query.set("skip", String(params.skip));
    if (params?.limit) query.set("limit", String(params.limit));
    return apiFetch<ScreeningSummary[]>(`/api/screenings/?${query}`);
  },

  get: (id: string) => apiFetch<Screening>(`/api/screenings/${id}`),

  create: (data: ScreeningCreate) =>
    apiFetch<Screening>("/api/screenings/", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  uploadImage: async (
    screeningId: string,
    eye: "left" | "right",
    file: File,
    lensType: string = "20D_condensing",
    cameraModel: string = "Smartphone + 20D Condensing Lens"
  ): Promise<UploadImageResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    const query = new URLSearchParams({
      eye,
      lens_type: lensType,
      camera_model: cameraModel,
    });
    const url = `${API_BASE}/api/screenings/${screeningId}/images?${query.toString()}`;

    const headers: Record<string, string> = {};
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("retinashield_token");
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
    }

    const res = await fetch(url, {
      method: "POST",
      body: formData,
      headers,
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `Upload Error: ${res.status}`);
    }
    return res.json();
  },

  getImageUrl: (screeningId: string, imageId: string) =>
    `${API_BASE}/api/screenings/${screeningId}/images/${imageId}/view`,
};

// ---------------------------------------------------------------------------
// Persisted Background Inference Jobs
// ---------------------------------------------------------------------------

export const jobsApi = {
  submit: (data: JobCreateRequest) =>
    apiFetch<JobReadResponse>("/api/jobs/", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  get: (jobId: string) => apiFetch<JobReadResponse>(`/api/jobs/${jobId}`),

  cancel: (jobId: string) =>
    apiFetch<{ job_id: string; status: string; message: string }>(
      `/api/jobs/${jobId}/cancel`,
      { method: "POST" }
    ),

  list: (screeningId?: string) => {
    const query = screeningId ? `?screening_id=${screeningId}` : "";
    return apiFetch<{ items: JobReadResponse[]; total: number }>(`/api/jobs/${query}`);
  },
};

// ---------------------------------------------------------------------------
// Analysis (Direct Synchronous / Pipeline Info)
// ---------------------------------------------------------------------------

export const analysisApi = {
  run: (screeningId: string, options?: { run_matlab?: boolean; run_yolo?: boolean; force_rerun?: boolean }) =>
    apiFetch<{
      screening_id: string;
      status: string;
      message: string;
      result: AnalysisResult | null;
    }>("/api/analysis/run", {
      method: "POST",
      body: JSON.stringify({
        screening_id: screeningId,
        ...options,
      }),
    }),

  getStatus: (screeningId: string) =>
    apiFetch<{
      screening_id: string;
      status: string;
      quality_verdict: string | null;
      dr_grade: number | null;
      dr_grade_label: string | null;
      referral_urgency: string | null;
      model_trained: boolean;
      disclaimer: string;
    }>(`/api/analysis/status/${screeningId}`),

  getPipelineInfo: () => apiFetch<PipelineInfo>("/api/analysis/pipeline-info"),
};

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

export const syncApi = {
  getStatus: (facilityId: string) =>
    apiFetch<{
      facility_id: string;
      facility_name: string;
      last_sync_at: string | null;
      pending_sync_count: number;
      is_active: boolean;
    }>(`/api/sync/status/${facilityId}`),
};

// ---------------------------------------------------------------------------
// Ophthalmologist Review Queue & Case Review
// ---------------------------------------------------------------------------

export const reviewsApi = {
  /** Filtered, prioritised review queue. */
  getQueue: (params?: {
    facility_id?: string;
    date_from?: string;
    date_to?: string;
    quality?: string;
    provisional_severity?: number;
    uncertainty?: boolean;
    disagreement?: boolean;
    review_status?: string;
    priority_sort?: string;
    skip?: number;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.facility_id) q.set("facility_id", params.facility_id);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    if (params?.quality) q.set("quality", params.quality);
    if (params?.provisional_severity !== undefined)
      q.set("provisional_severity", String(params.provisional_severity));
    if (params?.uncertainty !== undefined) q.set("uncertainty", String(params.uncertainty));
    if (params?.disagreement !== undefined) q.set("disagreement", String(params.disagreement));
    if (params?.review_status) q.set("review_status", params.review_status);
    if (params?.priority_sort) q.set("priority_sort", params.priority_sort);
    if (params?.skip !== undefined) q.set("skip", String(params.skip));
    if (params?.limit !== undefined) q.set("limit", String(params.limit));
    return apiFetch<{
      items: ReviewQueueItem[];
      total: number;
      skip: number;
      limit: number;
      priority_rule: string;
      priority_rule_version: string;
      priority_rule_requires_clinical_approval: boolean;
      priority_rule_approval_note: string;
    }>(`/api/screenings/review-queue?${q}`);
  },

  /** Acquire exclusive editing lock on a case. */
  claimLock: (screeningId: string) =>
    apiFetch<{
      screening_id: string;
      locked_by_id: string;
      locked_at: string;
      lock_expires_at: string;
      message: string;
    }>(`/api/screenings/${screeningId}/review/claim`, { method: "POST" }),

  /** Release the editing lock. */
  releaseLock: (screeningId: string) =>
    apiFetch<{ screening_id: string; message: string }>(
      `/api/screenings/${screeningId}/review/release`,
      { method: "POST" }
    ),

  /** Submit or amend a clinician review. */
  submit: (screeningId: string, data: ClinicianReviewCreate) =>
    apiFetch<ClinicianReviewRead>(`/api/screenings/${screeningId}/review`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** Get the current review and its amendment history. */
  get: (screeningId: string) =>
    apiFetch<ClinicianReviewRead>(`/api/screenings/${screeningId}/review`),

  /** Get the immutable amendment audit trail. */
  getHistory: (screeningId: string) =>
    apiFetch<ReviewAmendmentRead[]>(`/api/screenings/${screeningId}/review/history`),

  /** Generate a clinical report or patient summary. */
  generateReport: (
    screeningId: string,
    data: {
      report_type?: string;
      language?: string;
      is_signed?: boolean;
      include_ai_findings?: boolean;
      include_gradcam?: boolean;
    }
  ) =>
    apiFetch<ReportRead>(`/api/screenings/${screeningId}/report`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** List all generated reports for a screening. */
  listReports: (screeningId: string) =>
    apiFetch<ReportRead[]>(`/api/screenings/${screeningId}/reports`),

  /** Get specific report by ID or the most recent signed report. */
  getReport: (screeningId: string, reportId?: string) =>
    apiFetch<ReportRead>(
      reportId
        ? `/api/screenings/${screeningId}/reports/${reportId}`
        : `/api/screenings/${screeningId}/report`
    ),

  /** Get PDF download/streaming URL. */
  getPdfUrl: (screeningId: string, reportId: string) =>
    `${API_BASE}/api/screenings/${screeningId}/reports/${reportId}/pdf`,

  /** Offline speech synthesis with local fallback. */
  synthesizeVoice: (
    screeningId: string,
    reportId: string,
    data: { voice_consent: boolean; language: "en" | "hi" }
  ) =>
    apiFetch<VoicePlaybackResponse>(
      `/api/screenings/${screeningId}/reports/${reportId}/voice`,
      {
        method: "POST",
        body: JSON.stringify(data),
      }
    ),
};

// ---------------------------------------------------------------------------
// Review-related types (inline — avoids circular import with types.ts)
// ---------------------------------------------------------------------------

export interface ReviewQueueItem {
  screening_id: string;
  patient_id: string;
  patient_name: string | null;
  facility_id: string | null;
  eye: string;
  screened_at: string;
  quality_verdict: string | null;
  ai_dr_grade: number | null;
  ai_dr_grade_label: string | null;
  ai_confidence: number | null;
  ai_referral_urgency: string | null;
  ai_model_trained: boolean;
  is_uncertain: boolean;
  has_disagreement: boolean;
  concordance_status: string | null;
  review_status:
    | "ai_generated"
    | "awaiting_review"
    | "in_review"
    | "clinician_reviewed"
    | "recapture_requested";
  confirmed_dr_grade: number | null;
  confirmed_grade_label: string | null;
  review_version: number | null;
  locked_by_id: string | null;
  lock_expires_at: string | null;
}

export interface ReviewAmendmentRead {
  id: string;
  review_id: string;
  amended_by_id: string | null;
  previous_grade: number | null;
  new_grade: number | null;
  previous_referral: string | null;
  new_referral: string | null;
  previous_status: string | null;
  new_status: string | null;
  change_reason: string | null;
  amendment_notes: string | null;
  amended_at: string;
}

export interface ClinicianReviewRead {
  id: string;
  screening_id: string;
  reviewer_id: string;
  review_version: number;
  confirmed_dr_grade: number;
  macular_edema_present: boolean | null;
  is_ungradeable: boolean;
  recapture_requested: boolean;
  referral_recommendation: string;
  follow_up_months: number | null;
  clinical_notes: string;
  status: string;
  locked_by_id: string | null;
  locked_at: string | null;
  lock_expires_at: string | null;
  reviewed_at: string;
  updated_at: string;
  amendments: ReviewAmendmentRead[];
}

export interface ClinicianReviewCreate {
  confirmed_dr_grade: number;
  macular_edema_present?: boolean | null;
  referral_recommendation?: "none" | "routine" | "priority" | "urgent";
  follow_up_months?: number | null;
  clinical_notes: string;
  status?: "draft" | "final";
  is_ungradeable?: boolean;
  recapture_requested?: boolean;
  expected_version?: number | null;
  change_reason?: string | null;
}

// ---------------------------------------------------------------------------
// Operational Monitoring & Clinical Interoperability
// ---------------------------------------------------------------------------

export interface AggregationCell {
  category: string;
  count: number | null;
  display_count: string;
  is_suppressed: boolean;
}

export interface OperationalMetrics {
  generated_at: string;
  facility_id_filter: string | null;
  time_window_days: number;
  privacy_suppression_threshold: number;
  screening_volume: {
    total_screenings: number;
    last_24h: number;
    last_7d: number;
    last_30d: number;
    daily_trend: AggregationCell[];
    by_facility: AggregationCell[];
  };
  ungradeable_rates: {
    total_screenings_evaluated: number;
    total_ungradeable_count: number;
    ungradeable_rate_pct: number;
    ai_ungradeable_count: number;
    ai_ungradeable_pct: number;
    clinician_ungradeable_count: number;
    clinician_ungradeable_pct: number;
    quality_verdict_breakdown: Record<string, number>;
    failure_reasons_breakdown: Record<string, number>;
  };
  review_backlog: {
    total_backlog: number;
    awaiting_review_count: number;
    draft_review_count: number;
    age_distribution: {
      under_24h: number;
      between_24_72h: number;
      over_72h: number;
    };
    urgency_distribution: {
      none: number;
      routine: number;
      priority: number;
      urgent: number;
    };
    oldest_pending_hours: number | null;
  };
  processing_failures: {
    total_jobs: number;
    completed_jobs: number;
    failed_jobs: number;
    failure_rate_pct: number;
    failure_categories: Record<string, number>;
    recent_failures: Array<{
      job_id: string;
      facility_id: string | null;
      error_message: string;
      failed_at: string | null;
    }>;
  };
  synchronization_failures: {
    total_synced_screenings: number;
    pending_sync_screenings: number;
    sync_conflicts_total: number;
    sync_conflicts_unresolved: number;
    incomplete_chunk_sessions: number;
    conflict_type_breakdown: Record<string, number>;
  };
  latency: {
    total_measured_jobs: number;
    mean_seconds: number | null;
    median_seconds: number | null;
    p95_seconds: number | null;
    min_seconds: number | null;
    max_seconds: number | null;
    stage_breakdown_mean_seconds: Record<string, number>;
  };
  model_version_usage: Array<{
    model_name: string;
    model_version: string;
    runs_count: number;
    percentage: number;
    model_trained: boolean;
  }>;
  clinical_accuracy_separation_disclaimer: string;
}

export interface ShiftMetrics {
  generated_at: string;
  current_window_days: number;
  baseline_window_days: number;
  current_sample_size: number;
  baseline_sample_size: number;
  small_cell_suppression_applied: boolean;
  quality_shift_metrics: Array<{
    metric_name: string;
    baseline_mean: number | null;
    baseline_std: number | null;
    current_mean: number | null;
    current_std: number | null;
    delta_mean: number | null;
    shift_flag: boolean;
  }>;
  quality_verdict_shift: {
    baseline: Record<string, number>;
    current: Record<string, number>;
  };
  ungradeable_rate_shift: {
    baseline_pct: number;
    current_pct: number;
  };
  prediction_dr_grade_shift: {
    baseline: Record<string, number>;
    current: Record<string, number>;
  };
  confidence_shift: {
    baseline: number | null;
    current: number | null;
  };
  entropy_shift: {
    baseline: number | null;
    current: number | null;
  };
  regulatory_safety_notice: string;
}

export interface InteropStatus {
  fhir_version: string;
  abdm_exchange_enabled: boolean;
  abha_linking_enabled: boolean;
  environment: string;
  hip_id: string;
  gateway_url: string;
  supported_profiles: Array<{
    profile_name: string;
    standard: string;
    structure_definition: string;
    status: string;
    description: string;
  }>;
  remaining_integration_requirements: Array<{
    milestone: string;
    requirement_name: string;
    status: string;
    details: string;
    mandatory_for_routine_screening: boolean;
  }>;
  safeguards: string;
}

export interface FHIRBundleExport {
  screening_id: string;
  patient_id: string;
  bundle_id: string;
  bundle_type: string;
  composition_status: string;
  has_clinician_approval: boolean;
  is_provisional: boolean;
  resource_count: number;
  bundle_json: Record<string, any>;
  integrity_sha256: string;
}

export interface ExchangeTestResult {
  allowed: boolean;
  environment: string;
  reason: string;
  prerequisite_checklist: Record<string, boolean>;
  guidance: string;
}

export const monitoringApi = {
  getOperational: (params?: { facility_id?: string; days?: number }) => {
    const q = new URLSearchParams();
    if (params?.facility_id) q.set("facility_id", params.facility_id);
    if (params?.days) q.set("days", String(params.days));
    return apiFetch<OperationalMetrics>(`/api/monitoring/operational?${q}`);
  },

  getShifts: (params?: {
    current_days?: number;
    baseline_days?: number;
    facility_id?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.current_days) q.set("current_days", String(params.current_days));
    if (params?.baseline_days) q.set("baseline_days", String(params.baseline_days));
    if (params?.facility_id) q.set("facility_id", params.facility_id);
    return apiFetch<ShiftMetrics>(`/api/monitoring/shifts?${q}`);
  },

  getInteropStatus: () => apiFetch<InteropStatus>("/api/monitoring/interop/status"),

  exportFHIR: (screeningId: string) =>
    apiFetch<FHIRBundleExport>(`/api/monitoring/interop/export/${screeningId}`),

  testExchange: () =>
    apiFetch<ExchangeTestResult>("/api/monitoring/interop/exchange/test", {
      method: "POST",
    }),
};


