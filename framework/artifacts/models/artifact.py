from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from framework.artifacts.models.content import ArtifactContent
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, parse_datetime, utc_now


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    name: str
    content_type: str
    content: bytes | str | dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ValueError("artifact_id is required")
        if not self.name:
            raise ValueError("name is required")
        if not self.content_type:
            raise ValueError("content_type is required")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", parse_datetime(self.created_at) or utc_now())

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        payload = {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "content_type": self.content_type,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }
        if include_content:
            payload["content"] = (
                self.content.decode("utf-8", errors="replace")
                if isinstance(self.content, bytes)
                else to_jsonable(self.content)
            )
        return payload

    def content_bytes(self) -> bytes:
        return ArtifactContent(self.content).as_bytes()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Artifact":
        return cls(
            artifact_id=str(payload["artifact_id"]),
            name=str(payload["name"]),
            content_type=str(payload["content_type"]),
            content=payload.get("content", b""),
            metadata=dict(payload.get("metadata") or {}),
            created_at=parse_datetime(payload.get("created_at")) or utc_now(),
        )
