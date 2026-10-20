"""Seeds the database with demo accounts and a handful of patients/scans.

Run:  python -m app.seed   (from the backend/ directory)
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .database import Base, SessionLocal, engine
from .models import AIFinding, ImageUpload, Patient, User
from .security import hash_password

DEMO_USERS = [
    {
        "email": "admin@netrascan.in",
        "full_name": "NetraScan Administrator",
        "role": "admin",
        "password": "Admin123!",
    },
    {
        "email": "patient@example.org",
        "full_name": "Anita Sharma",
        "role": "patient",
        "password": "Patient123!",
    },
    {
        "email": "mo.faizal@example.org",
        "full_name": "Mohammed Faizal",
        "role": "patient",
        "password": "Faizal123!",
    },
    {
        "email": "lakshmi@example.org",
        "full_name": "Lakshmi Devi",
        "role": "patient",
        "password": "Lakshmi123!",
    },
    {
        "email": "aapti@example.org",
        "full_name": "Aapti Vishwakarma",
        "role": "patient",
        "password": "Aapti123!",
    },
    {
        "email": "worker@example.org",
        "full_name": "Ravi Kumar",
        "role": "health_worker",
        "password": "Worker123!",
    },
    {
        "email": "doctor@example.org",
        "full_name": "Dr. Meera Iyer",
        "role": "doctor",
        "password": "Doctor123!",
    },
    {
        "email": "ophthalmologist@netrascan.in",
        "full_name": "Dr. Anand Deshpande",
        "role": "ophthalmologist",
        "password": "Doctor123!",
    },
]


def _seed_demo_scans(db, worker, anita):
    """Populate demo scans/findings from backend/demo_samples/manifest.json so the
    dashboards and review queue aren't empty on first load."""
    samples_dir = Path(__file__).resolve().parent.parent / "demo_samples"
    manifest_path = samples_dir / "manifest.json"
    if not manifest_path.exists():
        print("  (demo_samples/manifest.json not found — skipping demo scans)")
        return

    patients = [p for p in (anita,) + tuple(
        db.query(Patient).filter(Patient.phone.like("+91 90000 0000%")).all()
    ) if p is not None]
    manifest = json.loads(manifest_path.read_text())

    for idx, sample in enumerate(manifest):
        image_id = "demo" + uuid.uuid4().hex[:12]
        file_path = str(samples_dir / sample["file"])
        patient = patients[idx % len(patients)]
        existing = db.query(ImageUpload).filter(ImageUpload.file_path == file_path).first()
        if existing:
            continue

        upload = ImageUpload(
            image_id=image_id,
            patient_id=patient.id,
            uploaded_by=worker.id,
            filename=sample["file"],
            file_path=file_path,
            quality_status=sample["quality_status"],
            quality_score=sample["quality_score"],
            retake_count=1 if sample["quality_status"] == "poor" else 0,
            eye_laterality=("od", "os", "os", "od", "ou")[idx % 5],
            uploaded_at=datetime.utcnow() - timedelta(hours=idx),
        )
        db.add(upload)

        if sample["quality_status"] == "poor":
            db.add(AIFinding(image_id=image_id, analysis_status="queued"))
            continue

        grade = int(sample["diagnosis"])
        # Sim plesion load that keeps the dual-engine check consistent for most
        # samples, but hands the review queue a couple of genuinely flagged cases.
        rules = {
            0: ([], "Consistent"),
            1: ([{"type": "microaneurysm", "count": 3}], "Consistent"),
            2: (
                [{"type": "microaneurysm", "count": 12}, {"type": "hemorrhage", "count": 4}],
                "Consistent",
            ),
            3: (
                [
                    {"type": "microaneurysm", "count": 18},
                    {"type": "hemorrhage", "count": 9},
                    {"type": "hard_exudate", "count": 11},
                    {"type": "soft_exudate", "count": 2},
                ],
                "Consistent",
            ),
            4: (
                [
                    {"type": "microaneurysm", "count": 2},
                    {"type": "hemorrhage", "count": 1},
                ],
                "Flagged for Review",
            ),
        }
        lesion_list, consistency = rules[grade]
        provenance = {
            "classifier": {
                "model": "EfficientNet-B0",
                "trained_on": "APTOS 2019 Blindness Detection",
                "validation_qwk": 0.81,
            },
            "detector": "YOLOv8n fine-tuned on IDRiD (demo seed)",
        }
        db.add(
            AIFinding(
                image_id=image_id,
                lesion_list=json.dumps(lesion_list),
                lesion_count=sum(l["count"] for l in lesion_list),
                icdr_grade=grade,
                icdr_confidence=0.75 + (idx % 3) * 0.08,
                consistency_status=consistency,
                analysis_status="completed",
                model_provenance=json.dumps(provenance),
                analyzed_at=datetime.utcnow() - timedelta(hours=idx),
            )
        )

    db.commit()
    print(f"  Seeded {len(manifest)} demo scans (10 graded + poor retake exercises).")


