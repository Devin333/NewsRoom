from __future__ import annotations

import re

from framework.artifacts.models import compute_checksum
from framework.artifacts.stores.errors import (
    ArtifactChecksumMismatchError,
    ArtifactStoreMetadataError,
)


_SHA256_CHECKSUM_RE = re.compile(r"[0-9a-f]{64}")
ARTIFACT_INTEGRITY_METADATA_KEY = "_artifact_integrity"
CHECKSUM_MISSING_INTEGRITY = "checksum_missing"


def validate_sha256_checksum(
    checksum: object,
    *,
    artifact_id: str,
    field: str = "checksum",
) -> str:
    """Return a validated lowercase SHA-256 digest from persisted metadata."""

    if not isinstance(checksum, str) or _SHA256_CHECKSUM_RE.fullmatch(checksum) is None:
        raise ArtifactStoreMetadataError(
            f"invalid {field} for artifact {artifact_id}: expected lowercase SHA-256"
        )
    return checksum


def verify_sha256_checksum(
    content: bytes,
    expected_checksum: object,
    *,
    artifact_id: str,
    field: str = "checksum",
) -> str:
    """Validate and compare a persisted SHA-256 digest, returning the actual digest."""

    expected = validate_sha256_checksum(
        expected_checksum,
        artifact_id=artifact_id,
        field=field,
    )
    actual = compute_checksum(content)
    if actual != expected:
        raise ArtifactChecksumMismatchError(
            f"artifact checksum mismatch: {artifact_id}"
        )
    return actual


__all__ = [
    "ARTIFACT_INTEGRITY_METADATA_KEY",
    "CHECKSUM_MISSING_INTEGRITY",
    "validate_sha256_checksum",
    "verify_sha256_checksum",
]
