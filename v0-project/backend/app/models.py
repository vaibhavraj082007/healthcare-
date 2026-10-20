from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # patient | health_worker | doctor | admin
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patients = relationship("Patient", back_populates="owner", foreign_keys="Patient.created_by")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    age = Column(Integer, nullable=True)
    gender = Column(String, nullable=True)
    village = Column(String, nullable=True)
    district = Column(String, nullable=True)
    phone = Column(String, nullable=True, unique=True)
    own_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="patients", foreign_keys=[created_by])
    uploads = relationship(
        "ImageUpload", back_populates="patient", cascade="all, delete-orphan"
    )


class ImageUpload(Base):
    __tablename__ = "image_uploads"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(String, unique=True, index=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    quality_status = Column(String, default="pending")  # pending | acceptable | poor
    quality_score = Column(Float, nullable=True)
    retake_count = Column(Integer, default=0)  # consecutive failed capture attempts
    eye_laterality = Column(String, default="unknown")  # od | os | ou | unknown
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="uploads")
    uploaded_by_user = relationship("User")
    findings = relationship(
        "AIFinding", back_populates="image", cascade="all, delete-orphan"
    )


class AIFinding(Base):
    __tablename__ = "ai_findings"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        String, ForeignKey("image_uploads.image_id"), index=True, nullable=False
    )
    lesion_list = Column(Text, default="[]")  # JSON array of {type, count}
    lesion_count = Column(Integer, default=0)
    icdr_grade = Column(Integer, nullable=True)
    icdr_confidence = Column(Float, nullable=True)
    consistency_status = Column(String, default="pending")  # Consistent | Flagged for Review
    analysis_status = Column(String, default="queued")  # queued | running | completed | failed
    model_provenance = Column(Text, default="{}")  # JSON describing engines used
    model_version = Column(String, nullable=True)  # engine signature used for this analysis
    error = Column(Text, nullable=True)
    analyzed_at = Column(DateTime, nullable=True)

    image = relationship("ImageUpload", back_populates="findings")
    report = relationship("ScreeningReport", back_populates="finding", uselist=False)


class ScreeningReport(Base):
    """Phase 3 — explainable AI screening report, generated once and cached.

    Persisted so the Grad-CAM heatmap and the plain-language report are not
    regenerated on every page view. Invalidated by a model_version mismatch: if
    the image is re-analyzed with a different engine signature the report is
    rebuilt in place.
    """

    __tablename__ = "screening_reports"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        String, ForeignKey("ai_findings.image_id"), unique=True, index=True, nullable=False
    )
    report_text = Column(Text, nullable=False)
    structured_findings = Column(Text, default="{}")  # JSON — clinician-facing object
    region_notes = Column(Text, nullable=True)  # computed heatmap region description
    gradcam_path = Column(String, nullable=True)  # null when heatmap computation failed
    generation_method = Column(String, default="template")  # template | llm
    model_version = Column(String, nullable=True)
    generated_at = Column(DateTime, default=datetime.utcnow)
    # Universal report header — demographics snapshot taken at generation time so
    # the report never silently changes if the patient profile is edited later.
    patient_id = Column(Integer, nullable=True)
    patient_name = Column(String, nullable=True)
    patient_age = Column(Integer, nullable=True)
    patient_gender = Column(String, nullable=True)
    referring_phc = Column(String, nullable=True)  # village, district snapshot
    submitting_worker = Column(String, nullable=True)  # ASHA worker full name
    scan_date = Column(DateTime, nullable=True)  # date of scan (analyzed time)
    eye_laterality = Column(String, nullable=True)  # OD | OS — currently not captured
    image_quality = Column(String, nullable=True)  # acceptable | poor | pending snapshot
    quality_score = Column(Float, nullable=True)  # focus score snapshot

    finding = relationship("AIFinding", back_populates="report")


class SyncQueue(Base):
    """Phase 4 — store-and-forward sync queue (backend-side, per spec §1).

    The prototype runs the PHC instance and the "telemedicine server" as one
    backend, so transmission is an internal state transition (queued ->
    syncing -> synced) rather than a network call. Idempotent by image_id.
    """

    __tablename__ = "sync_queue"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        String, ForeignKey("ai_findings.image_id"), unique=True, index=True, nullable=False
    )
    status = Column(String, default="queued")  # queued | syncing | synced | failed
    attempt_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    viewed_at = Column(DateTime, nullable=True)  # set when an ophthalmologist opens the case
    created_at = Column(DateTime, default=datetime.utcnow)


class SignOff(Base):
    """Phase 4 — auditable ophthalmologist sign-off (never a plain boolean).

    Approved: the AI grading/report stands. Revised: the doctor overrides the
    ICDR grade — the AI's original grade stays in ai_findings, the doctor's in
    revised_grade, so the disagreement is preserved (a natural future retraining
    signal, documented in the README). Rejected: case invalid, reason recorded.
    """

    __tablename__ = "sign_offs"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        String, ForeignKey("ai_findings.image_id"), unique=True, index=True, nullable=False
    )
    ophthalmologist_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(String, nullable=False)  # Approved | Revised | Rejected
    doctor_notes = Column(Text, nullable=True)
    revised_grade = Column(Integer, nullable=True)  # populated only when Revised
    signed_at = Column(DateTime, default=datetime.utcnow)


class PatientSummary(Base):
    """Phase 4 — post-sign-off patient summary, local-language + offline audio."""

    __tablename__ = "patient_summaries"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(String, ForeignKey("ai_findings.image_id"), index=True, nullable=False)
    language = Column(String, nullable=False)  # en | hi
    summary_text = Column(Text, nullable=False)
    audio_path = Column(String, nullable=True)  # pre-generated offline clip
    generated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("image_id", "language"),)


class CaseTracking(Base):
    """Phase 4 Part A — operational case tracking for a screened image.

    One row per completed AI finding, created the moment the screening report
    exists. severity_band is derived from the ICDR grade (0–1 Low, 2 Medium,
    3–4 High) and forced to High when the dual-engine check flagged the image.
    status marches New -> Claimed -> Contacted -> Reviewed.
    """

    __tablename__ = "case_tracking"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        String, ForeignKey("ai_findings.image_id"), unique=True, index=True, nullable=False
    )
    severity_band = Column(String, nullable=False, default="Low")  # Low | Medium | High
    status = Column(String, nullable=False, default="New")  # New | Claimed | Contacted | Reviewed
    assigned_doctor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    claimed_at = Column(DateTime, nullable=True)
    contacted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    notes = relationship("CaseNote", back_populates="case", cascade="all, delete-orphan")


class CaseNote(Base):
    """Phase 4 Part A — chronological collaboration thread on a tracked case.

    Both the reviewing clinician and the ASHA worker who registered the patient
    can append notes. Never edited or deleted after posting (audit trail).
    """

    __tablename__ = "case_notes"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(
        String, ForeignKey("case_tracking.image_id"), index=True, nullable=False
    )
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    author_name = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    case = relationship("CaseTracking", back_populates="notes")