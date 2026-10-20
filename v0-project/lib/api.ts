export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"

export class ApiError extends Error {
  status: number
  detail?: string

  constructor(message: string, status: number, detail?: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

/**
 * Thin typed wrapper around the NetraScan FastAPI backend.
 * Throws ApiError with the backend `detail` message when a request fails.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.body instanceof FormData
      ? {}
      : { "Content-Type": "application/json" }),
    ...(init.headers as Record<string, string>),
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })

  if (!response.ok) {
    let detail: string | undefined
    try {
      const body = await response.json()
      detail = typeof body.detail === "string" ? body.detail : undefined
    } catch {
      // non-JSON error body — keep undefined detail
    }
    const error = new ApiError(
      detail ?? `Request failed (${response.status})`,
      response.status,
      detail,
    )
    throw error
  }

  return (await response.json()) as T
}

export interface UserOut {
  id: number
  email: string
  full_name: string
  role: "patient" | "health_worker" | "doctor" | "admin" | "ophthalmologist"
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: UserOut
}

export interface FindingOut {
  image_id: string
  lesion_list: string | { type: string; count: number }[]
  lesion_count: number
  icdr_grade: number | null
  icdr_confidence: number | null
  consistency_status: string
  analysis_status: string
  analyzed_at: string | null
  model_provenance?: string | null
}

export interface UploadOut {
  image_id: string
  patient_id: number
  filename: string
  quality_status: string
  quality_score: number | null
  retake_count?: number
  eye_laterality?: string
  uploaded_at: string
  findings: FindingOut[]
}

export interface PatientOut {
  id: number
  full_name: string
  age: number | null
  gender: string | null
  village: string | null
  district: string | null
  phone: string | null
  created_at: string
  has_login: boolean
}

export interface RoleStats {
  total_patients: number
  total_scans: number
  scans_analyzed: number
  scans_pending: number
  flagged_for_review: number
  grade_distribution: Record<string, number>
}

export interface ReviewQueueItem {
  image_id: string
  patient_name: string
  patient_id: number | null
  icdr_grade: number | null
  icdr_confidence: number | null
  lesion_count: number | null
  lesion_list: string | null
  consistency_status: string
  analysis_status: string
  analyzed_at: string | null
  model_provenance?: string | null
}

export interface ModelInfo {
  name: string
  family: string
  task: string
  trained_on: string
  fine_tuned: boolean
  weights: boolean
  weights_path: string
  validation: Record<string, unknown>
  note: string
}

export interface LesionSummaryItem {
  type: string
  count: number
  avg_confidence: number | null
}

export interface LesionBreakdownItem {
  type: string
  count: number
}

export interface ReportHeader {
  patient_id: number | null
  patient_name: string | null
  patient_age: number | null
  patient_gender: string | null
  referring_phc: string | null
  submitting_worker: string | null
  scan_date: string | null
  eye_laterality: string | null
  image_quality?: string | null
  quality_score?: number | null
  report_id?: string | null
  generated_at?: string | null
  scan_id?: string | null
}

export interface RegionAnalysis {
  cluster_count: number | null
  used_optic_disc: boolean
  disc: unknown
  clusters: unknown
  description: string | null
  macula_attention: boolean
  exudates_near_macula: number
  spread_evenly: boolean
}

export interface MedicalReportLesionLine {
  label: string
  count_text: string
  confidence_text: string
}

export interface MedicalReportLesionTableRow {
  type: string
  label: string
  count: number
  confidence: number | null
}

export interface MedicalReport {
  report_id: string
  generated_at: string | null
  severity_scale?: {
    classifier_grade: number | null
    lesion_grade: number | null
    mode: "concordant" | "discordant" | "classifier_only" | "unavailable"
  } | null
  heatmap_available?: boolean
  patient: {
    name: string
    patient_id: string
    age: string
    gender: string
    referring_phc: string
    submitting_worker: string
  }
  examination: {
    scan_id: string
    scan_date: string | null
    eye: string
    modality: string
    quality: string
    optic_disc_visible?: string
    macula_visible?: string
  }
  findings: {
    optic_disc: string
    macula: string
    vasculature: string
    background: string
    lesion_lines: MedicalReportLesionLine[]
    lesion_note: string | null
    region_attention: string
  }
  lesion_table: MedicalReportLesionTableRow[]
  classification: {
    grade: number | null
    label: string
    basis: string
    icdr_confidence: number | null
    total_lesion_count: number
  }
  consistency: {
    headline: string
    status: string
    discrepant: boolean
  }
  impression: string
  observations: string[]
  recommendation: string
  ai_analysis_summary: {
    classifier: string
    detector: string
    grade: string
    consistency: string
    region_analysis: string
  }
  report_status: {
    report_id: string
    generated_at: string
    method: string
    model_version: string
  }
  disclaimer: string
}

export interface ScreeningReportHi {
  grade_label: string
  consistency_status: string
  flagged_reason: string | null
  lesion_labels: Record<string, string>
  region_notes?: string
  grade_basis?: string
  observations: string[]
  recommendation?: string
  macular_edema_note?: string | null
  eye?: string
  disclaimer?: string
  patient_report?: string
}

export interface StructuredFindings {
  icdr_grade: number | null
  icdr_grade_label: string
  lesion_breakdown?: LesionBreakdownItem[]
  lesion_summary: LesionSummaryItem[]
  total_lesion_count: number
  consistency_status: string
  flagged_reason: string | null
  model_version: string | null
  grade_basis?: string
  possible_macular_edema?: boolean
  macular_edema_note?: string | null
  region_analysis?: RegionAnalysis | null
  region_notes?: string | null
  observations?: string[]
  recommendation?: string | null
  disclaimer?: string | null
  medical_report?: MedicalReport | null
  hi?: ScreeningReportHi | null
}

export interface ScreeningReport {
  image_id: string
  report_text: string
  structured_findings: StructuredFindings
  region_notes: string | null
  gradcam_path: string | null
  generation_method: "template" | "llm"
  model_version: string | null
  generated_at: string | null
  header?: ReportHeader | null
  observations?: string[]
  recommendation?: string | null
  disclaimer?: string | null
  image_urls?: { fundus?: string | null; heatmap?: string | null } | null
  fundus_image_url?: string | null
  heatmap_image_url?: string | null
}

export interface DoctorQueueItem {
  image_id: string
  patient_id: number
  patient_name: string
  icdr_grade: number | null
  icdr_confidence: number | null
  consistency_status: string
  sync_status: "queued" | "syncing" | "synced" | "failed"
  viewed: boolean
  signed_off: boolean
  signed_decision: "Approved" | "Revised" | "Rejected" | null
  analyzed_at: string | null
}

export interface DoctorQueueCount {
  unseen: number
  unseen_flagged: number
}

export interface SignOffInput {
  image_id: string
  decision: "Approved" | "Revised" | "Rejected"
  doctor_notes?: string
  revised_grade?: number | null
}

export interface SignOffResult {
  image_id: string
  decision: string
  doctor_notes: string | null
  revised_grade: number | null
  signed_at: string
  summary_languages: string[]
}

export interface SyncStatus {
  pending: number
  syncing: number
  synced: number
  failed: number
  total: number
  offline_sim: boolean
}

export type PatientScanState =
  | "scan_received"
  | "analysis_in_progress"
  | "awaiting_review"
  | "reviewed"

export interface PatientStatus {
  image_id: string
  state: PatientScanState
  stage_label: string
  patient_text: string
  summary_languages: string[]
  signed_off: boolean
  signed_decision: string | null
  revised_grade: number | null
}

export interface PatientSummary {
  language: string
  summary_text: string
  has_audio: boolean
  content_version?: string
}

export type CaseStatus = "New" | "Claimed" | "Contacted" | "Reviewed"
export type SeverityBand = "Low" | "Medium" | "High"

export interface CaseListItem {
  image_id: string
  patient_id: number
  patient_name: string
  patient_age: number | null
  patient_gender: string | null
  village: string | null
  district: string | null
  phc: string | null
  icdr_grade: number | null
  icdr_confidence: number | null
  consistency_status: string
  severity_band: SeverityBand
  status: CaseStatus
  flagged: boolean
  assigned_doctor_id: number | null
  assigned_doctor_name: string | null
  worker_id: number | null
  worker_name: string | null
  has_report: boolean
  signed_off: boolean
  analyzed_at: string | null
  uploaded_at: string | null
  claimed_at: string | null
  contacted_at: string | null
  reviewed_at: string | null
  created_at: string | null
}

export interface CaseSummary {
  total: number
  high: number
  medium: number
  low: number
  flagged_pending: number
  awaiting_review: number
  claimed_by_me: number
  today_reported: number
  today_reviewed: number
}

export interface CaseNote {
  id: number
  image_id: string
  author_id: number
  author_name: string
  body: string
  created_at: string
}

export interface CaseSignOff {
  decision: string
  doctor_notes: string | null
  revised_grade: number | null
  signed_at: string
  ophthalmologist_id: number
}

export interface CaseDetail extends CaseListItem {
  phone: string | null
  lesion_count: number | null
  lesion_list: unknown
  sync_status: string
  report_generation_method: string | null
  sign_off: CaseSignOff | null
  notes: CaseNote[]
}

export interface NlSearchResult {
  query: string
  matched: boolean
  filter: Record<string, string> | null
  message: string
  items: CaseListItem[]
}

export interface PatientCaseInfo {
  image_id: string | null
  status: string
  severity_band: SeverityBand | null
  flagged: boolean
  has_case: boolean
  updated_at: string | null
}

export const authApi = {
  login: (email: string, password: string) =>
    apiFetch<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: (token: string) => apiFetch<UserOut>("/auth/me", {}, token),
}

export const patientsApi = {
  self: (token: string) => apiFetch<PatientOut>("/patients/self", {}, token),
  list: (token: string) => apiFetch<PatientOut[]>("/patients", {}, token),
  create: (token: string, patient: Record<string, unknown>) =>
    apiFetch<PatientOut>("/patients", {
      method: "POST",
      body: JSON.stringify(patient),
    }, token),
  addLogin: (token: string, patientId: number, email: string, password: string) =>
    apiFetch<PatientOut>(`/patients/${patientId}/login`, {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }, token),
  scans: (token: string, patientId: number) =>
    apiFetch<UploadOut[]>(`/patients/${patientId}/scans`, {}, token),
  caseInfo: (token: string, patientId: number) =>
    apiFetch<PatientCaseInfo>(`/patients/${patientId}/case`, {}, token),
}

export const uploadsApi = {
  create: (token: string, patientId: number, file: File, eyeLaterality: string = "unknown") => {
    const form = new FormData()
    form.append("patient_id", String(patientId))
    form.append("eye_laterality", eyeLaterality)
    form.append("file", file)
    return apiFetch<UploadOut>("/uploads", { method: "POST", body: form }, token)
  },
  get: (token: string, imageId: string) =>
    apiFetch<UploadOut>(`/uploads/${imageId}`, {}, token),
  analyze: (token: string, imageId: string) =>
    apiFetch<FindingOut>(`/analyze/${imageId}`, { method: "POST" }, token),
}

export const dashboardApi = {
  stats: (token: string) => apiFetch<RoleStats>("/stats", {}, token),
  reviewQueue: (token: string) =>
    apiFetch<ReviewQueueItem[]>("/review-queue", {}, token),
  models: (token: string) => apiFetch<ModelInfo[]>("/models", {}, token),
}

export const reportsApi = {
  get: (token: string, imageId: string) =>
    apiFetch<ScreeningReport>(`/reports/${imageId}`, {}, token),
  gradcamUrl: (imageId: string) =>
    `${API_BASE_URL}/reports/${imageId}/gradcam`,
}

export const telemedApi = {
  queue: (token: string) =>
    apiFetch<DoctorQueueItem[]>("/doctor/queue", {}, token),
  queueCount: (token: string) =>
    apiFetch<DoctorQueueCount>("/doctor/queue/count", {}, token),
  markSeen: (token: string, imageId: string) =>
    apiFetch<{ image_id: string; viewed: boolean }>(
      `/doctor/queue/${imageId}/seen`,
      { method: "POST" },
      token,
    ),
  signOff: (token: string, input: SignOffInput) =>
    apiFetch<SignOffResult>("/doctor/signoffs", {
      method: "POST",
      body: JSON.stringify(input),
    }, token),
  syncStatus: (token: string) =>
    apiFetch<SyncStatus>("/sync/status", {}, token),
  setOfflineSim: (token: string, enabled: boolean) =>
    apiFetch<SyncStatus>("/sync/offline-sim", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }, token),
  scanStatus: (token: string, imageId: string) =>
    apiFetch<PatientStatus>(`/reports/${imageId}/status`, {}, token),
  summaries: (token: string, imageId: string) =>
    apiFetch<PatientSummary[]>(`/summaries/${imageId}`, {}, token),
}

export const doctorApi = {
  cases: (token: string, params?: Record<string, string>) => {
    const qs = params ? new URLSearchParams(params).toString() : ""
    return apiFetch<CaseListItem[]>(
      `/doctor/cases${qs ? `?${qs}` : ""}`,
      {},
      token,
    )
  },
  summary: (token: string) =>
    apiFetch<CaseSummary>("/doctor/cases/summary", {}, token),
  detail: (token: string, imageId: string) =>
    apiFetch<CaseDetail>(`/doctor/cases/detail/${imageId}`, {}, token),
  notes: (token: string, imageId: string) =>
    apiFetch<CaseNote[]>(`/doctor/cases/notes/${imageId}`, {}, token),
  addNote: (token: string, imageId: string, body: string) =>
    apiFetch<CaseNote>(
      `/doctor/cases/notes/${imageId}`,
      { method: "POST", body: JSON.stringify({ body }) },
      token,
    ),
  claim: (token: string, imageId: string) =>
    apiFetch<CaseDetail>(
      `/doctor/cases/claim/${imageId}`,
      { method: "POST" },
      token,
    ),
  setStatus: (token: string, imageId: string, status: CaseStatus) =>
    apiFetch<CaseDetail>(
      `/doctor/cases/status/${imageId}`,
      { method: "POST", body: JSON.stringify({ status }) },
      token,
    ),
  search: (token: string, query: string) =>
    apiFetch<NlSearchResult>(
      "/doctor/cases/search",
      { method: "POST", body: JSON.stringify({ query }) },
      token,
    ),
}

export function summaryAudioUrl(
  imageId: string,
  language: string,
  contentVersion?: string,
): string {
  const base = `${API_BASE_URL}/summaries/${imageId}/${language}/audio`
  return contentVersion ? `${base}?v=${encodeURIComponent(contentVersion)}` : base
}

export async function fetchSummaryAudioUrl(
  imageId: string,
  language: string,
  token: string,
  contentVersion?: string,
): Promise<string> {
  const response = await fetch(summaryAudioUrl(imageId, language, contentVersion), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  })
  if (!response.ok) throw new Error(`No audio clip (${response.status})`)
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}

/**
 * Fetches the stored Grad-CAM heatmap as a blob and returns an object URL.
 * The served endpoint is bearer-auth protected, so it cannot be <img>-tagged
 * directly without a token.
 */
export async function fetchGradcamBlobUrl(
  imageId: string,
  token: string,
): Promise<string | null> {
  const response = await fetch(reportsApi.gradcamUrl(imageId), {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) return null
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}

export function scanImageUrl(imageId: string): string {
  return `${API_BASE_URL}/uploads/${imageId}/image`
}

/**
 * Fetches a stored scan as a blob and returns an object URL. Must be called
 * from the browser because it authenticates with the session bearer token,
 * which an <img src> request cannot supply.
 */
export async function fetchScanBlobUrl(
  imageId: string,
  token: string,
): Promise<string> {
  const response = await fetch(scanImageUrl(imageId), {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new Error(`Unable to load scan image (${response.status})`)
  }
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}