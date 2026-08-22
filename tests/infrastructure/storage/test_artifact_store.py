from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json

import pytest

from infrastructure.storage.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactIndexNotFoundError,
    ArtifactNotFoundError,
    ArtifactRef,
    ArtifactWriteRequest,
    FilesystemArtifactStore,
    LocalJsonArtifactIndexStore,
)
from framework.agent.artifacts.stores.errors import ArtifactStoreMetadataError
from framework.agent.artifacts.models import canonical_artifact_relative_path
from framework.shared.graph_identity import GraphStageIdentity


_CHECKSUM = f"sha256:{'a' * 64}"


def _ref(
    artifact_id: str,
    *,
    run_id: str = "run-1",
    artifact_type: str = "report",
    created_at: datetime | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=run_id,
        scope_kind="standalone",
        artifact_type=artifact_type,
        path=f"custom/{artifact_id}.json",
        content_type="application/json",
        size_bytes=2,
        checksum=sha256(b"{}").hexdigest(),
        redacted=True,
        created_at=created_at or datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )


def test_artifact_ref_round_trips() -> None:
    ref = _ref("artifact-1")

    restored = ArtifactRef.from_dict(ref.to_dict())

    assert restored == ref
    assert restored.to_dict()["created_at"] == "2026-05-11T01:00:00Z"


def test_filesystem_artifact_store_writes_reads_exists_and_deletes(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    content = b'{"status":"ok"}'

    ref = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="report-1",
            artifact_type="report",
            scope_kind="standalone",
            content=content,
            content_type="application/json",
            created_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC),
            metadata={"stage": "draft"},
        )
    )

    assert ref.path.startswith("objects/")
    assert ref.size_bytes == len(content)
    assert ref.checksum == sha256(content).hexdigest()
    assert (tmp_path / "run-1" / ref.path).read_bytes() == content
    assert store.exists(ref) is True
    assert store.list("run-1") == [ref.path]
    assert store.checksum(ref) == ref.checksum
    assert store.read(ref) == content

    store.delete(ref)

    assert store.exists(ref) is False
    assert store.list("run-1") == []
    with pytest.raises(ArtifactNotFoundError):
        store.read(ref)


def test_filesystem_artifact_store_detects_checksum_mismatch(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    ref = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="artifact-1",
            artifact_type="report",
            scope_kind="standalone",
            content=b"original",
            content_type="text/plain",
        )
    )
    (tmp_path / "run-1" / ref.path).write_bytes(b"changed")

    with pytest.raises(ArtifactChecksumMismatchError):
        store.read(ref)


def test_filesystem_artifact_store_fences_graph_node_instances_and_conflicts(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    common = {
        "run_id": "run-1",
        "artifact_id": "report-1",
        "scope_kind": "graph",
        "graph_id": "research",
        "graph_version": "v1",
        "graph_ref": "research@v1",
        "graph_checksum": _CHECKSUM,
        "node_id": "analyze",
        "artifact_type": "report",
        "content_type": "application/json",
    }
    left = store.write(
        ArtifactWriteRequest(
            **common,
            node_instance_id="analyze:loop:1",
            content=b'{"node":"left"}',
        )
    )
    right = store.write(
        ArtifactWriteRequest(
            **common,
            node_instance_id="analyze:loop:2",
            content=b'{"node":"right"}',
        )
    )

    assert left.path != right.path
    assert store.read(left) == b'{"node":"left"}'
    assert store.read(right) == b'{"node":"right"}'
    duplicate = store.write(
        ArtifactWriteRequest(
            **common,
            node_instance_id="analyze:loop:1",
            content=b'{"node":"left"}',
        )
    )
    assert duplicate.path == left.path
    assert duplicate.checksum == left.checksum
    assert duplicate.artifact_id == left.artifact_id

    with pytest.raises(ArtifactStoreMetadataError, match="identity conflict"):
        store.write(
            ArtifactWriteRequest(
                **common,
                node_instance_id="analyze:loop:1",
                content=b'{"node":"tampered"}',
            )
        )

    with pytest.raises(ValueError, match="relative_path"):
        store.write(ArtifactWriteRequest(
            **common,
            node_instance_id="analyze:loop:3",
            content=b"{}",
            relative_path="objects/foreign.json",
        ))


def test_artifact_ref_rejects_legacy_step_payload_and_graph_path_tamper(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    ref = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="report-1",
            scope_kind="graph",
            graph_id="research",
            graph_version="v1",
            graph_ref="research@v1",
            graph_checksum=_CHECKSUM,
            node_id="analyze",
            node_instance_id="analyze:loop:1",
            artifact_type="report",
            content=b"{}",
            content_type="application/json",
        )
    )
    legacy_payload = ref.to_dict() | {"step_id": "analyze"}
    with pytest.raises(ValueError, match="fields are invalid"):
        ArtifactRef.from_dict(legacy_payload)

    tampered = replace(ref)
    object.__setattr__(tampered, "path", "objects/foreign/report.json")
    with pytest.raises(ArtifactStoreMetadataError, match="does not match Graph identity"):
        store.read(tampered)