def _ensure_retake_column():
    from sqlalchemy import text

    with engine.connect() as conn:
        for stmt in (
            "ALTER TABLE image_uploads ADD COLUMN retake_count INTEGER DEFAULT 0",
            "ALTER TABLE image_uploads ADD COLUMN eye_laterality VARCHAR DEFAULT 'unknown'",
        ):
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists


def seed():
    Base.metadata.create_all(bind=engine)
    _ensure_retake_column()
    db = SessionLocal()
    try:
        users = {}
        users_by_email = {}
        for spec in DEMO_USERS:
            existing = db.query(User).filter(User.email == spec["email"]).first()
            if existing:
                users[spec["role"]] = existing
                users_by_email[spec["email"]] = existing
                continue
            user = User(
                email=spec["email"],
                full_name=spec["full_name"],
                role=spec["role"],
                hashed_password=hash_password(spec["password"]),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            users[spec["role"]] = user
            users_by_email[spec["email"]] = user

        worker = users["health_worker"]
        anita = db.query(Patient).filter(
            Patient.own_user_id == users_by_email["patient@example.org"].id
        ).first()
        if anita is None:
            anita = Patient(
                full_name="Anita Sharma",
                age=54,
                gender="Female",
                village="Rampur",
                district="Sitapur",
                phone="+91 90000 00001",
                own_user_id=users["patient"].id,
                created_by=worker.id,
            )
            db.add(anita)

        demo_patients = [
            {
                "full_name": "Mohammed Faizal",
                "age": 61,
                "gender": "Male",
                "village": "Kalluvathukkal",
                "district": "Kollam",
                "phone": "+91 90000 00002",
                "login_email": "mo.faizal@example.org",
            },
            {
                "full_name": "Lakshmi Devi",
                "age": 47,
                "gender": "Female",
                "village": "Baramati",
                "district": "Pune",
                "phone": "+91 90000 00003",
                "login_email": "lakshmi@example.org",
            },
            {
                "full_name": "Aapti Vishwakarma",
                "age": 39,
                "gender": "Female",
                "village": "Jaynagar",
                "district": "Madhubani",
                "phone": "+91 90000 00004",
                "login_email": "aapti@example.org",
            },
        ]
        for spec in demo_patients:
            existing = db.query(Patient).filter(Patient.phone == spec["phone"]).first()
            login_email = spec.pop("login_email")
            if existing:
                if existing.own_user_id is None and login_email in users_by_email:
                    existing.own_user_id = users_by_email[login_email].id
            else:
                owner = users_by_email.get(login_email)
                db.add(
                    Patient(
                        **spec,
                        created_by=worker.id,
                        own_user_id=owner.id if owner else None,
                    )
                )

        db.commit()
        _seed_demo_scans(db, worker, anita)
        _seed_phase4_rows(db, users.get("ophthalmologist"))
        print("Seeded demo accounts:")
        for spec in DEMO_USERS:
            print(f"  {spec['role']:<13} {spec['email']:<30} {spec['password']}")
        print("Done.")
    finally:
        db.close()


def _seed_phase4_rows(db, ophthalmologist):
    """Phase 4 — pre-synced queue + one signed-off case with patient summary,
    so the doctor review portal, notifications and patient stages are all
    demonstrable without waiting for real transmissions."""
    from datetime import datetime

    from .ml.summaries import create_summaries
    from .models import SignOff, SyncQueue

    if ophthalmologist is None:
        return

    completed = db.query(AIFinding).filter(AIFinding.analysis_status == "completed").all()
    for f in completed:
        if db.query(SyncQueue).filter(SyncQueue.image_id == f.image_id).first() is None:
            db.add(
                SyncQueue(
                    image_id=f.image_id,
                    status="synced",
                    synced_at=f.analyzed_at or datetime.utcnow(),
                )
            )
    db.commit()

    # Sign off one clean case so the sealed loop is already visible.
    target = (
        db.query(AIFinding)
        .filter(AIFinding.analysis_status == "completed", AIFinding.icdr_grade == 0)
        .first()
    )
    if target is None:
        return
    existing = db.query(SignOff).filter(SignOff.image_id == target.image_id).first()
    if existing is not None:
        return
    sign = SignOff(
        image_id=target.image_id,
        ophthalmologist_id=ophthalmologist.id,
        decision="Approved",
        doctor_notes=(
            "Grading consistent with the lesion detector; no retinopathy. "
            "Routine 12-month screening interval is appropriate."
        ),
        signed_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.add(sign)
    db.commit()
    db.refresh(sign)
    create_summaries(db, target.image_id, sign, ai_grade=int(target.icdr_grade or 0))
    print(f"  Phase 4: {len(completed)} cases pre-synced into the doctor queue; "
          f"{target.image_id} signed off (Approved).")


if __name__ == "__main__":
    seed()