"""
RetinaShield — Private Image Storage Service

Manages secure storage of fundus images. Images are never served directly
via the web server — they are accessed only through authenticated API
endpoints that stream the file contents.

Supports optional Fernet encryption at rest.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

import aiofiles
from PIL import Image as PILImage

from app.config import settings

logger = logging.getLogger(__name__)


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
                logger.error(f"Failed to initialize encryption: {e}")
                self._encrypt = False

    def _get_storage_path(self, stored_filename: str) -> Path:
        """Get the full path for a stored image, organized by date prefix."""
        # Use first 2 chars of UUID as directory sharding
        shard = stored_filename[:2]
        shard_dir = self._base_dir / shard
        shard_dir.mkdir(parents=True, exist_ok=True)
        return shard_dir / stored_filename

    async def store_image(
        self, file_content: bytes, original_filename: str, content_type: str = "image/jpeg"
    ) -> dict:
        """
        Store a fundus image securely.

        Returns metadata dict with stored_filename, storage_path, dimensions, size.
        """
        # Generate UUID-based filename
        ext = Path(original_filename).suffix or ".jpg"
        stored_filename = f"{uuid.uuid4()}{ext}"
        storage_path = self._get_storage_path(stored_filename)

        # Validate image
        try:
            from io import BytesIO

            pil_img = PILImage.open(BytesIO(file_content))
            pil_img.verify()
            # Re-open after verify (verify() may consume the stream)
            pil_img = PILImage.open(BytesIO(file_content))
            width, height = pil_img.size
        except Exception as e:
            raise ValueError(f"Invalid image file: {e}")

        # Check size limit
        if len(file_content) > settings.max_upload_size_bytes:
            raise ValueError(
                f"Image size ({len(file_content)} bytes) exceeds "
                f"maximum ({settings.max_upload_size_bytes} bytes)"
            )

        # Optionally encrypt
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
            f"({width}x{height}, {len(file_content)} bytes)"
        )

        return {
            "stored_filename": stored_filename,
            "storage_path": str(storage_path),
            "content_type": content_type,
            "file_size_bytes": len(file_content),
            "width": width,
            "height": height,
        }

    async def retrieve_image(self, stored_filename: str) -> bytes:
        """Retrieve an image by its stored filename. Decrypts if needed."""
        storage_path = self._get_storage_path(stored_filename)

        if not storage_path.exists():
            raise FileNotFoundError(f"Image not found: {stored_filename}")

        async with aiofiles.open(storage_path, "rb") as f:
            data = await f.read()

        # Decrypt if encrypted
        if stored_filename.endswith(".enc") and self._fernet:
            data = self._fernet.decrypt(data)

        return data

    async def delete_image(self, stored_filename: str) -> bool:
        """Delete an image from storage."""
        storage_path = self._get_storage_path(stored_filename)
        if storage_path.exists():
            storage_path.unlink()
            logger.info(f"Deleted image: {stored_filename}")
            return True
        return False

    async def get_image_path(self, stored_filename: str) -> str:
        """Get the filesystem path for an image (for pipeline processing)."""
        path = self._get_storage_path(stored_filename)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {stored_filename}")

        # If encrypted, we need to decrypt to a temp file for pipeline processing
        if stored_filename.endswith(".enc") and self._fernet:
            decrypted_path = path.parent / path.stem  # Remove .enc
            data = await self.retrieve_image(stored_filename)
            async with aiofiles.open(decrypted_path, "wb") as f:
                await f.write(data)
            return str(decrypted_path)

        return str(path)


# Singleton
image_store = ImageStore()
