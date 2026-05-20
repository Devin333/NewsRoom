from __future__ import annotations

from pathlib import Path

from framework.artifacts.models import Artifact, ArtifactReference


class ArtifactValidator:
    def validate(self, artifact: Artifact) -> list[str]:
        errors: list[str] = []
        if not artifact.artifact_id:
            errors.append("artifact_id is required")
        if not artifact.name:
            errors.append("name is required")
        if not artifact.content_type:
            errors.append("content_type is required")
        if isinstance(artifact.artifact_id, str):
            errors.extend(_id_errors(artifact.artifact_id, "artifact_id"))
        return errors

    def validate_reference(self, ref: ArtifactReference) -> list[str]:
        errors: list[str] = []
        if not ref.artifact_id:
            errors.append("artifact_id is required")
        if not ref.uri:
            errors.append("uri is required")
        errors.extend(_relative_path_errors(ref.uri, "uri"))
        return errors


def _id_errors(value: str, label: str) -> list[str]:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        return [f"invalid {label}: {value}"]
    return []


def _relative_path_errors(value: str, label: str) -> list[str]:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        return [f"invalid {label}: {value}"]
    return []
