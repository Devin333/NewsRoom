from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from framework.harness.artifacts import (
    GRAPH_TERMINAL_MANIFEST_SCHEMA,
    GraphArtifactStrictContentReader,
    GraphManifestHistoryDiagnostic,
    GraphTerminalArtifact,
    GraphTerminalManifest,
    GraphTerminalManifestError,
    GraphTerminalManifestErrorCode,
    GraphTerminalManifestHistoryError,
    GraphTerminalPublicationEvidence,
    GraphTerminalStatus,
    graph_terminal_manifest_hash,
    parse_graph_terminal_manifest,
)


_NOW = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
_SHA_A = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_SHA_C = "sha256:" + "c" * 64
_SHA_D = "sha256:" + "d" * 64
_SHA_E = "sha256:" + "e" * 64
_SHA_F = "sha256:" + "f" * 64


class _MemoryContentPort:
    def __init__(self, values: dict[tuple[str, str], bytes]) -> None:
        self.values = dict(values)
        self.calls: list[tuple[str, str]] = []

    def read_artifact_content(self, *, run_id: str, relative_path: str) -> bytes:
        self.calls.append((run_id, relative_path))
        return self.values[(run_id, relative_path)]


def _checksum(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"


def _artifact(
    content: bytes = b'{"status":"ok"}',
    *,
    artifact_key: str = "analysis",
    artifact_id: str = "analysis-1",
    ref: str = "artifact://run-1/analysis-1",
    relative_path: str = "nodes/analyze/analysis.json",
    media_type: str = "application/json",
    metadata: dict | None = None,
) -> GraphTerminalArtifact:
    return GraphTerminalArtifact(
        artifact_key=artifact_key,
        artifact_id=artifact_id,
        ref=ref,
        relative_path=relative_path,
        content_checksum=_checksum(content),
        byte_size=len(content),
        media_type=media_type,
        node_id="analyze",
        attempt_id="attempt-1",
        required_for_replay=True,
        required_for_publication=True,
        metadata=metadata or {"producer_revision": "research@1"},
    )


def _publication() -> GraphTerminalPublicationEvidence:
    return GraphTerminalPublicationEvidence(
        identity_scope_ref=_SHA_A,
        subject_scope_ref=_SHA_B,
        publication_authority_ref=_SHA_C,
        terminal_side_effect_outcome_ref=_SHA_D,
        artifact_evidence_ref=_SHA_E,
        artifact_member_evidence_ref=_SHA_F,
        committed_at=_NOW + timedelta(seconds=2),
        metadata={"handler": "research-artifact-bundle@1"},
    )


def _manifest(
    *artifacts: GraphTerminalArtifact,
    publication: GraphTerminalPublicationEvidence | None = None,
) -> GraphTerminalManifest:
    return GraphTerminalManifest(
        tenant_id="tenant-1",
        run_id="run-1",
        graph_id="research.paper-analysis",
        graph_version="1",
        graph_schema_version="1",
        compiler_version="1",
        normalized_graph_checksum=_SHA_A,
        status=GraphTerminalStatus.SUCCEEDED,
        started_at=_NOW,
        completed_at=_NOW + timedelta(seconds=2),
        terminal_state_ref=_SHA_B,
        checkpoint_ref="checkpoint://run-1/terminal",
        terminal_node_ids=("publish",),
        gate_evidence_refs=(_SHA_C,),
        artifacts=tuple(artifacts),
        publication=publication,
    )


def test_graph_terminal_manifest_round_trips_with_canonical_hash() -> None:
    artifact = _artifact()
    manifest = _manifest(artifact, publication=_publication())

    payload = json.loads(json.dumps(manifest.to_dict()))
    restored = parse_graph_terminal_manifest(payload, expected_run_id="run-1")

    assert restored == manifest
    assert restored.schema_version == GRAPH_TERMINAL_MANIFEST_SCHEMA
    assert restored.manifest_hash == graph_terminal_manifest_hash(restored)
    assert restored.artifact("analysis") == artifact
    assert restored.publication == _publication()


def test_graph_terminal_manifest_rejects_hash_tampering() -> None:
    payload = _manifest(_artifact()).to_dict()
    payload["graph_version"] = "2"

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphTerminalManifest.from_dict(payload)

    assert raised.value.code is GraphTerminalManifestErrorCode.HASH_MISMATCH
    assert raised.value.field == "manifest_hash"


def test_graph_terminal_manifest_rejects_unknown_fields() -> None:
    payload = _manifest().to_dict()
    payload["workflow_id"] = "legacy"

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphTerminalManifest.from_dict(payload)

    assert raised.value.code is GraphTerminalManifestErrorCode.SCHEMA_INVALID


def test_graph_terminal_manifest_rejects_run_identity_mismatch() -> None:
    payload = _manifest().to_dict()

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphTerminalManifest.from_dict(payload, expected_run_id="run-2")

    assert raised.value.code is GraphTerminalManifestErrorCode.IDENTITY_MISMATCH


@pytest.mark.parametrize("field_name", ["graph_version", "graph_schema_version", "compiler_version"])
@pytest.mark.parametrize("moving_version", ["latest", "current", "default", "stable"])
def test_graph_terminal_manifest_rejects_moving_versions(
    field_name: str,
    moving_version: str,
) -> None:
    values = {
        "graph_version": "1",
        "graph_schema_version": "1",
        "compiler_version": "1",
    }
    values[field_name] = moving_version

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphTerminalManifest(
            tenant_id="tenant-1",
            run_id="run-1",
            graph_id="research.paper-analysis",
            normalized_graph_checksum=_SHA_A,
            status="succeeded",
            started_at=_NOW,
            completed_at=_NOW + timedelta(seconds=2),
            terminal_state_ref=_SHA_B,
            checkpoint_ref="checkpoint://run-1/terminal",
            terminal_node_ids=("publish",),
            gate_evidence_refs=(_SHA_C,),
            **values,
        )

    assert raised.value.field == field_name


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secret.json",
        "/absolute.json",
        "C:secret.json",
        "\\\\server\\share\\secret.json",
        "nodes//output.json",
        "nodes/CON/output.json",
        "nodes/output.json. ",
    ],
)
def test_graph_terminal_artifact_rejects_unsafe_paths(relative_path: str) -> None:
    with pytest.raises(GraphTerminalManifestError) as raised:
        _artifact(relative_path=relative_path)

    assert raised.value.code is GraphTerminalManifestErrorCode.SCHEMA_INVALID
    assert raised.value.field == "artifact.relative_path"


