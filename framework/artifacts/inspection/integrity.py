from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.artifacts.models import ArtifactManifest, compute_checksum
from framework.artifacts.stores import ArtifactStore


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

    def inspect(self, manifest: ArtifactManifest, store: ArtifactStore | None = None) -> ArtifactIntegrityReport:
        actual_store = store or self.store
        if actual_store is None:
            return ArtifactIntegrityReport(valid=True, checked_count=len(manifest.artifacts))
        issues: list[ArtifactIntegrityIssue] = []
        for ref in manifest.artifacts:
            artifact = actual_store.get(ref.artifact_id)
            if artifact is None:
                issues.append(ArtifactIntegrityIssue(ref.artifact_id, "missing"))
                continue
            if ref.checksum and compute_checksum(artifact.content_bytes()) != ref.checksum:
                issues.append(ArtifactIntegrityIssue(ref.artifact_id, "checksum_mismatch"))
        return ArtifactIntegrityReport(
            valid=not issues,
            checked_count=len(manifest.artifacts),
            issues=issues,
        )
