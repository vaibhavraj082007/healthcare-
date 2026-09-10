"""
RetinaShield — Facility Secure Image Store

Encrypts fundus images with AES-256-GCM before writing to disk so that raw
image files on the facility computer are not readable without the facility key.

Key management:
    The key is read from the environment variable named by
    `facility_config.image_encryption_key_env_var`.  It is a 32-byte value
    encoded as 64 hex characters.  Keys are NEVER written to the database,
    log files, or browser storage.

Format on disk (encrypted):
    [4 bytes: magic "RSIv"] [12 bytes: nonce] [N bytes: ciphertext+tag]

Format on disk (plaintext fallback, when encryption disabled):
    Raw image bytes, stored as-is.

IMPORTANT: This module is for the facility daemon only.  Web browser code
    never decrypts images — the daemon serves decrypted content over a local
    loopback socket that is not internet-accessible.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from facility.config import facility_config

logger = logging.getLogger(__name__)

_MAGIC = b"RSIv"
_NONCE_LEN = 12


class SecureImageStore:
    """
    AES-256-GCM encrypted image storage for facility-local fundus images.

    Provides:
        store()          — write encrypted image, return (path, sha256_of_raw)
        read_decrypt()   — decrypt and return raw image bytes
        verify_sha256()  — confirm raw bytes match stored checksum

    If `facility_config.image_encryption_enabled` is False (development mode),
    images are stored as plain files but the same interface is used, with a
    warning logged at startup.
    """

    def __init__(self) -> None:
        self._base_dir = facility_config.image_dir
        self._encryption_enabled = facility_config.image_encryption_enabled
        self._key: bytes | None = facility_config.image_encryption_key

        if self._encryption_enabled:
            if not self._key:
                raise RuntimeError(
                    "Image encryption is enabled but "
                    f"{facility_config.image_encryption_key_env_var} is not set. "
                    "Set the environment variable to a 64-character hex string "
                    "(32 random bytes).  To generate: "
                    "python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            logger.info("SecureImageStore: AES-256-GCM encryption enabled.")
        else:
            logger.warning(
                "SecureImageStore: Encryption DISABLED — images stored in "
                "plaintext.  This is NOT acceptable for production use."
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def store(
        self,
        raw_bytes: bytes,
        encounter_id: str,
        eye: str,
        original_ext: str = ".jpg",
    ) -> tuple[str, str]:
        """
        Encrypt and persist `raw_bytes`.

        Returns:
            (relative_path_str, sha256_hex_of_raw_bytes)

        The returned path is relative to `facility_config.image_dir` and is
        stored in the outbox DB.  It is meaningful only on this facility node.
        """
        sha256 = self._sha256(raw_bytes)

        # Sub-directory by encounter_id prefix to limit per-dir file count
        subdir = self._base_dir / encounter_id[:2] / encounter_id
        subdir.mkdir(parents=True, exist_ok=True)

        filename = f"{eye}{original_ext}"
        if self._encryption_enabled:
            filename += ".enc"

        abs_path = subdir / filename

        if self._encryption_enabled:
            self._write_encrypted(abs_path, raw_bytes)
        else:
            abs_path.write_bytes(raw_bytes)

        rel_path = str(abs_path.relative_to(self._base_dir))
        logger.info(
            "Stored image: encounter=%s eye=%s sha256=%s... encrypted=%s",
            encounter_id,
            eye,
            sha256[:12],
            self._encryption_enabled,
        )
        return rel_path, sha256

    def read_decrypt(self, rel_path: str) -> bytes:
        """
        Read and decrypt image bytes from `rel_path` (relative to image_dir).

        Returns raw image bytes suitable for passing to the MATLAB pipeline.
        NEVER writes decrypted bytes to a permanent file.
        """
        abs_path = self._base_dir / rel_path
        if not abs_path.exists():
            raise FileNotFoundError(f"Image not found: {abs_path}")

        raw = abs_path.read_bytes()

        if self._encryption_enabled:
            return self._read_encrypted(raw)
        return raw

    def verify_sha256(self, rel_path: str, expected_sha256: str) -> bool:
        """
        Decrypt image and verify SHA-256 matches the stored checksum.
        Returns True if match, False otherwise.
        """
        try:
            raw = self.read_decrypt(rel_path)
            actual = self._sha256(raw)
            return actual == expected_sha256.lower()
        except Exception as exc:
            logger.error("SHA-256 verification failed for %s: %s", rel_path, exc)
            return False

    def delete(self, rel_path: str) -> None:
        """Securely delete an image file."""
        abs_path = self._base_dir / rel_path
        if abs_path.exists():
            # Overwrite with zeros before deletion to reduce forensic recovery
            size = abs_path.stat().st_size
            with abs_path.open("r+b") as f:
                f.write(b"\x00" * size)
            abs_path.unlink()
            logger.info("Deleted image: %s", rel_path)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write_encrypted(self, path: Path, plaintext: bytes) -> None:
        """Format: [4B magic][12B nonce][ciphertext+16B tag]"""
        assert self._key is not None
        nonce = os.urandom(_NONCE_LEN)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        path.write_bytes(_MAGIC + nonce + ciphertext)

    def _read_encrypted(self, data: bytes) -> bytes:
        """Reverse of `_write_encrypted`."""
        assert self._key is not None
        if len(data) < 4 + _NONCE_LEN:
            raise ValueError("Encrypted image file is too short — possibly corrupted.")
        magic = data[:4]
        if magic != _MAGIC:
            raise ValueError(
                f"Unrecognised magic bytes {magic!r}. "
                "File may not be an encrypted RetinaShield image, "
                "or was encrypted with a different tool."
            )
        nonce = data[4 : 4 + _NONCE_LEN]
        ciphertext = data[4 + _NONCE_LEN :]
        aesgcm = AESGCM(self._key)
        try:
            return aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise ValueError(
                "AES-GCM decryption failed — wrong key or corrupted data."
            ) from exc

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


# Module-level singleton
secure_image_store = SecureImageStore()