def test_artifact_ref_rejects_control_character_identity_tokens() -> None:
    with pytest.raises(ValueError, match="control character"):
        _ref("artifact-\x1f-1")

    with pytest.raises(ValueError, match="control character"):
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="artifact-\x1f-1",
            artifact_type="report",
            content=b"{}",
        )


def test_filesystem_artifact_store_list_rejects_link_escape(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run-1"
    outside = tmp_path / "outside"
    run_dir.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = run_dir / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is not available: {exc}")

    with pytest.raises(ValueError):
        store.list("run-1")


def test_filesystem_artifact_store_rejects_unsafe_ids_and_paths(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="invalid run_id"):
        store.write(ArtifactWriteRequest(run_id="../secret", artifact_type="report", scope_kind="standalone", content=b"{}"))

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list("../secret")

    with pytest.raises(ValueError, match="invalid artifact_id"):
        store.write(
            ArtifactWriteRequest(
                run_id="run-1",
                artifact_id="nested/artifact",
                scope_kind="standalone",
                artifact_type="report",
                content=b"{}",
            )
        )

    with pytest.raises(ValueError, match="invalid artifact path"):
        store.write(
        ArtifactWriteRequest(
                run_id="run-1",
                artifact_id="artifact-1",
                scope_kind="standalone",
                artifact_type="report",
                content=b"{}",
                relative_path="../secret.json",
            )
        )


def test_local_json_artifact_index_store_indexes_by_run(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    first = _ref("artifact-1", created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC))
    second = _ref("artifact-2", created_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC))

    first_path = store.index_artifact(first)
    second_path = store.index_artifact(second)

    assert first_path.exists()
    assert second_path.exists()
    assert store.get_artifact(first) == first
    assert [ref.artifact_id for ref in store.list_by_run("run-1")] == ["artifact-1", "artifact-2"]


