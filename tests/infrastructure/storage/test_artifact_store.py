from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

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


def _ref(
    artifact_id: str,
    *,
    run_id: str = "run-1",
    step_id: str | None = None,
    artifact_type: str = "report",
    created_at: datetime | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=run_id,
        step_id=step_id,
        artifact_type=artifact_type,
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
            content=b"original",
            content_type="text/plain",
        )
    )
    (tmp_path / "run-1" / ref.path).write_bytes(b"changed")

    with pytest.raises(ArtifactChecksumMismatchError):
        store.read(ref)


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
        store.write(ArtifactWriteRequest(run_id="../secret", artifact_type="report", content=b"{}"))

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list("../secret")

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


def test_local_json_artifact_index_store_supports_logical_artifact_ids(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    ref = replace(_ref("artifact-1"), artifact_id="tool:result:artifact-1")

    record_path = store.index_artifact(ref)

    assert record_path.name.startswith("a-")
    assert ":" not in record_path.name
    assert store.get_artifact("run-1", "tool:result:artifact-1") == ref
    assert store.list_by_run("run-1") == [ref]

    store.delete_artifact("run-1", "tool:result:artifact-1")

    with pytest.raises(ArtifactIndexNotFoundError):
        store.get_artifact("run-1", "tool:result:artifact-1")


@pytest.mark.parametrize("artifact_id", [None, "", " \t"])
def test_local_json_artifact_index_store_requires_nonblank_string_artifact_id(
    tmp_path,
    artifact_id,
) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    ref = replace(_ref("artifact-1"), artifact_id=artifact_id)

    with pytest.raises(ValueError, match="artifact_id is required"):
        store.index_artifact(ref)
    with pytest.raises(ValueError, match="artifact_id is required"):
        store.get_artifact("run-1", artifact_id)
    with pytest.raises(ValueError, match="artifact_id is required"):
        store.delete_artifact("run-1", artifact_id)

    assert not list(tmp_path.iterdir())


def test_local_json_artifact_index_store_rejects_unsafe_filesystem_fields(tmp_path) -> None:
    store = LocalJsonArtifactIndexStore(tmp_path)
    base = _ref("artifact-1", step_id="draft_report")
    unsafe_refs = [
        (replace(base, run_id="../secret"), "invalid run_id"),
        (replace(base, step_id="../step"), "invalid step_id"),
        (replace(base, path="../secret.json"), "invalid artifact path"),
    ]

    for ref, message in unsafe_refs:
        with pytest.raises(ValueError, match=message):
            store.index_artifact(ref)

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
        store.get_artifact("run-1", "missing")

    with pytest.raises(ValueError, match="invalid run_id"):
        store.list_by_run("../secret")

    with pytest.raises(ValueError, match="invalid step_id"):
        store.list_by_step("run-1", "../step")

    with pytest.raises(ValueError, match="artifact_type is required"):
        store.list_by_type("")


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
