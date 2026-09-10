"""
RetinaShield — Audit, Retention, Privacy & Backup Test Suite

Tests:
- PII scrubbing log filter (redacting Indian phone numbers, Aadhaar patterns, tokens, passwords).
- Security audit event logging without PII leakage.
- Soft-deletion and DPDP Right-to-Erasure execution.
- Backup creation with SHA-256 manifests and recovery verification.
"""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
from pathlib import Path
from PIL import Image as PILImage

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.logging_filter import PIIScrubbingFilter
from app.core.security import hash_password, create_access_token
from app.db.session import Base, get_db
from app.models.user import User, UserRole
from app.models.patient import Patient
from app.models.screening import Screening, ScreeningImage
from app.models.audit import AuditEvent
from app.services.retention_service import retention_service
from app.services.backup_service import backup_service
from app.services.image_store import image_store
from app.main import app


class TestAuditAndRetention(unittest.IsolatedAsyncioTestCase):
    """Test suite for privacy, audit trails, data retention, and backup recovery."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_audit.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def override_get_db():
            async with self.session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()

        app.dependency_overrides[get_db] = override_get_db

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    def test_pii_scrubbing_filter(self):
        """Verify PIIScrubbingFilter removes sensitive phone numbers, Aadhaar patterns, and tokens."""
        f = PIIScrubbingFilter()

        # 1. Indian mobile phone numbers
        msg1 = "Screening for patient with contact 9876543210 completed"
        self.assertEqual(
            f.sanitize_message(msg1),
            "Screening for patient with contact [REDACTED_PHONE] completed",
        )

        # 2. 12-digit Aadhaar pattern
        msg2 = "Audit record for Aadhaar 1234 5678 9012"
        self.assertEqual(
            f.sanitize_message(msg2),
            "Audit record for Aadhaar [REDACTED_AADHAAR]",
        )

        # 3. Bearer tokens
        msg3 = "Incoming request with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abc_def"
        self.assertEqual(
            f.sanitize_message(msg3),
            "Incoming request with Bearer [REDACTED_TOKEN]",
        )

        # 4. Passwords
        msg4 = "User auth failed with password: SecretPassword123!"
        self.assertIn("[REDACTED]", f.sanitize_message(msg4))

    async def test_audit_event_logging_and_admin_query(self):
        """Verify security audit events are stored and accessible only to administrators."""
        async with self.session_factory() as session:
            admin = User(
                username="admin_auditor",
                email="audit@admin.org",
                full_name="Chief Auditor",
                role=UserRole.ADMINISTRATOR,
                password_hash=hash_password("AuditPass@2026"),
                is_active=True,
            )
            hw = User(
                username="hw_field",
                email="hw@field.org",
                full_name="Field Worker",
                role=UserRole.HEALTH_WORKER,
                password_hash=hash_password("FieldPass@2026"),
                is_active=True,
            )
            session.add_all([admin, hw])
            await session.flush()

            # Seed audit event
            ev = AuditEvent(
                user_id=hw.id,
                facility_id="PHC-PUNE",
                event_type="patient_registered",
                resource_type="patient",
                resource_id=str(uuid.uuid4()),
                details={"patient_gender": "Female"},
            )
            session.add(ev)
            await session.commit()

            admin_id = str(admin.id)
            hw_id = str(hw.id)

        admin_token = create_access_token(subject=admin_id, role="administrator")
        hw_token = create_access_token(subject=hw_id, role="health-worker")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Non-admin attempts to view audit trail -> 403 Forbidden
            hw_resp = await client.get(
                "/api/audit/",
                headers={"Authorization": f"Bearer {hw_token}"},
            )
            self.assertEqual(hw_resp.status_code, 403)

            # Admin queries audit trail -> 200 OK
            admin_resp = await client.get(
                "/api/audit/",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self.assertEqual(admin_resp.status_code, 200)
            events = admin_resp.json()
            self.assertGreaterEqual(len(events), 1)
            self.assertTrue(any(e["event_type"] == "patient_registered" for e in events))

    async def test_soft_delete_and_dpdp_right_to_erasure(self):
        """Verify soft deletion preserves records, while DPDP Right-to-Erasure purges files and records."""
        # Create dummy image on disk via image_store
        img = PILImage.new("RGB", (600, 600), color=(100, 100, 100))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        store_meta = await image_store.store_image(buf.getvalue(), "dpdp_test.jpg", "image/jpeg")

        async with self.session_factory() as session:
            patient = Patient(first_name="Pooja", last_name="Joshi", facility_id="PHC-DELHI")
            session.add(patient)
            await session.flush()

            screening = Screening(patient_id=patient.id, facility_id="PHC-DELHI", eye="right")
            session.add(screening)
            await session.flush()

            img_rec = ScreeningImage(
                screening_id=screening.id,
                original_filename="dpdp_test.jpg",
                stored_filename=store_meta["stored_filename"],
                storage_path=store_meta["storage_path"],
                content_type="image/jpeg",
                eye="right",
                width=600,
                height=600,
                file_size_bytes=store_meta["file_size_bytes"],
            )
            session.add(img_rec)

            admin = User(
                username="admin_dpo",
                email="dpo@retina.org",
                full_name="Data Protection Officer",
                role=UserRole.ADMINISTRATOR,
                password_hash=hash_password("DpoPass@2026"),
                is_active=True,
            )
            session.add(admin)
            await session.commit()

            patient_id = patient.id
            screening_id = screening.id
            admin_id = admin.id
            stored_file = store_meta["stored_filename"]

        # 1. Test Soft Deletion
        async with self.session_factory() as session:
            soft_success = await retention_service.soft_delete_patient(
                db=session, patient_id=patient_id, reason="Temporary removal"
            )
            self.assertTrue(soft_success)
            await session.commit()

            # Verify soft-deleted
            p = await session.get(Patient, patient_id)
            self.assertTrue(p.is_deleted)
            s = await session.get(Screening, screening_id)
            self.assertTrue(s.is_deleted)

        # 2. Test DPDP Right-to-Erasure Hard Purge
        async with self.session_factory() as session:
            purge_res = await retention_service.execute_dpdp_right_to_erasure(
                db=session,
                patient_id=patient_id,
                requested_by_user_id=admin_id,
                reason="Patient withdrew consent and requested erasure under DPDP Act 2023",
            )
            self.assertEqual(purge_res["status"], "purged")
            self.assertEqual(purge_res["deleted_images_count"], 1)
            await session.commit()

            # Verify database records are deleted
            p_check = await session.get(Patient, patient_id)
            self.assertIsNone(p_check)
            s_check = await session.get(Screening, screening_id)
            self.assertIsNone(s_check)

            # Verify file is deleted from disk
            with self.assertRaises(FileNotFoundError):
                await image_store.retrieve_image(stored_file)

    async def test_backup_and_recovery_verification(self):
        """Verify backup creation with SHA-256 manifests and recovery integrity verification."""
        # Create dummy image
        img = PILImage.new("RGB", (512, 512), color=(50, 80, 120))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        store_meta = await image_store.store_image(buf.getvalue(), "backup_test.jpg", "image/jpeg")

        async with self.session_factory() as session:
            patient = Patient(first_name="Ravi", last_name="Nair")
            session.add(patient)
            await session.flush()

            screening = Screening(patient_id=patient.id, eye="left")
            session.add(screening)
            await session.flush()

            img_rec = ScreeningImage(
                screening_id=screening.id,
                original_filename="backup_test.jpg",
                stored_filename=store_meta["stored_filename"],
                storage_path=store_meta["storage_path"],
                content_type="image/jpeg",
                eye="left",
                width=512,
                height=512,
                file_size_bytes=store_meta["file_size_bytes"],
            )
            session.add(img_rec)
            await session.commit()

            # 1. Create backup
            backup_info = await backup_service.create_backup(db=session, backup_label="test_run")
            self.assertIn("backup_filename", backup_info)
            self.assertGreaterEqual(backup_info["archived_images_count"], 1)
            backup_path = backup_info["backup_path"]

        # 2. Verify backup integrity
        verify_res = backup_service.verify_backup_integrity(backup_path)
        self.assertEqual(verify_res["status"], "verified")
        self.assertGreaterEqual(verify_res["verified_files_count"], 1)
