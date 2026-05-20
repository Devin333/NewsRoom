from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.shared.json import to_jsonable


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    run_id: str
    artifact_type: str
    path: str
    content_type: str
    step_id: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    redacted: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "redacted": self.redacted,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "metadata": to_jsonable(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ArtifactRef:
        return cls(
            artifact_id=str(payload["artifact_id"]),
            run_id=str(payload["run_id"]),
            step_id=_optional_str(payload.get("step_id")),
            artifact_type=str(payload["artifact_type"]),
            path=str(payload["path"]),
            content_type=str(payload["content_type"]),
            size_bytes=_optional_int(payload.get("size_bytes")),
            checksum=_optional_str(payload.get("checksum")),
            redacted=bool(payload.get("redacted", True)),
            created_at=_parse_datetime(str(payload["created_at"])),
            metadata=dict(payload.get("metadata") or {}),
        )


class ArtifactManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def start_run(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def write_json(self, run_id: str, name: str, data: Any) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(to_jsonable(data), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target

    def write_text(self, run_id: str, name: str, text: str) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def write_bytes(self, run_id: str, name: str, data: bytes) -> Path:
        target = self._target(run_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def _target(self, run_id: str, name: str) -> Path:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact name must be relative to the run directory: {name}")
        return self.run_dir(run_id) / relative


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


