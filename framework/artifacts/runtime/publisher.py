from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from framework.artifacts.models import Artifact, ArtifactReference
from framework.artifacts.models.checksum import compute_checksum
from framework.artifacts.stores import ArtifactStore
from framework.shared.time import utc_now


REDACTED_METADATA_VALUE = "***REDACTED***"
SENSITIVE_METADATA_PATTERNS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)


class ArtifactStatus(StrEnum):
    CREATED = "created"
    PUBLISHED = "published"
    FAILED = "failed"
    MISSING = "missing"
    CORRUPTED = "corrupted"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class WorkflowArtifactRef:
    artifact_id: str
    artifact_type: str
    key: str
    uri: str
    content_hash: str
    size_bytes: int
    media_type: str | None
    created_by_step_id: str
    created_at: str
    status: ArtifactStatus
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ArtifactStatus(self.status))
        object.__setattr__(self, "metadata", redact_metadata(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "key": self.key,
            "uri": self.uri,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "created_by_step_id": self.created_by_step_id,
            "created_at": self.created_at,
            "status": self.status.value,
            "metadata": redact_metadata(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowArtifactRef":
        return cls(
            artifact_id=str(payload["artifact_id"]),
            artifact_type=str(payload["artifact_type"]),
            key=str(payload["key"]),
            uri=str(payload["uri"]),
            content_hash=str(payload["content_hash"]),
            size_bytes=int(payload["size_bytes"]),
            media_type=_optional_str(payload.get("media_type")),
            created_by_step_id=str(payload["created_by_step_id"]),
            created_at=str(payload["created_at"]),
            status=ArtifactStatus(str(payload["status"])),
            metadata=dict(payload.get("metadata") or {}),
        )

    def with_status(self, status: ArtifactStatus) -> "WorkflowArtifactRef":
        return WorkflowArtifactRef(
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            key=self.key,
            uri=self.uri,
            content_hash=self.content_hash,
            size_bytes=self.size_bytes,
            media_type=self.media_type,
            created_by_step_id=self.created_by_step_id,
            created_at=self.created_at,
            status=status,
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class ArtifactPublishResult:
    artifact_ref: WorkflowArtifactRef | None
    succeeded: bool
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", redact_metadata(self.metadata))


class ArtifactPublisher(Protocol):
    publisher_id: str

    def publish(self, artifact: Artifact) -> ArtifactReference:
        ...


class WorkflowArtifactPublisher(Protocol):
    publisher_id: str

    def publish_artifact(
        self,
        *,
        run_id: str,
        step_id: str,
        key: str,
        artifact_type: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactPublishResult:
        ...

    def exists(self, artifact_ref: WorkflowArtifactRef) -> bool:
        ...

    def verify(self, artifact_ref: WorkflowArtifactRef) -> bool:
        ...

    def recover(self, artifact_ref: WorkflowArtifactRef) -> ArtifactPublishResult:
        ...


class DefaultArtifactPublisher:
    publisher_id = "default"

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def publish(self, artifact: Artifact) -> ArtifactReference:
        return self.store.put(artifact)


class LocalArtifactPublisher:
    publisher_id = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def publish_artifact(
        self,
        *,
        run_id: str,
        step_id: str,
        key: str,
        artifact_type: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactPublishResult:
        try:
            metadata_payload = dict(metadata or {})
            artifact_id = _artifact_id(
                run_id=run_id,
                step_id=step_id,
                key=key,
                artifact_type=artifact_type,
                metadata=metadata_payload,
            )
            relative_uri = _artifact_uri(
                step_id=step_id,
                key=key,
                artifact_type=artifact_type,
                metadata=metadata_payload,
            )
            path = self.root / run_id / relative_uri
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            artifact_ref = WorkflowArtifactRef(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                key=key,
                uri=Path(relative_uri).as_posix(),
                content_hash=stable_hash_bytes(content),
                size_bytes=len(content),
                media_type=_media_type_from_metadata(metadata),
                created_by_step_id=step_id,
                created_at=utc_now_iso(),
                status=ArtifactStatus.PUBLISHED,
                metadata={
                    "publisher_id": self.publisher_id,
                    "run_id": run_id,
                    **metadata_payload,
                },
            )
            return ArtifactPublishResult(
                artifact_ref=artifact_ref,
                succeeded=True,
                metadata={"publisher_id": self.publisher_id},
            )
        except Exception as exc:
            return ArtifactPublishResult(
                artifact_ref=None,
                succeeded=False,
                error=str(exc),
                metadata={"publisher_id": self.publisher_id},
            )

    def exists(self, artifact_ref: WorkflowArtifactRef) -> bool:
        return self._artifact_path(artifact_ref).exists()

    def verify(self, artifact_ref: WorkflowArtifactRef) -> bool:
        path = self._artifact_path(artifact_ref)
        if not path.exists():
            return False
        return stable_hash_bytes(path.read_bytes()) == artifact_ref.content_hash

    def recover(self, artifact_ref: WorkflowArtifactRef) -> ArtifactPublishResult:
        if not self.exists(artifact_ref):
            return ArtifactPublishResult(
                artifact_ref=artifact_ref.with_status(ArtifactStatus.FAILED),
                succeeded=False,
                error="artifact is missing",
                metadata={"artifact_status": ArtifactStatus.MISSING.value},
            )
        if not self.verify(artifact_ref):
            return ArtifactPublishResult(
                artifact_ref=artifact_ref.with_status(ArtifactStatus.CORRUPTED),
                succeeded=False,
                error="artifact hash mismatch",
                metadata={"artifact_status": ArtifactStatus.CORRUPTED.value},
            )
        return ArtifactPublishResult(
            artifact_ref=artifact_ref.with_status(ArtifactStatus.RECOVERED),
            succeeded=True,
            metadata={"artifact_status": ArtifactStatus.RECOVERED.value},
        )

    def status(self, artifact_ref: WorkflowArtifactRef) -> ArtifactStatus:
        if not self.exists(artifact_ref):
            return ArtifactStatus.MISSING
        if not self.verify(artifact_ref):
            return ArtifactStatus.CORRUPTED
        return artifact_ref.status

    def _artifact_path(self, artifact_ref: WorkflowArtifactRef) -> Path:
        uri = Path(artifact_ref.uri)
        if uri.is_absolute() or ".." in uri.parts:
            raise ValueError(f"artifact uri must be relative: {artifact_ref.uri}")
        run_id = artifact_ref.metadata.get("run_id")
        if run_id is not None:
            run_path = Path(str(run_id))
            if run_path.is_absolute() or ".." in run_path.parts:
                raise ValueError(f"artifact run_id must be relative: {run_id}")
            return self.root / run_path / uri
        return self.root / uri


def stable_hash_bytes(content: bytes) -> str:
    return compute_checksum(content)


def redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _redacted_metadata_value(str(key), value)
        for key, value in dict(metadata or {}).items()
    }


def utc_now_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def _redacted_metadata_value(key: str, value: Any) -> Any:
    normalized = key.casefold()
    if any(pattern in normalized for pattern in SENSITIVE_METADATA_PATTERNS):
        return REDACTED_METADATA_VALUE
    if isinstance(value, dict):
        return redact_metadata(value)
    if isinstance(value, list):
        return [
            redact_metadata(item) if isinstance(item, dict) else item
            for item in value
        ]
    return value


def _artifact_id(
    *,
    run_id: str,
    step_id: str,
    key: str,
    artifact_type: str,
    metadata: dict[str, Any],
) -> str:
    explicit_artifact_id = metadata.get("artifact_id")
    if explicit_artifact_id is not None:
        return str(explicit_artifact_id)
    _ = (run_id, key)
    return ":".join([step_id, artifact_type])


def _artifact_uri(
    *,
    step_id: str,
    key: str,
    artifact_type: str,
    metadata: dict[str, Any],
) -> str:
    relative_path = metadata.get("relative_path")
    if relative_path is not None:
        path = Path(str(relative_path).replace("\\", "/"))
    else:
        suffix = _suffix_for_artifact_type(artifact_type, _media_type_from_metadata(metadata))
        path = Path("artifacts") / step_id / f"{key}.{suffix}"
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"artifact path must be relative to the run directory: {path}")
    return path.as_posix()


def _suffix_for_artifact_type(artifact_type: str, media_type: str | None) -> str:
    if media_type == "application/json" or artifact_type == "json":
        return "json"
    if media_type == "text/markdown" or artifact_type == "markdown":
        return "md"
    if media_type == "text/plain":
        return "txt"
    if artifact_type in {"html", "csv"}:
        return artifact_type
    return "bin"


def _media_type_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    value = dict(metadata or {}).get("media_type")
    if value is None:
        value = dict(metadata or {}).get("content_type")
    return _optional_str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
