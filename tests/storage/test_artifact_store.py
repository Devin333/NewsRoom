from datetime import UTC, datetime
from hashlib import sha256

import pytest

from storage.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactIndexNotFoundError,
    ArtifactNotFoundError,
    ArtifactRef,
    ArtifactWriteRequest,
    FilesystemArtifactStore,
    LocalJsonArtifactIndexStore,
)


def _ref(
    artifact_id: str,
    *,
    step_id: str | None = None,
    created_at: datetime | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id="run-1",
        step_id=step_id,
        artifact_type="report",
        path=f"artifacts/report/{artifact_id}.json",
        content_type="application/json",
        size_bytes=2,
        checksum=sha256(b"{}").hexdigest(),
        redacted=True,
        created_at=created_at or datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        metadata={"source": "test"},
    )


def test_artifact_ref_round_trips() -> None:
    ref = _ref("artifact-1", step_id="draft_report")

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
            step_id="draft_report",
            artifact_type="report",
            content=content,
            content_type="application/json",
            created_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC),
            metadata={"stage": "draft"},
        )
    )

    assert ref.path == "steps/draft_report/artifacts/report-1.json"
    assert ref.size_bytes == len(content)
    assert ref.checksum == sha256(content).hexdigest()
    assert (tmp_path / "run-1" / ref.path).read_bytes() == content
    assert store.exists(ref) is True
    assert store.read(ref) == content

    store.delete(ref)

    assert store.exists(ref) is False
    with pytest.raises(ArtifactNotFoundError):
        store.read(ref)


def test_filesystem_artifact_store_detects_checksum_mismatch(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    ref = store.write(
        ArtifactWriteRequest(
            run_id="run-1",
            artifact_id="artifact-1",
            artifact_type="report",
            content=b"original",
            content_type="text/plain",
        )
    )
    (tmp_path / "run-1" / ref.path).write_bytes(b"changed")

    with pytest.raises(ArtifactChecksumMismatchError):
        store.read(ref)


def test_filesystem_artifact_store_rejects_unsafe_ids_and_paths(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="invalid run_id"):
        store.write(ArtifactWriteRequest(run_id="../secret", artifact_type="report", content=b"{}"))

    with pytest.raises(ValueError, match="invalid artifact_id"):
        store.write(
            ArtifactWriteRequest(
                run_id="run-1",
                artifact_id="nested/artifact",
                artifact_type="report",
                content=b"{}",
            )
        )

    with pytest.raises(ValueError, match="invalid artifact path"):
        store.write(
            ArtifactWriteRequest(
                run_id="run-1",
                artifact_id="artifact-1",
                artifact_type="report",
                content=b"{}",
                relative_path="../secret.json",
            )
        )


def test_local_json_artifact_index_store_indexes_by_run_and_step(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    first = _ref("artifact-1", step_id="draft_report", created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC))
    second = _ref("artifact-2", step_id="editor_review", created_at=datetime(2026, 5, 11, 2, 0, tzinfo=UTC))

    first_path = store.index_artifact(first)
    second_path = store.index_artifact(second)

    assert first_path.exists()
    assert second_path.exists()
    assert store.get_artifact("run-1", "artifact-1") == first
    assert [ref.artifact_id for ref in store.list_by_run("run-1")] == ["artifact-1", "artifact-2"]
    assert store.list_by_step("run-1", "draft_report") == [first]
    assert store.list_by_step("run-1", "missing") == []


def test_local_json_artifact_index_store_handles_missing_and_rejects_unsafe_ids(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)

    assert store.list_by_run("missing") == []

    with pytest.raises(ArtifactIndexNotFoundError):
        store.get_artifact("run-1", "missing")

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="invalid step_id"):
        store.list_by_step("run-1", "../step")
