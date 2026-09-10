"""
RetinaShield — Backup & Recovery Service

Provides:
1. Automated snapshot generation of image storage and clinical records metadata.
2. SHA-256 manifest generation for backup integrity verification.
3. Recovery verification procedure to ensure backups can be restored without corruption.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.screening import ScreeningImage

logger = logging.getLogger(__name__)


class BackupRecoveryError(Exception):
    """Raised when backup creation or recovery verification fails."""
    pass


class BackupService:
    """Service to create, manifest, and verify backups for disaster recovery."""

    def __init__(self) -> None:
        self.backup_dir = settings.backup_storage_dir
        self.image_dir = settings.image_storage_dir

    def _compute_sha256(self, filepath: Path) -> str:
        """Compute SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    async def create_backup(
        self,
        db: AsyncSession,
        backup_label: str = "scheduled_backup",
    ) -> dict[str, Any]:
        """
        Create a tar.gz backup archive of private images and database image metadata
        with an embedded SHA-256 manifest.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"retinashield_{backup_label}_{timestamp}.tar.gz"
        backup_path = self.backup_dir / backup_filename

        # Query all active image records
        img_res = await db.execute(select(ScreeningImage))
        images = img_res.scalars().all()

        manifest: dict[str, Any] = {
            "version": "1.0.0",
            "backup_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "label": backup_label,
            "images_count": len(images),
            "files": {},
        }

        # Build archive
        temp_manifest_path = self.backup_dir / f"manifest_{timestamp}.json"
        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                # Archive stored images
                for img in images:
                    img_path = Path(img.storage_path)
                    if img_path.exists():
                        file_hash = self._compute_sha256(img_path)
                        arcname = f"images/{img.stored_filename}"
                        tar.add(img_path, arcname=arcname)
                        manifest["files"][arcname] = {
                            "image_id": str(img.id),
                            "stored_filename": img.stored_filename,
                            "original_filename": img.original_filename,
                            "file_size_bytes": img_path.stat().st_size,
                            "sha256": file_hash,
                        }

                # Write and add manifest to tar
                with open(temp_manifest_path, "w", encoding="utf-8") as mf:
                    json.dump(manifest, mf, indent=2)

                tar.add(temp_manifest_path, arcname="manifest.json")
        finally:
            if temp_manifest_path.exists():
                temp_manifest_path.unlink()

        backup_sha256 = self._compute_sha256(backup_path)
        logger.info(
            f"Created backup archive: {backup_path.name} "
            f"({backup_path.stat().st_size} bytes, sha256={backup_sha256[:8]}...)"
        )

        return {
            "backup_filename": backup_filename,
            "backup_path": str(backup_path),
            "size_bytes": backup_path.stat().st_size,
            "sha256": backup_sha256,
            "archived_images_count": len(manifest["files"]),
            "created_at": manifest["created_at"],
        }

    def verify_backup_integrity(self, backup_path: Path | str) -> dict[str, Any]:
        """
        Verify that a backup archive is valid and every embedded file matches its
        recorded SHA-256 digest in manifest.json.
        """
        p = Path(backup_path)
        if not p.exists():
            raise FileNotFoundError(f"Backup file not found: {p}")

        if not tarfile.is_tarfile(p):
            raise BackupRecoveryError("File is not a valid tar archive")

        with tarfile.open(p, "r:gz") as tar:
            # Extract and parse manifest
            try:
                manifest_member = tar.getmember("manifest.json")
                f = tar.extractfile(manifest_member)
                if not f:
                    raise BackupRecoveryError("Failed to extract manifest.json from backup archive")
                manifest_data = json.load(f)
            except KeyError:
                raise BackupRecoveryError("Archive is missing required manifest.json")

            verified_files = 0
            # Validate every file against manifest checksum
            for arcname, meta in manifest_data.get("files", {}).items():
                try:
                    member = tar.getmember(arcname)
                except KeyError:
                    raise BackupRecoveryError(f"File listed in manifest is missing from archive: {arcname}")

                content = tar.extractfile(member)
                if not content:
                    raise BackupRecoveryError(f"Could not read archived file: {arcname}")

                hasher = hashlib.sha256()
                for chunk in iter(lambda: content.read(65536), b""):
                    hasher.update(chunk)
                computed_hash = hasher.hexdigest()

                if computed_hash != meta["sha256"]:
                    raise BackupRecoveryError(
                        f"Integrity check failed for {arcname}: "
                        f"expected {meta['sha256']}, computed {computed_hash}"
                    )
                verified_files += 1

        logger.info(f"Backup verification successful for {p.name}: {verified_files} files verified.")
        return {
            "backup_filename": p.name,
            "status": "verified",
            "verified_files_count": verified_files,
            "manifest_backup_id": manifest_data.get("backup_id"),
        }


# Singleton
backup_service = BackupService()
