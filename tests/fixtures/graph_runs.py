from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from backend.research.graphs import build_paper_analysis_graph_definition
from framework.harness.artifacts import (
    GraphTerminalArtifact,
    GraphTerminalManifest,
    GraphTerminalManifestV2,
)
from framework.harness.graph import GraphExecutionVersionManifest, HarnessGraphCompiler


_STARTED_AT = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
_STATE_CHECKSUM = "sha256:" + "b" * 64
_GATE_CHECKSUM = "sha256:" + "c" * 64


@dataclass(frozen=True, slots=True)
class GraphTerminalRunFixture:
    root: Path
    run_dir: Path
    manifest_path: Path
    manifest: GraphTerminalManifestV2

    def artifact_path(self, artifact_key: str) -> Path:
        artifact = self.manifest.artifact(artifact_key)
        if artifact is None:
            raise KeyError(artifact_key)
        return self.run_dir / artifact.relative_path


def write_graph_terminal_run(
    root: str | Path,
    run_id: str = "run-1",
    *,
    files: Mapping[str, tuple[str, Any]] | None = None,
    status: str = "succeeded",
) -> GraphTerminalRunFixture:
    artifact_root = Path(root)
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    actual_files = (
        {"output": ("output.json", {"status": "ok"})}
        if files is None
        else dict(files)
    )
    artifacts: list[GraphTerminalArtifact] = []
    for artifact_key, (relative_path, value) in actual_files.items():
        content = _encoded_content(value)
        path = run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        artifacts.append(
            GraphTerminalArtifact(
                artifact_key=artifact_key,
                artifact_id=artifact_key,
                ref=f"artifact://{run_id}/{artifact_key}",
                relative_path=relative_path,
                content_checksum=f"sha256:{sha256(content).hexdigest()}",
                byte_size=len(content),
                media_type=_media_type(relative_path),
                node_id="publish_artifacts",
                attempt_id="attempt-1",
                required_for_replay=True,
                required_for_publication=True,
            )
        )
    execution_versions = _execution_versions()
    terminal = GraphTerminalManifest(
        tenant_id="tenant-1",
        run_id=run_id,
        graph_id=execution_versions.graph_id,
        graph_version=execution_versions.graph_version,
        graph_schema_version=execution_versions.normalized_graph_schema_version,
        compiler_version=execution_versions.compiler_version,
        normalized_graph_checksum=execution_versions.normalized_graph_checksum,
        status=status,
        started_at=_STARTED_AT,
        completed_at=_STARTED_AT + timedelta(seconds=1),
        terminal_state_ref=_STATE_CHECKSUM,
        checkpoint_ref=f"graph-state://{run_id}/{_STATE_CHECKSUM}",
        terminal_node_ids=execution_versions.terminal_node_ids,
        gate_evidence_refs=(_GATE_CHECKSUM,),
        artifacts=tuple(artifacts),
    )
    manifest = GraphTerminalManifestV2(
        terminal=terminal,
        execution_versions=execution_versions,
    )
    manifest_path = run_dir / "manifest.json"
    rewrite_graph_terminal_manifest(manifest_path, manifest)
    return GraphTerminalRunFixture(
        root=artifact_root,
        run_dir=run_dir,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def rewrite_graph_terminal_manifest(
    target: str | Path | GraphTerminalRunFixture,
    manifest: GraphTerminalManifestV2 | GraphTerminalManifest | Mapping[str, Any],
) -> None:
    path = target.manifest_path if isinstance(target, GraphTerminalRunFixture) else Path(target)
    payload = (
        manifest.to_dict()
        if isinstance(manifest, (GraphTerminalManifestV2, GraphTerminalManifest))
        else dict(manifest)
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _encoded_content(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _execution_versions() -> GraphExecutionVersionManifest:
    graph = HarnessGraphCompiler().compile(
        build_paper_analysis_graph_definition()
    ).graph
    return GraphExecutionVersionManifest.from_normalized_graph(graph)


def _media_type(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.casefold()
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


class _FixtureGraphIndexReader:
    """Test-only index adapter for manifest and artifact transport tests."""

    def read_for_manifest(self, manifest: GraphTerminalManifestV2):
        records = tuple(
            SimpleNamespace(
                artifact_key=artifact.artifact_key,
                artifact_id=artifact.artifact_id,
                artifact_ref=artifact.ref,
                relative_path=artifact.relative_path,
                content_checksum=artifact.content_checksum,
                byte_size=artifact.byte_size,
                media_type=artifact.media_type,
                required_for_replay=artifact.required_for_replay,
                required_for_publication=artifact.required_for_publication,
            )
            for artifact in manifest.artifacts
        )
        return SimpleNamespace(
            artifact_records=records,
            event_records=(),
            event_high_watermark=0,
            snapshot_checksum="fixture-index",
        )


def graph_index_reader(root: str | Path) -> _FixtureGraphIndexReader:
    del root
    return _FixtureGraphIndexReader()


__all__ = [
    "GraphTerminalRunFixture",
    "graph_index_reader",
    "rewrite_graph_terminal_manifest",
    "write_graph_terminal_run",
]