@pytest.mark.parametrize("identity", ["artifact_key", "artifact_id", "ref", "relative_path"])
def test_graph_terminal_manifest_rejects_duplicate_artifact_identity(identity: str) -> None:
    first = _artifact()
    overrides = {
        "artifact_key": "summary",
        "artifact_id": "summary-1",
        "ref": "artifact://run-1/summary-1",
        "relative_path": "nodes/summarize/summary.json",
    }
    overrides[identity] = getattr(first, identity)
    second = _artifact(**overrides)

    with pytest.raises(GraphTerminalManifestError) as raised:
        _manifest(first, second)

    assert raised.value.field == "artifacts.identity"


def test_graph_terminal_manifest_membership_is_immutable_and_rehashed() -> None:
    original = _manifest()
    with_member = original.with_artifact(_artifact())
    detached = with_member.without_artifact("analysis")

    assert original.artifacts == ()
    assert with_member.artifact("analysis") is not None
    assert with_member.manifest_hash != original.manifest_hash
    assert detached.artifacts == ()
    assert detached.manifest_hash == original.manifest_hash


def test_graph_terminal_manifest_missing_detach_target_is_typed() -> None:
    with pytest.raises(GraphTerminalManifestError) as raised:
        _manifest().without_artifact("missing")

    assert raised.value.code is GraphTerminalManifestErrorCode.ARTIFACT_NOT_FOUND


def test_graph_terminal_metadata_is_immutable_and_rejects_secrets() -> None:
    artifact = _artifact(metadata={"safe": {"revision": "1"}})

    with pytest.raises(TypeError):
        artifact.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(GraphTerminalManifestError):
        _artifact(metadata={"nested": {"api_key": "secret"}})


@pytest.mark.parametrize(
    "schema_version",
    ["newsroom.workflow_run_manifest.v1", "newsroom.workflow_run_manifest.v999"],
)
def test_legacy_workflow_manifest_returns_typed_history_quarantine(
    schema_version: str,
) -> None:
    payload = {
        "schema_version": schema_version,
        "run_id": "run-1",
    }

    with pytest.raises(GraphTerminalManifestHistoryError) as raised:
        parse_graph_terminal_manifest(payload, expected_run_id="run-1")

    diagnostic = raised.value.diagnostic
    assert isinstance(diagnostic, GraphManifestHistoryDiagnostic)
    assert diagnostic.to_dict() == {
        "code": "graph_terminal_manifest_history_quarantined",
        "run_id": "run-1",
        "observed_schema": schema_version,
        "disposition": "quarantine",
        "owner": "offline-graph-history-migrator",
        "resumable": False,
        "executable": False,
        "publishable": False,
    }


def test_unknown_graph_manifest_schema_fails_without_history_fallback() -> None:
    payload = _manifest().to_dict()
    payload["schema_version"] = "newsroom.graph-terminal-manifest/v999"

    with pytest.raises(GraphTerminalManifestError) as raised:
        parse_graph_terminal_manifest(payload, expected_run_id="run-1")

    assert not isinstance(raised.value, GraphTerminalManifestHistoryError)
    assert raised.value.code is GraphTerminalManifestErrorCode.SCHEMA_UNSUPPORTED


