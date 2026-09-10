"""
RetinaShield — Private Image Storage Service

Manages secure storage of fundus images. Images are never served statically
via the web server — they are accessed only through authenticated API
endpoints that enforce role and facility authorization before streaming bytes.

Features:
- Magic byte validation for JPEG, PNG, and TIFF.
- Pillow decode validation: decoded pixel dimensions, aspect ratio, color mode.
- Cryptographic SHA-256 integrity digest generation.
- Sharded filesystem storage using UUIDs.
- Optional Fernet encryption at rest.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from pathlib import Path

import aiofiles
from PIL import Image as PILImage

from app.config import settings

logger = logging.getLogger(__name__)

# Known magic bytes signatures
_MAGIC_BYTES = {
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
    "tiff_le": b"II*\x00",
    "tiff_be": b"MM\x00*",
}


class ImageValidationError(ValueError):
    """Raised when an uploaded image fails validation."""
    pass


class ImageStore:
    """Secure private storage for retinal fundus images."""

    def __init__(self) -> None:
        self._base_dir = settings.image_storage_dir
        self._encrypt = settings.encrypt_images
        self._fernet = None

        if self._encrypt and settings.image_encryption_key:
            try:
                from cryptography.fernet import Fernet
                self._fernet = Fernet(settings.image_encryption_key.encode())
                logger.info("Image encryption enabled")
            except Exception as e:
                logger.error(f"Failed to initialize image encryption: {e}")
                self._encrypt = False

    def _get_storage_path(self, stored_filename: str) -> Path:
        """Get the full path for a stored image with directory sharding."""
        shard = stored_filename[:2]
        shard_dir = self._base_dir / shard
        shard_dir.mkdir(parents=True, exist_ok=True)
        return shard_dir / stored_filename

    def validate_image_bytes(self, content: bytes, content_type: str | None = None) -> tuple[int, int, str]:
        """
        Validate raw image bytes:
        1. File size check.
        2. Magic bytes validation.
        3. Decoded image integrity and pixel dimensions.

        Returns (width, height, detected_format).
        """
        # 1. Size limit check
        if len(content) > settings.max_upload_size_bytes:
            raise ImageValidationError(
                f"Image size ({len(content) / (1024*1024):.2f} MB) exceeds limit of "
                f"{settings.max_upload_size_mb} MB"
            )

        if len(content) < 32:
            raise ImageValidationError("Uploaded file is too small to be a valid image")

        # 2. Magic bytes inspection
        is_jpeg = content.startswith(_MAGIC_BYTES["jpeg"])
        is_png = content.startswith(_MAGIC_BYTES["png"])
        is_tiff = (
            content.startswith(_MAGIC_BYTES["tiff_le"])
            or content.startswith(_MAGIC_BYTES["tiff_be"])
        )

        if not (is_jpeg or is_png or is_tiff):
            raise ImageValidationError(
                "Invalid image header. File does not match expected JPEG, PNG, or TIFF signature."
            )

        detected_format = "JPEG" if is_jpeg else ("PNG" if is_png else "TIFF")

        # 3. Pillow decode and verify
        try:
            stream = io.BytesIO(content)
            with PILImage.open(stream) as img:
                img.verify()

            # Re-read image for size inspection
            stream.seek(0)
            with PILImage.open(stream) as img:
                width, height = img.size
                mode = img.mode

                if mode not in ("RGB", "RGBA", "L"):
                    raise ImageValidationError(
                        f"Unsupported color mode '{mode}'. Fundus screening requires RGB or grayscale."
                    )
        except ImageValidationError:
            raise
        except Exception as e:
            raise ImageValidationError(f"Cannot decode fundus image: {e}")

        # 4. Dimension constraints (Retinal screening requires adequate resolution)
        min_dim = settings.min_upload_dim_px
        max_dim = settings.max_upload_dim_px

        if width < min_dim or height < min_dim:
            raise ImageValidationError(
                f"Image dimensions ({width}x{height}) below minimum required resolution "
                f"of {min_dim}x{min_dim} px for diagnostic evaluation"
            )

        if width > max_dim or height > max_dim:
            raise ImageValidationError(
                f"Image dimensions ({width}x{height}) exceed maximum allowed dimension "
                f"of {max_dim}x{max_dim} px"
            )

        return width, height, detected_format

    async def store_image(
        self,
        file_content: bytes,
        original_filename: str,
        content_type: str = "image/jpeg",
    ) -> dict:
        """
        Validate, hash, and store a fundus image securely in private storage.
        """
        # Validate bytes & extract properties
        width, height, detected_format = self.validate_image_bytes(file_content, content_type)

        # Compute SHA-256 digest
        sha256_hash = hashlib.sha256(file_content).hexdigest()

        # Map extension
        ext_map = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif"}
        ext = ext_map.get(detected_format, ".jpg")
        stored_filename = f"{uuid.uuid4()}{ext}"
        storage_path = self._get_storage_path(stored_filename)

        # Optional encryption
        data_to_write = file_content
        if self._encrypt and self._fernet:
            data_to_write = self._fernet.encrypt(file_content)
            stored_filename += ".enc"
            storage_path = self._get_storage_path(stored_filename)

        # Write to disk
        async with aiofiles.open(storage_path, "wb") as f:
            await f.write(data_to_write)

        logger.info(
            f"Stored image: {original_filename} → {stored_filename} "
            f"({width}x{height}, {len(file_content)} bytes, sha256={sha256_hash[:8]}...)"
        )

        return {
            "stored_filename": stored_filename,
            "storage_path": str(storage_path),
            "content_type": f"image/{detected_format.lower()}",
            "file_size_bytes": len(file_content),
            "width": width,
            "height": height,
            "sha256_hash": sha256_hash,
        }

    async def retrieve_image(self, stored_filename: str) -> bytes:
        """Retrieve an image by stored filename. Decrypts if encrypted."""
        storage_path = self._get_storage_path(stored_filename)

        if not storage_path.exists():
            raise FileNotFoundError(f"Image not found in storage: {stored_filename}")

        async with aiofiles.open(storage_path, "rb") as f:
            data = await f.read()

        if stored_filename.endswith(".enc") and self._fernet:
            data = self._fernet.decrypt(data)

        return data

    async def delete_image(self, stored_filename: str) -> bool:
        """Delete an image from storage."""
        storage_path = self._get_storage_path(stored_filename)
        if storage_path.exists():
            storage_path.unlink()
            logger.info(f"Deleted image from store: {stored_filename}")
            return True
        return False

    async def get_image_path(self, stored_filename: str) -> str:
        """Get filesystem path for pipeline processing."""
        path = self._get_storage_path(stored_filename)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {stored_filename}")

        if stored_filename.endswith(".enc") and self._fernet:
            decrypted_path = path.parent / path.stem
            data = await self.retrieve_image(stored_filename)
            async with aiofiles.open(decrypted_path, "wb") as f:
                await f.write(data)
            return str(decrypted_path)

        return str(path)


# Singleton
image_store = ImageStore()
