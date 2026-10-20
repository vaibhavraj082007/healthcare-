from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_roles
from ..models import AIFinding, CaseTracking, ImageUpload, Patient, User
from ..schemas import (
    PatientCaseOut,
    PatientCreate,
    PatientLogin,
    PatientOut,
    UploadOut,
)
from ..security import hash_password

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=list[PatientOut])
def list_patients(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "health_worker", "doctor")),
):
    if user.role == "health_worker":
        return db.query(Patient).filter(Patient.created_by == user.id).all()
    return db.query(Patient).all()


@router.get("/self", response_model=PatientOut)
def my_record(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("patient")),
):
    patient = db.query(Patient).filter(Patient.own_user_id == user.id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="No patient record linked to this account")
    # materialize most recent upload
    uploads = (
        db.query(ImageUpload)
        .filter(ImageUpload.patient_id == patient.id)
        .order_by(ImageUpload.uploaded_at.desc())
        .all()
    )
    patient.latest_upload = uploads[0] if uploads else None  # type: ignore[attr-defined]
    return patient


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "health_worker")),
):
    data = payload.model_dump()
    email = data.pop("email", None)
    password = data.pop("password", None)
    if (email is None) != (password is None):
        raise HTTPException(
            status_code=400,
            detail="Provide both email and password, or neither",
        )

    account: User | None = None
    if email is not None and password is not None:
        normalized = email.lower().strip()
        if db.query(User).filter(User.email == normalized).first():
            raise HTTPException(status_code=400, detail="Email already registered")
        if len(password) < 8:
            raise HTTPException(
                status_code=400,
                detail="Password must be at least 8 characters",
            )
        account = User(
            email=normalized,
            full_name=payload.full_name.strip(),
            role="patient",
            hashed_password=hash_password(password),
        )
        db.add(account)
        db.flush()

    patient = Patient(
        **data,
        created_by=user.id,
        own_user_id=account.id if account else None,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if user.role == "health_worker" and patient.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this patient")
    return patient


@router.get("/{patient_id}/case", response_model=PatientCaseOut)
def patient_latest_case(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Live case snapshot for the ASHA worker dashboard (status + band).

    A worker sees it only for patients they registered; patients are denied.
    """
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if user.role == "health_worker" and patient.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this patient")

    upload = (
        db.query(ImageUpload)
        .filter(ImageUpload.patient_id == patient.id)
        .order_by(ImageUpload.uploaded_at.desc())
        .first()
    )
    if upload is None:
        return PatientCaseOut(has_case=False, status="None")

    finding = (
        db.query(AIFinding)
        .filter(
            AIFinding.image_id == upload.image_id,
            AIFinding.analysis_status == "completed",
        )
        .first()
    )
    if finding is None:
        return PatientCaseOut(
            image_id=upload.image_id,
            has_case=False,
            status="None",
        )

    case = (
        db.query(CaseTracking)
        .filter(CaseTracking.image_id == finding.image_id)
        .first()
    )
    if case is None:
        return PatientCaseOut(
            image_id=finding.image_id,
            has_case=False,
            status="None",
        )

    updated_at = case.reviewed_at or case.contacted_at or case.claimed_at or case.created_at
    return PatientCaseOut(
        image_id=finding.image_id,
        status=case.status,
        severity_band=case.severity_band,
        flagged=(case.severity_band == "High"),
        has_case=True,
        updated_at=updated_at,
    )


@router.get("/{patient_id}/scans", response_model=list[UploadOut])
def patient_scans(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if user.role == "patient" and patient.own_user_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this patient")
    if user.role == "health_worker" and patient.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this patient")
    return (
        db.query(ImageUpload)
        .filter(ImageUpload.patient_id == patient.id)
        .order_by(ImageUpload.uploaded_at.desc())
        .all()
    )


@router.post("/{patient_id}/login", response_model=PatientOut)
def add_patient_login(
    patient_id: int,
    payload: PatientLogin,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "health_worker")),
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if user.role == "health_worker" and patient.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to edit this patient")
    if patient.own_user_id is not None:
        raise HTTPException(status_code=400, detail="Patient already has a login")

    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters",
        )

    account = User(
        email=email,
        full_name=patient.full_name,
        role="patient",
        hashed_password=hash_password(payload.password),
    )
    db.add(account)
    db.flush()
    patient.own_user_id = account.id
    db.commit()
    db.refresh(patient)
    return patient