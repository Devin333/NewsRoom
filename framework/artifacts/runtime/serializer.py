from __future__ import annotations

import json
from typing import Any

from framework.artifacts.models import Artifact
from framework.shared.json import to_jsonable
from framework.shared.time import parse_datetime, utc_now


class ArtifactSerializer:
    def serialize(self, artifact: Artifact) -> bytes:
        return artifact.content_bytes()

    def deserialize(self, data: bytes, metadata: dict[str, Any]) -> Artifact:
        content_type = str(metadata.get("content_type") or "application/octet-stream")
        content: bytes | str | dict[str, Any]
        if content_type == "application/json":
            content = json.loads(data.decode("utf-8"))
        elif content_type.startswith("text/"):
            content = data.decode("utf-8")
        else:
            content = data
        return Artifact(
            artifact_id=str(metadata["artifact_id"]),
            name=str(metadata.get("name") or metadata["artifact_id"]),
            content_type=content_type,
            content=content,
            metadata=dict(metadata.get("metadata") or {}),
            created_at=parse_datetime(metadata.get("created_at")) or utc_now(),
        )

    def metadata_payload(self, artifact: Artifact) -> dict[str, Any]:
        return to_jsonable(artifact.to_dict(include_content=False))
