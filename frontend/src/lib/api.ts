/**
 * RetinaShield — API Client
 *
 * Typed client for the FastAPI backend. All responses include the
 * research screening disclaimer.
 */

import type {
  Patient,
  PatientCreate,
  Screening,
  ScreeningCreate,
  ScreeningSummary,
  AnalysisResult,
  PipelineInfo,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API Error: ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ---------------------------------------------------------------------------
// Patients
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
// Screenings
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

  uploadImage: async (screeningId: string, eye: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const url = `${API_BASE}/api/screenings/${screeningId}/images?eye=${eye}`;
    const res = await fetch(url, { method: "POST", body: formData });
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
// Analysis
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
