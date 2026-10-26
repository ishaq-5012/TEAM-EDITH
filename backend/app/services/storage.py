"""Private file storage.

Files are written under ``settings.storage_dir`` (outside any public web root)
using generated keys, never client-supplied names. Content type is determined
from magic bytes; client filenames and MIME headers are treated as untrusted
metadata only. Downloads must go through authorized API endpoints.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings
from app.core.errors import DomainError

CHUNK = 1024 * 1024

# (magic prefix, detected MIME, canonical extension)
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"II*\x00", "image/tiff", "tiff"),
    (b"MM\x00*", "image/tiff", "tiff"),
]

ALLOWED_MIME_TYPES = frozenset(m for _, m, _ in _SIGNATURES)

_KEY_RE = re.compile(r"^[a-f0-9]{48}$")


class UnsupportedFileType(DomainError):
    status_code = 415
    code = "unsupported_file_type"


class FileTooLarge(DomainError):
    status_code = 413
    code = "file_too_large"


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    sha256: str
    size_bytes: int
    detected_mime: str
    extension: str


def detect_mime(head: bytes) -> tuple[str, str] | None:
    for magic, mime, ext in _SIGNATURES:
        if head.startswith(magic):
            return mime, ext
    return None


def sanitize_display_name(name: str | None, max_len: int = 200) -> str:
    """Return a safe *display* name. Never used as a filesystem path."""
    raw = unicodedata.normalize("NFKC", name or "")
    raw = raw.replace("\\", "/").rsplit("/", 1)[-1]
    raw = "".join(ch for ch in raw if ch.isprintable() and ch not in '<>:"|?*')
    raw = raw.strip(" .")
    return (raw or "unnamed")[:max_len]


class LocalStorage:
    def __init__(self, root: Path | None = None, max_bytes: int | None = None):
        settings = get_settings()
        self.root = Path(root or settings.storage_dir).resolve()
        self.max_bytes = max_bytes or settings.max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def check_writable(self) -> None:
        """Write and remove a probe file in the storage root. Raises OSError if storage is unavailable."""
        probe = self.root / f".probe-{secrets.token_hex(8)}"
        probe.write_bytes(b"ok")
        probe.unlink()

    def _path_for(self, key: str) -> Path:
        if not _KEY_RE.fullmatch(key):
            raise DomainError("Invalid storage key", code="invalid_storage_key")
        path = (self.root / key[:2] / key).resolve()
        if self.root not in path.parents:
            raise DomainError("Invalid storage key", code="invalid_storage_key")
        return path

    def save(self, stream: BinaryIO) -> StoredObject:
        """Stream to a temp file, enforcing size limit and type allow-list, then move into place."""
        key = secrets.token_hex(24)
        final = self._path_for(key)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.with_suffix(".part")
        digest = hashlib.sha256()
        size = 0
        head = b""
        try:
            with open(tmp, "xb") as out:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FileTooLarge(f"File exceeds the {self.max_bytes} byte limit")
                    if len(head) < 16:
                        head += chunk[: 16 - len(head)]
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise DomainError("File is empty", code="empty_file")
            detected = detect_mime(head)
            if detected is None:
                raise UnsupportedFileType(
                    "Unsupported file type. Allowed: PDF, PNG, JPEG, TIFF (verified by file content)"
                )
            os.replace(tmp, final)
        finally:
            if tmp.exists():
                tmp.unlink()
        return StoredObject(key, digest.hexdigest(), size, detected[0], detected[1])

    def open(self, key: str) -> BinaryIO:
        path = self._path_for(key)
        if not path.is_file():
            raise DomainError("Stored file not found", code="not_found", status_code=404)
        return open(path, "rb")

    def path(self, key: str) -> Path:
        return self._path_for(key)

    def read(self, key: str) -> bytes:
        """Whole object in memory (uploads are size-capped). Callers verify the hash themselves."""
        path = self._path_for(key)
        if not path.is_file():
            raise DomainError("Stored file not found", code="not_found", status_code=404)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        """Remove a stored object (used to roll back rejected or failed uploads). Missing is fine."""
        path = self._path_for(key)
        path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

    def verify(self, key: str, expected_sha256: str) -> bool:
        digest = hashlib.sha256()
        with self.open(key) as fh:
            while chunk := fh.read(CHUNK):
                digest.update(chunk)
        return secrets.compare_digest(digest.hexdigest(), expected_sha256)


def get_storage() -> LocalStorage:
    """FastAPI dependency; tests override it to simulate storage failures."""
    return LocalStorage()
