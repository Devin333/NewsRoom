from __future__ import annotations

from framework.artifacts.models import Artifact, ArtifactReference
from framework.artifacts.paths import ArtifactPathError, validate_artifact_path_segment


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
        if ref.run_id is not None:
            errors.extend(_id_errors(ref.run_id, "run_id"))
        return errors


def _id_errors(value: str, label: str) -> list[str]:
    try:
        validate_artifact_path_segment(value, field=label)
    except ArtifactPathError as exc:
        return [str(exc)]
    return []
