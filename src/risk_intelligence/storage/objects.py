"""Deterministic object identity and byte integrity; no retrieval or parsing."""

from datetime import UTC
from hashlib import sha256
from pathlib import PurePosixPath
import re

from risk_intelligence.domain.evidence import Source


class EvidenceIntegrityError(RuntimeError):
    """Bytes, checksum or immutable identity disagree; evidence must not be used."""


class StorageAccessError(RuntimeError):
    """Storage access failed independently of object absence or byte integrity."""


MEDIA_EXTENSIONS = {
    "application/json": "json", "application/pdf": "pdf",
    "application/xhtml+xml": "xhtml", "text/html": "html",
    "application/xml": "xml", "text/xml": "xml", "text/plain": "txt",
    "application/octet-stream": "bin",
}


def checksum(content: bytes) -> str:
    """Return lowercase SHA-256 of the exact bytes, including empty content."""
    if not isinstance(content, bytes):
        raise TypeError("Raw evidence must be bytes")
    return sha256(content).hexdigest()


def verify_checksum(content: bytes, expected: str) -> None:
    """Reject malformed digests or different bytes without exposing evidence."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or checksum(content) != expected:
        raise EvidenceIntegrityError("Raw evidence SHA-256 mismatch")


def validate_object_path(object_path: str) -> tuple[str, ...]:
    """Require portable relative components; exclude traversal and Windows aliases."""
    parts = PurePosixPath(object_path).parts
    if not parts or "/".join(parts) != object_path:
        raise ValueError("Object path must be a canonical relative path")
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part) or part.endswith("."):
            raise ValueError("Unsafe object path component")
        if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", part.split(".")[0], re.I):
            raise ValueError("Reserved object path component")
    return parts


def object_key(source: Source, digest: str, media_type: str) -> str:
    """Name an event using supplied UTC metadata only; retries never read a clock."""
    source = Source.model_validate(source)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Object key requires lowercase SHA-256")
    if media_type not in MEDIA_EXTENSIONS:
        raise ValueError("Unsupported raw media type")
    # Derive from canonical ISO rather than platform-dependent strftime year padding.
    timestamp = source.retrieved_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    timestamp = timestamp.replace("-", "").replace(":", "").replace(".", "")
    key = (f"raw/v1/{source.company_number}/{source.source_type.value}/{timestamp}/"
           f"{source.source_id}/{digest}.{MEDIA_EXTENSIONS[media_type]}")
    validate_object_path(key)
    return key
