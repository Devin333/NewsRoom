from __future__ import annotations

from typing import Final


_OBSERVABILITY_OUTCOMES_ATTRIBUTE: Final = (
    "_artifact_observability_emitted_outcomes"
)


def artifact_observability_was_emitted(subject: object, outcome: str) -> bool:
    """Return whether an outcome was emitted by an upstream deterministic owner."""

    emitted = getattr(subject, _OBSERVABILITY_OUTCOMES_ATTRIBUTE, ())
    return isinstance(emitted, (set, frozenset)) and outcome in emitted


def mark_artifact_observability_emitted(subject: object, outcome: str) -> None:
    """Attach an internal, non-serialized propagation marker to an outcome object."""

    emitted = getattr(subject, _OBSERVABILITY_OUTCOMES_ATTRIBUTE, ())
    outcomes = set(emitted) if isinstance(emitted, (set, frozenset)) else set()
    outcomes.add(outcome)
    object.__setattr__(
        subject,
        _OBSERVABILITY_OUTCOMES_ATTRIBUTE,
        frozenset(outcomes),
    )


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when committed artifact state refers to missing content."""


class ArtifactChecksumMismatchError(ValueError):
    """Raised when persisted artifact bytes do not match a valid checksum."""


class ArtifactStoreMetadataError(ValueError):
    """Raised when artifact-store metadata is missing, malformed, or invalid."""

    @property
    def observability_emitted(self) -> bool:
        return artifact_observability_was_emitted(self, "metadata_corrupt")

    def mark_observability_emitted(self) -> None:
        mark_artifact_observability_emitted(self, "metadata_corrupt")


__all__ = [
    "ArtifactChecksumMismatchError",
    "ArtifactNotFoundError",
    "ArtifactStoreMetadataError",
    "artifact_observability_was_emitted",
    "mark_artifact_observability_emitted",
]