def test_local_json_artifact_index_store_supports_logical_artifact_ids(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    ref = replace(_ref("artifact-1"), artifact_id="tool:result:artifact-1")

    record_path = store.index_artifact(ref)

    assert record_path.name.startswith("a-")
    assert ":" not in record_path.name
    assert store.get_artifact(ref) == ref
    assert store.list_by_run("run-1") == [ref]

    store.delete_artifact(ref)

    with pytest.raises(ArtifactIndexNotFoundError):
        store.get_artifact(ref)


@pytest.mark.parametrize("artifact_id", [None, "", " \t"])
def test_local_json_artifact_index_store_requires_nonblank_string_artifact_id(
    tmp_path,
    artifact_id,
) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    with pytest.raises(ValueError, match="artifact_id is required"):
        replace(_ref("artifact-1"), artifact_id=artifact_id)

    assert not list(tmp_path.iterdir())


def test_local_json_artifact_index_store_rejects_unsafe_filesystem_fields(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    base = _ref("artifact-1")
    with pytest.raises(ValueError, match="invalid run_id"):
        replace(base, run_id="../secret")
    with pytest.raises(ValueError, match="artifact path"):
        store.index_artifact(replace(base, path="../secret.json"))

    assert not list(tmp_path.iterdir())


def test_local_json_artifact_index_store_lists_by_type(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    first = _ref("artifact-1", artifact_type="report_json")
    second = _ref("artifact-2", artifact_type="events")
    third = _ref("artifact-3", run_id="run-2", artifact_type="report_json")

    store.index_artifact(second)
    store.index_artifact(first)
    store.index_artifact(third)

    assert [ref.artifact_id for ref in store.list_by_type("report_json")] == [
        "artifact-1",
        "artifact-3",
    ]
    assert store.list_by_type("report_json", run_id="run-1") == [first]


def test_local_json_artifact_index_store_lists_all_runs(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    first = _ref("artifact-1", run_id="run-1", created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC))
    second = _ref("artifact-2", run_id="run-2", created_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC))

    store.index_artifact(second)
    store.index_artifact(first)

    assert [ref.artifact_id for ref in store.list_all()] == ["artifact-1", "artifact-2"]


def test_local_json_artifact_index_store_handles_missing_and_rejects_unsafe_ids(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)

    assert store.list_by_run("missing") == []

    with pytest.raises(ArtifactIndexNotFoundError):
        store.get_artifact(_ref("missing"))

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="artifact_type is required"):
        store.list_by_type("")


def test_local_json_artifact_index_store_fences_exact_graph_identity(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    left = _graph_ref("shared", node_instance_id="analyze:1", attempt=1)
    retry = _graph_ref("shared", node_instance_id="analyze:1", attempt=2)
    right = _graph_ref("shared", node_instance_id="analyze:2", attempt=1)

    paths = {store.index_artifact(ref) for ref in (left, retry, right)}

    assert len(paths) == 3
    assert store.get_artifact(left) == left
    assert store.list_by_node_instance(_stage_identity("analyze:1")) == [left, retry]
    assert store.list_by_node_instance(
        _stage_identity("analyze:1"),
        activity_id="activity-1",
        attempt=2,
    ) == [retry]

    other_checksum = replace(
        _stage_identity("analyze:1"),
        graph_checksum=f"sha256:{'b' * 64}",
    )
    assert store.list_by_node_instance(other_checksum) == []

    store.delete_artifact(left)
    assert store.list_by_node_instance(_stage_identity("analyze:1")) == [retry]
    assert store.get_artifact(right) == right


def test_local_json_artifact_index_store_rejects_conflicting_duplicate(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    ref = _graph_ref("artifact-1", node_instance_id="analyze:1", attempt=1)
    store.index_artifact(ref)

    assert store.index_artifact(ref) == store.index_artifact(ref)
    with pytest.raises(ArtifactStoreMetadataError, match="identity conflict"):
        store.index_artifact(replace(ref, checksum=sha256(b"changed").hexdigest()))


def test_local_json_artifact_index_store_rejects_legacy_record(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    ref = _ref("artifact-1")
    record_path = store.index_artifact(ref)
    payload = ref.to_dict()
    payload.pop("scope_kind")
    payload["step_id"] = "analyze"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactStoreMetadataError, match="record is invalid"):
        store.list_by_run("run-1")


def test_local_json_artifact_index_store_rejects_linked_external_record(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path / "index")
    ref = _ref("artifact-1")
    record_path = store.index_artifact(ref)
    external = tmp_path / "external.json"
    external.write_text(record_path.read_text(encoding="utf-8"), encoding="utf-8")
    record_path.unlink()
    try:
        record_path.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation is not available: {exc}")

    with pytest.raises(ValueError):
        store.list_by_run("run-1")


def _stage_identity(node_instance_id: str) -> GraphStageIdentity:
    return GraphStageIdentity(
        run_id="run-1",
        graph_id="research",
        graph_version="v1",
        graph_ref="research@v1",
        graph_checksum=_CHECKSUM,
        node_id="analyze",
        node_instance_id=node_instance_id,
    )


def _graph_ref(
    artifact_id: str,
    *,
    node_instance_id: str,
    attempt: int,
) -> ArtifactRef:
    request = ArtifactWriteRequest(
        run_id="run-1",
        artifact_id=artifact_id,
        scope_kind="graph",
        graph_id="research",
        graph_version="v1",
        graph_ref="research@v1",
        graph_checksum=_CHECKSUM,
        node_id="analyze",
        node_instance_id=node_instance_id,
        activity_id="activity-1",
        attempt=attempt,
        artifact_type="report",
        content=b"{}",
        content_type="application/json",
    )
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=request.run_id,
        scope_kind=request.scope_kind,
        graph_id=request.graph_id,
        graph_version=request.graph_version,
        graph_ref=request.graph_ref,
        graph_checksum=request.graph_checksum,
        node_id=request.node_id,
        node_instance_id=request.node_instance_id,
        activity_id=request.activity_id,
        attempt=request.attempt,
        artifact_type=request.artifact_type,
        path=canonical_artifact_relative_path(request),
        content_type=request.content_type,
        size_bytes=2,
        checksum=sha256(b"{}").hexdigest(),
        created_at=datetime(2026, 5, 11, 1, attempt, tzinfo=UTC),
        metadata={"source": "graph-test"},
    )
