from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from framework.harness.artifacts import GraphTerminalArtifact, GraphTerminalManifest


_STARTED_AT = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
_GRAPH_CHECKSUM = "sha256:" + "a" * 64
_STATE_CHECKSUM = "sha256:" + "b" * 64
_GATE_CHECKSUM = "sha256:" + "c" * 64


@dataclass(frozen=True, slots=True)
class GraphTerminalRunFixture:
    root: Path
    run_dir: Path
    manifest_path: Path
    manifest: GraphTerminalManifest

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
                node_id="publish",
                attempt_id="attempt-1",
                required_for_replay=True,
                required_for_publication=True,
            )
        )
    manifest = GraphTerminalManifest(
        tenant_id="tenant-1",
        run_id=run_id,
        graph_id="research.paper-analysis",
        graph_version="1.0.0",
        graph_schema_version="1.0.0",
        compiler_version="1.0.0",
        normalized_graph_checksum=_GRAPH_CHECKSUM,
        status=status,
        started_at=_STARTED_AT,
        completed_at=_STARTED_AT + timedelta(seconds=1),
        terminal_state_ref=_STATE_CHECKSUM,
        checkpoint_ref=f"graph-state://{run_id}/{_STATE_CHECKSUM}",
        terminal_node_ids=("publish",),
        gate_evidence_refs=(_GATE_CHECKSUM,),
        artifacts=tuple(artifacts),
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
    manifest: GraphTerminalManifest | Mapping[str, Any],
) -> None:
    path = target.manifest_path if isinstance(target, GraphTerminalRunFixture) else Path(target)
    payload = manifest.to_dict() if isinstance(manifest, GraphTerminalManifest) else dict(manifest)
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


__all__ = [
    "GraphTerminalRunFixture",
    "rewrite_graph_terminal_manifest",
    "write_graph_terminal_run",
]
