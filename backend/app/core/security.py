"""
RetinaShield — Core Security & Authentication

Implements:
- Argon2id password hashing and verification using maintained argon2-cffi.
- Signed JSON Web Token (JWT) encoding and decoding using pyjwt with HS256/RS256.
- Role-based claim extraction and validation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.config import settings

logger = logging.getLogger(__name__)

# Argon2id password hasher with NIST/OWASP compliant parameters
_hasher = PasswordHasher(
    time_cost=3,        # Number of iterations
    memory_cost=65536,  # 64 MiB
    parallelism=4,      # 4 lanes
    hash_len=32,        # 256-bit output hash
    salt_len=16,        # 128-bit random salt
)


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    if not password:
        raise ValueError("Password cannot be empty")
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2id hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception as e:
        logger.error(f"Unexpected error during password verification: {e}")
        return False


def create_access_token(
    subject: str,
    role: str,
    facility_id: str | None = None,
    expires_delta: timedelta | None = None,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Parameters
    ----------
    subject : str
        Subject identifier (typically user UUID or username).
    role : str
        Staff role ('health-worker', 'ophthalmologist', 'administrator').
    facility_id : str | None
        Assigned healthcare facility identifier.
    expires_delta : timedelta | None
        Optional token lifetime override.
    additional_claims : dict[str, Any] | None
        Any optional metadata claims to embed.
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": str(role),
        "facility_id": str(facility_id) if facility_id else None,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": "retinashield-auth",
    }

    if additional_claims:
        payload.update(additional_claims)

    encoded_jwt = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Raises
    ------
    jwt.PyJWTError
        If token is expired, has invalid signature, or is malformed.
    """
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer="retinashield-auth",
    )
