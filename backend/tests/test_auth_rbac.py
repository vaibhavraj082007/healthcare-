"""
RetinaShield — Staff Authentication & RBAC Test Suite

Tests:
- Argon2id password hashing and verification.
- Signed JWT issuance and claim validation.
- Staff login endpoint.
- Administrator-controlled provisioning and privileged role assignments.
- Rejection of unauthorized role escalation.
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.security import hash_password, verify_password, create_access_token, decode_access_token
from app.db.session import Base, get_db
from app.models.user import User, UserRole
from app.models.facility import Facility
from app.main import app


class TestAuthRBAC(unittest.IsolatedAsyncioTestCase):
    """Test suite for staff authentication and role-based access control."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_auth.db"
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

    def test_argon2id_hashing(self):
        """Verify Argon2id password hashing and comparison."""
        password = "StrongStaffPassword@2026"
        pw_hash = hash_password(password)

        self.assertTrue(pw_hash.startswith("$argon2id$"))
        self.assertTrue(verify_password(password, pw_hash))
        self.assertFalse(verify_password("WrongPassword", pw_hash))
        self.assertFalse(verify_password("", pw_hash))

    def test_jwt_token_claims(self):
        """Verify JWT claims encoding and decoding."""
        user_id = str(uuid.uuid4())
        token = create_access_token(
            subject=user_id,
            role="health-worker",
            facility_id="PHC-PUNE-01",
        )

        claims = decode_access_token(token)
        self.assertEqual(claims["sub"], user_id)
        self.assertEqual(claims["role"], "health-worker")
        self.assertEqual(claims["facility_id"], "PHC-PUNE-01")
        self.assertEqual(claims["iss"], "retinashield-auth")

    async def test_staff_login_and_me(self):
        """Test staff login flow and me endpoint."""
        async with self.session_factory() as session:
            fac = Facility(facility_code="PHC-001", name="Primary Health Centre 1")
            session.add(fac)
            hw = User(
                username="hw_rani",
                email="rani@phc.org",
                full_name="Rani Devi",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-001",
                password_hash=hash_password("WorkerSecurePass123"),
                is_active=True,
            )
            session.add(hw)
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Invalid login
            bad_resp = await client.post(
                "/api/auth/login",
                json={"username": "hw_rani", "password": "WrongPassword!"},
            )
            self.assertEqual(bad_resp.status_code, 401)

            # 2. Valid login
            login_resp = await client.post(
                "/api/auth/login",
                json={"username": "hw_rani", "password": "WorkerSecurePass123"},
            )
            self.assertEqual(login_resp.status_code, 200)
            data = login_resp.json()
            self.assertIn("access_token", data)
            self.assertEqual(data["role"], "health-worker")
            self.assertEqual(data["facility_id"], "PHC-001")

            token = data["access_token"]

            # 3. Access /me
            me_resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(me_resp.status_code, 200)
            me_data = me_resp.json()
            self.assertEqual(me_data["username"], "hw_rani")
            self.assertEqual(me_data["role"], "health-worker")

    async def test_admin_staff_provisioning_and_rbac(self):
        """Verify administrator provisions staff, and non-admin cannot provision."""
        async with self.session_factory() as session:
            admin = User(
                username="admin_super",
                email="admin@retina.org",
                full_name="Admin Chief",
                role=UserRole.ADMINISTRATOR,
                password_hash=hash_password("AdminPass@2026"),
                is_active=True,
            )
            hw = User(
                username="hw_user",
                email="hw@retina.org",
                full_name="Health Worker",
                role=UserRole.HEALTH_WORKER,
                password_hash=hash_password("HwPass@2026"),
                is_active=True,
            )
            session.add_all([admin, hw])
            await session.commit()
            admin_id = str(admin.id)
            hw_id = str(hw.id)

        admin_token = create_access_token(subject=admin_id, role="administrator")
        hw_token = create_access_token(subject=hw_id, role="health-worker")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Non-admin attempts to provision staff -> 403 Forbidden
            hw_try = await client.post(
                "/api/auth/users",
                json={
                    "username": "dr_sharma",
                    "email": "sharma@eye.org",
                    "full_name": "Dr. Sharma",
                    "role": "ophthalmologist",
                    "password": "DoctorPassword123",
                },
                headers={"Authorization": f"Bearer {hw_token}"},
            )
            self.assertEqual(hw_try.status_code, 403)

            # Admin provisions ophthalmologist -> 201 Created
            admin_prov = await client.post(
                "/api/auth/users",
                json={
                    "username": "dr_sharma",
                    "email": "sharma@eye.org",
                    "full_name": "Dr. Sharma",
                    "role": "ophthalmologist",
                    "password": "DoctorPassword123",
                },
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self.assertEqual(admin_prov.status_code, 201)
            created_user = admin_prov.json()
            self.assertEqual(created_user["role"], "ophthalmologist")
            new_user_id = created_user["id"]

            # Admin updates role
            role_upd = await client.patch(
                f"/api/auth/users/{new_user_id}/role",
                json={"role": "administrator"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self.assertEqual(role_upd.status_code, 200)
            self.assertEqual(role_upd.json()["role"], "administrator")

            # Admin deactivates account
            status_upd = await client.patch(
                f"/api/auth/users/{new_user_id}/status",
                json={"is_active": False},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self.assertEqual(status_upd.status_code, 200)
            self.assertFalse(status_upd.json()["is_active"])
