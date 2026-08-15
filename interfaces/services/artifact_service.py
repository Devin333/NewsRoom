from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.harness.artifacts import (
    GraphArtifactStrictContentReader,
    GraphTerminalArtifact,
    GraphTerminalManifestError,
    GraphTerminalManifestErrorCode,
    GraphTerminalManifestHistoryError,
)
from infrastructure.storage.artifacts import FilesystemGraphTerminalArtifactReader


@dataclass(frozen=True)
class ArtifactSummary:
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ArtifactListResult:
    run_id: str
    artifacts: list[ArtifactSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_count": len(self.artifacts),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class ArtifactDetail:
    run_id: str
    artifact_key: str
    relative_path: str
    content_type: str
    size_bytes: int | None
    content: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_key": self.artifact_key,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "content": self.content,
        }


class ArtifactInspectionService:
    def __init__(
        self,
        artifact_root: str | Path = ".newsroom/runs",
        *,
        terminal_reader: FilesystemGraphTerminalArtifactReader | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.terminal_reader = terminal_reader or FilesystemGraphTerminalArtifactReader(
            self.artifact_root
        )
        if self.terminal_reader.root.resolve(strict=False) != self.artifact_root.resolve(
            strict=False
        ):
            raise ValueError("terminal_reader root does not match artifact_root")
        self.content_reader = GraphArtifactStrictContentReader(self.terminal_reader)

    def list_artifacts(self, run_id: str) -> ArtifactListResult:
        try:
            manifest = self.terminal_reader.read_terminal_manifest(run_id)
        except GraphTerminalManifestError as exc:
            _raise_inspection_contract_error(exc)
        artifacts = [
            self._summary(artifact)
            for artifact in sorted(
                manifest.artifacts,
                key=lambda item: item.artifact_key,
            )
        ]
        return ArtifactListResult(run_id=manifest.run_id, artifacts=artifacts)

    def get_artifact(self, run_id: str, artifact_key: str) -> ArtifactDetail:
        try:
            manifest = self.terminal_reader.read_terminal_manifest(run_id)
            record = self.content_reader.read(manifest, artifact_key, redact=True)
        except GraphTerminalManifestError as exc:
            _raise_inspection_contract_error(exc)
        content = record.content
        if record.media_type == "application/x-ndjson" and isinstance(content, list):
            content = _jsonl_values_to_text(content)
        return ArtifactDetail(
            run_id=manifest.run_id,
            artifact_key=artifact_key,
            relative_path=record.relative_path,
            content_type=record.media_type,
            size_bytes=record.byte_size,
            content=content,
        )

    @staticmethod
    def _summary(artifact: GraphTerminalArtifact) -> ArtifactSummary:
        return ArtifactSummary(
            artifact_key=artifact.artifact_key,
            relative_path=artifact.relative_path,
            content_type=artifact.media_type,
            size_bytes=artifact.byte_size,
        )


def _jsonl_values_to_text(values: list[Any]) -> str:
    lines = [json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values]
    return "\n".join(lines) + ("\n" if lines else "")


def _raise_inspection_contract_error(
    exc: GraphTerminalManifestError,
) -> NoReturn:
    if isinstance(exc, GraphTerminalManifestHistoryError):
        raise exc
    if exc.code in {
        GraphTerminalManifestErrorCode.ARTIFACT_CHECKSUM_MISMATCH,
        GraphTerminalManifestErrorCode.ARTIFACT_SIZE_MISMATCH,
    }:
        raise ArtifactChecksumMismatchError(str(exc)) from exc
    if exc.code is GraphTerminalManifestErrorCode.ARTIFACT_NOT_FOUND:
        raise ArtifactNotFoundError(str(exc)) from exc
    raise ArtifactStoreMetadataError(str(exc)) from exc