def test_publication_evidence_requires_publishable_artifact_and_bounded_time() -> None:
    with pytest.raises(GraphTerminalManifestError) as no_artifact:
        _manifest(publication=_publication())
    assert no_artifact.value.field == "publication.artifacts"

    artifact = replace(_artifact(), required_for_publication=False)
    with pytest.raises(GraphTerminalManifestError) as not_publishable:
        _manifest(artifact, publication=_publication())
    assert not_publishable.value.field == "publication.artifacts"

    late = replace(_publication(), committed_at=_NOW + timedelta(seconds=3))
    with pytest.raises(GraphTerminalManifestError) as outside_terminal_window:
        _manifest(_artifact(), publication=late)
    assert outside_terminal_window.value.field == "publication.committed_at"


def test_strict_reader_verifies_bytes_and_redacts_structured_content() -> None:
    content = b'{"token":"hidden","nested":{"api_key":"secret"},"safe":"ok"}'
    artifact = _artifact(content)
    port = _MemoryContentPort({("run-1", artifact.relative_path): content})

    record = GraphArtifactStrictContentReader(port).read(
        _manifest(artifact),
        "analysis",
    )

    assert record.content == {
        "token": "[redacted]",
        "nested": {"api_key": "[redacted]"},
        "safe": "ok",
    }
    assert record.content_checksum == _checksum(content)
    assert port.calls == [("run-1", "nodes/analyze/analysis.json")]


def test_strict_reader_decodes_ndjson_after_integrity_verification() -> None:
    content = b'{"value":1}\n{"token":"hidden"}\n'
    artifact = _artifact(content, media_type="application/x-ndjson")
    port = _MemoryContentPort({("run-1", artifact.relative_path): content})

    record = GraphArtifactStrictContentReader(port).read(
        _manifest(artifact),
        "analysis",
    )

    assert record.content == [{"value": 1}, {"token": "[redacted]"}]


def test_strict_reader_rejects_checksum_tampering() -> None:
    expected = b'{"status":"ok"}'
    tampered = b'{"status":"tampered"}'
    artifact = _artifact(expected)
    port = _MemoryContentPort({("run-1", artifact.relative_path): tampered})

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphArtifactStrictContentReader(port).read(_manifest(artifact), "analysis")

    assert raised.value.code is GraphTerminalManifestErrorCode.ARTIFACT_SIZE_MISMATCH


def test_strict_reader_rejects_same_size_checksum_tampering() -> None:
    expected = b'{"status":"ok"}'
    tampered = b'{"status":"no"}'
    assert len(tampered) == len(expected)
    artifact = _artifact(expected)
    port = _MemoryContentPort({("run-1", artifact.relative_path): tampered})

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphArtifactStrictContentReader(port).read(_manifest(artifact), "analysis")

    assert raised.value.code is GraphTerminalManifestErrorCode.ARTIFACT_CHECKSUM_MISMATCH


def test_strict_reader_rejects_invalid_json_after_integrity_verification() -> None:
    content = b'{"duplicate":1,"duplicate":2}'
    artifact = _artifact(content)
    port = _MemoryContentPort({("run-1", artifact.relative_path): content})

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphArtifactStrictContentReader(port).read(_manifest(artifact), "analysis")

    assert raised.value.code is GraphTerminalManifestErrorCode.ARTIFACT_CONTENT_INVALID


def test_strict_reader_rejects_content_over_bound() -> None:
    content = b"1234"
    artifact = _artifact(content, media_type="application/octet-stream")
    port = _MemoryContentPort({("run-1", artifact.relative_path): content})

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphArtifactStrictContentReader(port, max_content_bytes=3).read(
            _manifest(artifact),
            "analysis",
        )

    assert raised.value.code is GraphTerminalManifestErrorCode.ARTIFACT_CONTENT_TOO_LARGE


def test_strict_reader_rejects_unknown_artifact_before_port_call() -> None:
    port = _MemoryContentPort({})

    with pytest.raises(GraphTerminalManifestError) as raised:
        GraphArtifactStrictContentReader(port).read(_manifest(), "missing")

    assert raised.value.code is GraphTerminalManifestErrorCode.ARTIFACT_NOT_FOUND
    assert port.calls == []


def test_graph_artifact_owner_does_not_import_legacy_workflow() -> None:
    owner_root = Path(__file__).parents[4] / "framework" / "harness" / "artifacts"
    imports: list[str] = []
    for path in sorted(owner_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.append(node.module)

    assert not [name for name in imports if name.startswith("framework.workflow")]


def test_manifest_hash_changes_when_publication_evidence_changes() -> None:
    artifact = _artifact()
    first = _manifest(artifact, publication=_publication())
    second_publication = replace(_publication(), artifact_evidence_ref=_SHA_A)
    second = _manifest(artifact, publication=second_publication)

    assert first.manifest_hash != second.manifest_hash
