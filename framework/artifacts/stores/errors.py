from __future__ import annotations


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when committed artifact state refers to missing content."""


class ArtifactChecksumMismatchError(ValueError):
    """Raised when persisted artifact bytes do not match a valid checksum."""


class ArtifactStoreMetadataError(ValueError):
    """Raised when artifact-store metadata is missing, malformed, or invalid."""


__all__ = [
    "ArtifactChecksumMismatchError",
    "ArtifactNotFoundError",
    "ArtifactStoreMetadataError",
]
