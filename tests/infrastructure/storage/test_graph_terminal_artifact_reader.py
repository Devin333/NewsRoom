from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from framework.agent.artifacts import (
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
)
from framework.harness.artifacts import (
    GraphArtifactStrictContentReader,
    GraphTerminalArtifact,
    GraphTerminalManifest,
    GraphTerminalManifestError,
    GraphTerminalManifestErrorCode,
    GraphTerminalManifestHistoryError,
)
from infrastructure.storage.artifacts import FilesystemGraphTerminalArtifactReader


_NOW = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
_SHA_A = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_SHA_C = "sha256:" + "c" * 64


def _write_run(root, content: bytes = b'{"status":"ok"}'):
    run_dir = root / "run-1"
    artifact_path = run_dir / "nodes" / "analyze" / "analysis.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(content)
    artifact = GraphTerminalArtifact(
        artifact_key="analysis",
        artifact_id="analysis-1",
        ref="artifact://run-1/analysis-1",
        relative_path="nodes/analyze/analysis.json",
        content_checksum=f"sha256:{sha256(content).hexdigest()}",
        byte_size=len(content),
        media_type="application/json",
        node_id="analyze",
        attempt_id="attempt-1",
        required_for_replay=True,
        required_for_publication=True,
    )
    manifest = GraphTerminalManifest(
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="research.paper-analysis",
        graph_version="1",
        graph_schema_version="1",
        compiler_version="1",
        normalized_graph_checksum=_SHA_A,
        status="succeeded",
        started_at=_NOW,
        completed_at=_NOW + timedelta(seconds=1),
        terminal_state_ref=_SHA_B,
        checkpoint_ref="checkpoint://run-1/terminal",
        terminal_node_ids=("publish",),
        gate_evidence_refs=(_SHA_C,),
        artifacts=(artifact,),
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict()),
        encoding="utf-8",
    )
    return manifest, artifact_path


def test_filesystem_reader_reads_verified_graph_content(tmp_path) -> None:
    expected, _ = _write_run(tmp_path)
    adapter = FilesystemGraphTerminalArtifactReader(tmp_path)

    manifest = adapter.read_terminal_manifest("run-1")
    content = GraphArtifactStrictContentReader(adapter).read(manifest, "analysis")

    assert manifest == expected
    assert content.content == {"status": "ok"}


def test_filesystem_reader_rejects_unsafe_run_and_artifact_paths(tmp_path) -> None:
    adapter = FilesystemGraphTerminalArtifactReader(tmp_path)

    with pytest.raises(ArtifactPathError):
        adapter.read_terminal_manifest("../run-1")
    with pytest.raises(ArtifactPathError):
        adapter.read_artifact_content(run_id="run-1", relative_path="../secret")


def test_filesystem_reader_returns_artifact_not_found_for_missing_run(tmp_path) -> None:
    with pytest.raises(ArtifactNotFoundError, match="run-1/manifest.json"):
        FilesystemGraphTerminalArtifactReader(tmp_path).read_terminal_manifest("run-1")


def test_filesystem_reader_rejects_duplicate_manifest_keys(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        '{"schema_version":"one","schema_version":"two"}',
        encoding="utf-8",
    )

    with pytest.raises(ArtifactStoreMetadataError, match="invalid Graph terminal"):
        FilesystemGraphTerminalArtifactReader(tmp_path).read_terminal_manifest("run-1")


def test_filesystem_reader_returns_typed_legacy_history_diagnostic(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "newsroom.workflow_run_manifest.v1",
                "run_id": "run-1",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GraphTerminalManifestHistoryError) as raised:
        FilesystemGraphTerminalArtifactReader(tmp_path).read_terminal_manifest("run-1")

    assert raised.value.code is GraphTerminalManifestErrorCode.HISTORY_QUARANTINED
    assert raised.value.diagnostic.publishable is False


def test_filesystem_reader_rejects_manifest_identity_mismatch(tmp_path) -> None:
    manifest, _ = _write_run(tmp_path)
    payload = manifest.to_dict()
    payload["run_id"] = "run-2"
    payload["manifest_hash"] = None
    rebuilt = GraphTerminalManifest.from_dict(payload)
    (tmp_path / "run-1" / "manifest.json").write_text(
        json.dumps(rebuilt.to_dict()),
        encoding="utf-8",
    )

    with pytest.raises(GraphTerminalManifestError) as raised:
        FilesystemGraphTerminalArtifactReader(tmp_path).read_terminal_manifest("run-1")

    assert raised.value.code is GraphTerminalManifestErrorCode.IDENTITY_MISMATCH


def test_filesystem_reader_rejects_oversized_manifest_before_decode(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_bytes(b"{}")

    with pytest.raises(ArtifactStoreMetadataError, match="read limit"):
        FilesystemGraphTerminalArtifactReader(
            tmp_path,
            max_manifest_bytes=1,
        ).read_terminal_manifest("run-1")


def test_filesystem_reader_rejects_non_regular_artifact(tmp_path) -> None:
    manifest, artifact_path = _write_run(tmp_path)
    artifact_path.unlink()
    artifact_path.mkdir()
    adapter = FilesystemGraphTerminalArtifactReader(tmp_path)

    with pytest.raises(ArtifactStoreMetadataError, match="not a regular file"):
        GraphArtifactStrictContentReader(adapter).read(manifest, "analysis")


def test_filesystem_reader_rejects_symlink_escape(tmp_path) -> None:
    manifest, artifact_path = _write_run(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"leaked":true}', encoding="utf-8")
    artifact_path.unlink()
    try:
        artifact_path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available")

    with pytest.raises((ArtifactPathError, ArtifactStoreMetadataError)):
        GraphArtifactStrictContentReader(
        FilesystemGraphTerminalArtifactReader(tmp_path)
        ).read(manifest, "analysis")


def test_filesystem_reader_rejects_symlink_inside_artifact_root(tmp_path) -> None:
    manifest, artifact_path = _write_run(tmp_path)
    target = artifact_path.with_name("target.json")
    artifact_path.replace(target)
    try:
        artifact_path.symlink_to(target)
    except (OSError, NotImplementedError):
        target.replace(artifact_path)
        pytest.skip("symlink creation is not available")

    with pytest.raises(ArtifactStoreMetadataError, match="symlink"):
        GraphArtifactStrictContentReader(
            FilesystemGraphTerminalArtifactReader(tmp_path)
        ).read(manifest, "analysis")
