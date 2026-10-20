from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, computed_field


# ---------- Auth ----------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str


class UserRegister(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: str = "patient"  # patient | health_worker | doctor


# ---------- Patients ----------
class PatientCreate(BaseModel):
    full_name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    phone: Optional[str] = None
    # Optional login for the patient. Provide both or neither.
    email: Optional[EmailStr] = None
    password: Optional[str] = None


class PatientLogin(BaseModel):
    email: EmailStr
    password: str


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    phone: Optional[str] = None
    created_at: datetime
    own_user_id: Optional[int] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_login(self) -> bool:
        return self.own_user_id is not None


# ---------- Uploads ----------
class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    image_id: str
    lesion_list: Any = []
    lesion_count: int = 0
    icdr_grade: Optional[int] = None
    icdr_confidence: Optional[float] = None
    consistency_status: str = "pending"
    analysis_status: str = "queued"
    analyzed_at: Optional[datetime] = None
    model_provenance: Optional[str] = None


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    image_id: str
    patient_id: int
    filename: str
    quality_status: str
    quality_score: Optional[float] = None
    retake_count: int = 0
    eye_laterality: str = "unknown"
    uploaded_at: datetime

    findings: list[FindingOut] = []


# ---------- Dashboard ----------
class RoleStats(BaseModel):
    total_patients: int
    total_scans: int
    scans_analyzed: int
    scans_pending: int
    flagged_for_review: int
    grade_distribution: dict[int, int] = {}


class ModelInfo(BaseModel):
    name: str
    family: str
    task: str
    trained_on: str
    fine_tuned: bool
    weights: bool
    weights_path: str
    validation: dict[str, Any] = {}
    note: str


# ---------- Phase 3 — Explainable reports ----------
class ReportOut(BaseModel):
    image_id: str
    report_text: str
    structured_findings: dict[str, Any] = {}
    region_notes: Optional[str] = None
    gradcam_path: Optional[str] = None
    generation_method: str = "template"
    model_version: Optional[str] = None
    generated_at: Optional[datetime] = None
    # Universal report format (Phase-4-A fixes) — demographics snapshot frozen
    # at generation time plus the sectioned Findings/Observations/Recommendation.
    header: Optional[dict[str, Any]] = None
    observations: list[str] = []
    recommendation: Optional[str] = None
    disclaimer: Optional[str] = None
    # Both images that belong to this exact report/case: the stored fundus scan
    # and its Grad-CAM explainability heatmap. Both are keyed by image_id (never
    # hard-coded) and both endpoints re-check patient ownership server-side.
    # heatmap_image_url is None when no heatmap was ever generated for this scan
    # (the UI must show an explicit notice, never a placeholder image).
    image_urls: dict[str, Optional[str]] = {}
    fundus_image_url: Optional[str] = None
    heatmap_image_url: Optional[str] = None


# ---------- Phase 4 — Telemedicine ----------
class DoctorQueueItem(BaseModel):
    image_id: str
    patient_id: int
    patient_name: str
    icdr_grade: Optional[int] = None
    icdr_confidence: Optional[float] = None
    consistency_status: str = "pending"
    sync_status: str = "queued"  # queued | syncing | synced | failed
    viewed: bool = False
    signed_off: bool = False
    signed_decision: Optional[str] = None
    analyzed_at: Optional[datetime] = None


class DoctorQueueCount(BaseModel):
    unseen: int
    unseen_flagged: int


class SignOffIn(BaseModel):
    image_id: str
    decision: str  # Approved | Revised | Rejected
    doctor_notes: Optional[str] = None
    revised_grade: Optional[int] = None  # required when decision == "Revised"


class SignOffOut(BaseModel):
    image_id: str
    decision: str
    doctor_notes: Optional[str] = None
    revised_grade: Optional[int] = None
    signed_at: datetime
    summary_languages: list[str] = []


class SyncStatus(BaseModel):
    pending: int
    syncing: int
    synced: int
    failed: int
    total: int
    offline_sim: bool


class OfflineSimIn(BaseModel):
    enabled: bool


class PatientStatusOut(BaseModel):
    image_id: str
    state: str  # scan_received | analysis_in_progress | awaiting_review | reviewed
    stage_label: str
    patient_text: str
    summary_languages: list[str] = []
    signed_off: bool = False
    signed_decision: Optional[str] = None
    revised_grade: Optional[int] = None


class SummaryOut(BaseModel):
    language: str
    summary_text: str
    has_audio: bool = False
    content_version: str | None = None


# ---------- Phase 4 Part A — Case tracking (doctor portal / ASHA bridge) ----------
class CaseListItem(BaseModel):
    image_id: str
    patient_id: int
    patient_name: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    phc: Optional[str] = None
    icdr_grade: Optional[int] = None
    icdr_confidence: Optional[float] = None
    consistency_status: str = "pending"
    severity_band: str = "Low"  # Low | Medium | High
    status: str = "New"  # New | Claimed | Contacted | Reviewed
    flagged: bool = False
    assigned_doctor_id: Optional[int] = None
    assigned_doctor_name: Optional[str] = None
    worker_id: Optional[int] = None
    worker_name: Optional[str] = None
    has_report: bool = False
    signed_off: bool = False
    analyzed_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    contacted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class CaseSummaryOut(BaseModel):
    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    flagged_pending: int = 0
    awaiting_review: int = 0
    claimed_by_me: int = 0
    today_reported: int = 0
    today_reviewed: int = 0


class CaseNoteOut(BaseModel):
    id: int
    image_id: str
    author_id: int
    author_name: str
    body: str
    created_at: datetime


class CaseNoteIn(BaseModel):
    body: str


class CaseStatusIn(BaseModel):
    status: str  # Claimed | Contacted | Reviewed


class CaseDetailOut(CaseListItem):
    phone: Optional[str] = None
    lesion_count: Optional[int] = None
    lesion_list: Any = None
    sync_status: str = "queued"
    report_generation_method: Optional[str] = None
    sign_off: Optional[dict[str, Any]] = None
    notes: list[CaseNoteOut] = []


class NlSearchIn(BaseModel):
    query: str


class NlSearchOut(BaseModel):
    query: str
    matched: bool = False
    filter: Optional[dict[str, Any]] = None
    message: str = ""
    items: list[CaseListItem] = []


class PatientCaseOut(BaseModel):
    image_id: Optional[str] = None
    status: str = "None"
    severity_band: Optional[str] = None
    flagged: bool = False
    has_case: bool = False
    updated_at: Optional[datetime] = None


TokenResponse.model_rebuild()