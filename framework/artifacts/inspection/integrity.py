from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.artifacts.models import ArtifactManifest
from framework.artifacts.observability import (
    emit_artifact_checksum_missing,
    emit_artifact_integrity_inspection,
    emit_artifact_metadata_corrupt,
)
from framework.artifacts.stores import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreMetadataError,
    verify_sha256_checksum,
)
from framework.artifacts.stores.errors import (
    artifact_observability_was_emitted,
)
from framework.artifacts.stores.integrity import (
    ARTIFACT_INTEGRITY_METADATA_KEY,
    CHECKSUM_MISSING_INTEGRITY,
)


class ArtifactStoreRequiredError(RuntimeError):
    """Raised when non-empty integrity inspection has no configured store."""


@dataclass(frozen=True)
class ArtifactIntegrityIssue:
    artifact_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"artifact_id": self.artifact_id, "reason": self.reason}


@dataclass(frozen=True)
class ArtifactIntegrityReport:
    valid: bool
    checked_count: int
    issues: list[ArtifactIntegrityIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "checked_count": self.checked_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class ArtifactIntegrityInspector:
    def __init__(self, store: ArtifactStore | None = None) -> None:
        self.store = store

    def inspect(
        self,
        manifest: ArtifactManifest,
        store: ArtifactStore | None = None,
    ) -> ArtifactIntegrityReport:
        try:
            report = self._inspect(manifest, store=store)
        except ArtifactStoreRequiredError:
            emit_artifact_integrity_inspection(result="store_unavailable")
            raise
        except Exception:
            emit_artifact_integrity_inspection(result="error")
            raise
        emit_artifact_integrity_inspection(
            result="valid" if report.valid else "invalid"
        )
        return report

    def _inspect(
        self,
        manifest: ArtifactManifest,
        *,
        store: ArtifactStore | None,
    ) -> ArtifactIntegrityReport:
        if not manifest.artifacts:
            return ArtifactIntegrityReport(valid=True, checked_count=0)
        actual_store = store if store is not None else self.store
        if actual_store is None:
            raise ArtifactStoreRequiredError(
                "artifact integrity inspection requires an artifact store"
            )
        issues: list[ArtifactIntegrityIssue] = []
        checked_count = 0
        for ref in manifest.artifacts:
            checked_count += 1
            try:
                artifact = actual_store.get(ref.artifact_id)
            except ArtifactNotFoundError:
                issues.append(ArtifactIntegrityIssue(ref.artifact_id, "missing"))
                continue
            except ArtifactChecksumMismatchError:
                issues.append(
                    ArtifactIntegrityIssue(ref.artifact_id, "checksum_mismatch")
                )
                continue
            except ArtifactStoreMetadataError as exc:
                if not exc.observability_emitted:
                    emit_artifact_metadata_corrupt(store="artifact_store")
                    exc.mark_observability_emitted()
                issues.append(
                    ArtifactIntegrityIssue(ref.artifact_id, "metadata_corrupt")
                )
                continue
            if artifact is None:
                issues.append(ArtifactIntegrityIssue(ref.artifact_id, "missing"))
                continue
            if (
                artifact.metadata.get(ARTIFACT_INTEGRITY_METADATA_KEY)
                == CHECKSUM_MISSING_INTEGRITY
                or ref.checksum is None
            ):
                if not artifact_observability_was_emitted(
                    artifact,
                    "checksum_missing",
                ):
                    emit_artifact_checksum_missing(store="artifact_store")
                issues.append(
                    ArtifactIntegrityIssue(ref.artifact_id, "checksum_missing")
                )
                continue
            try:
                verify_sha256_checksum(
                    artifact.content_bytes(),
                    ref.checksum,
                    artifact_id=ref.artifact_id,
                    field="artifact reference checksum",
                )
            except ArtifactChecksumMismatchError:
                issues.append(
                    ArtifactIntegrityIssue(ref.artifact_id, "checksum_mismatch")
                )
            except ArtifactStoreMetadataError as exc:
                if not exc.observability_emitted:
                    emit_artifact_metadata_corrupt(store="artifact_store")
                    exc.mark_observability_emitted()
                issues.append(
                    ArtifactIntegrityIssue(ref.artifact_id, "metadata_corrupt")
                )
        return ArtifactIntegrityReport(
            valid=not issues,
            checked_count=checked_count,
            issues=issues,
        )


__all__ = [
    "ArtifactIntegrityInspector",
    "ArtifactIntegrityIssue",
    "ArtifactIntegrityReport",
    "ArtifactStoreRequiredError",
]
