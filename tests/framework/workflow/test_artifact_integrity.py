from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
)
from framework.workflow.inspection.inspector import (
    WorkflowRunInspector,
    read_strict_workflow_artifact_content,
)
from framework.artifacts.observability import (
    ARTIFACT_CHECKSUM_MISMATCH_EVENT,
    ARTIFACT_CHECKSUM_MISSING_EVENT,
    ARTIFACT_METADATA_CORRUPT_EVENT,
    ARTIFACT_OBSERVABILITY_LOGGER,
)
from tests.fixtures.workflow_runs import (
    CanonicalWorkflowRunFixture,
    rewrite_manifest,
    write_canonical_terminal_run,
)


def test_strict_artifact_read_verifies_before_decoding_and_redaction(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(
        tmp_path,
        terminal_content={"token": "hidden", "status": "ok"},
    )

    record = read_strict_workflow_artifact_content(
        fixture.run_dir,
        fixture.manifest,
        "output",
    )

    assert record.content == {"status": "ok", "token": "[redacted]"}
    assert record.size_bytes == fixture.artifact_path("output").stat().st_size


def test_strict_artifact_read_rejects_tampered_bytes(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").write_bytes(b'{"status":"tampered"}')

    with pytest.raises(ArtifactChecksumMismatchError, match="output"):
        read_strict_workflow_artifact_content(
            fixture.run_dir,
            fixture.manifest,
            "output",
        )


def test_strict_direct_checksum_mismatch_emits_once_without_content(
    tmp_path: Path,
    caplog,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    secret = "MISMATCH-SECRET-CONTENT"
    fixture.artifact_path("output").write_text(secret, encoding="utf-8")
    caplog.set_level("WARNING", logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactChecksumMismatchError):
        read_strict_workflow_artifact_content(
            fixture.run_dir,
            fixture.manifest,
            "output",
        )

    records = _artifact_event_records(caplog)
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_CHECKSUM_MISMATCH_EVENT
    ]
    assert records[0].artifact_event_dimensions == {
        "store": "strict_workflow",
        "operation": "strict_read",
    }
    assert secret not in records[0].getMessage()


@pytest.mark.parametrize("checksum", [None, "pending", "A" * 64, "not-a-checksum"])
def test_strict_artifact_read_rejects_missing_or_invalid_checksum(
    tmp_path: Path,
    checksum: object,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = _manifest_copy(fixture)
    if checksum is None:
        manifest["artifact_metadata"]["output"].pop("checksum")
    else:
        manifest["artifact_metadata"]["output"]["checksum"] = checksum
    rewrite_manifest(fixture, manifest)

    with pytest.raises(ArtifactStoreMetadataError):
        read_strict_workflow_artifact_content(fixture.run_dir, manifest, "output")


def test_strict_direct_read_emits_missing_checksum_once(tmp_path: Path, caplog) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = _manifest_copy(fixture)
    manifest["artifact_metadata"]["output"].pop("checksum")
    rewrite_manifest(fixture, manifest)
    caplog.set_level("WARNING", logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactStoreMetadataError):
        read_strict_workflow_artifact_content(fixture.run_dir, manifest, "output")

    records = _artifact_event_records(caplog)
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_CHECKSUM_MISSING_EVENT
    ]
    assert records[0].artifact_event_dimensions == {"store": "strict_workflow"}


def test_strict_replay_emits_metadata_corrupt_once(tmp_path: Path, caplog) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = _manifest_copy(fixture)
    manifest.pop("workflow_id")
    rewrite_manifest(fixture, manifest)
    caplog.set_level("WARNING", logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactStoreMetadataError):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )

    records = _artifact_event_records(caplog)
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_METADATA_CORRUPT_EVENT
    ]
    assert records[0].artifact_event_dimensions == {"store": "strict_workflow"}


def test_strict_replay_emits_missing_checksum_once(tmp_path: Path, caplog) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = _manifest_copy(fixture)
    manifest["artifact_metadata"]["output"].pop("checksum")
    rewrite_manifest(fixture, manifest)
    caplog.set_level("WARNING", logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactStoreMetadataError):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )

    records = _artifact_event_records(caplog)
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_CHECKSUM_MISSING_EVENT
    ]
    assert records[0].artifact_event_dimensions == {"store": "strict_workflow"}


def test_strict_artifact_read_rejects_missing_file(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").unlink()

    with pytest.raises(ArtifactNotFoundError, match="output.json"):
        read_strict_workflow_artifact_content(
            fixture.run_dir,
            fixture.manifest,
            "output",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_type", ""),
        ("content_type", 1),
        ("size_bytes", True),
        ("size_bytes", -1),
        ("size_bytes", "1"),
    ],
)
def test_strict_artifact_read_rejects_invalid_optional_metadata_shape(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = _manifest_copy(fixture)
    manifest["artifact_metadata"]["output"][field] = value
    rewrite_manifest(fixture, manifest)

    with pytest.raises(ArtifactStoreMetadataError):
        read_strict_workflow_artifact_content(fixture.run_dir, manifest, "output")


def test_strict_artifact_read_rejects_invalid_canonical_manifest_before_target_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = _manifest_copy(fixture)
    manifest.pop("workflow_id")
    rewrite_manifest(fixture, manifest)
    output_path = fixture.artifact_path("output")
    original_read_bytes = Path.read_bytes

    def reject_target_read(path: Path) -> bytes:
        if path == output_path:
            raise AssertionError("invalid manifest must fail before target read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_target_read)

    with pytest.raises(ArtifactStoreMetadataError, match="canonical run manifest"):
        read_strict_workflow_artifact_content(
            fixture.run_dir,
            fixture.manifest,
            "output",
        )


def test_strict_artifact_read_accepts_only_manifest_pending_sentinel(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)

    record = read_strict_workflow_artifact_content(
        fixture.run_dir,
        fixture.manifest,
        "manifest",
    )

    assert record.content["artifact_metadata"]["manifest"]["checksum"] == "pending"
    assert record.content["run_id"] == "run-1"


@pytest.mark.parametrize(
    ("artifact_key", "replacement", "assertion"),
    [
        ("output", b'{"result":"tampered"}', lambda bundle: bundle.artifact_by_key("output").content["result"] == "verified-original"),
        ("events", b'{"event_type":"tampered","payload":{}}\n', lambda bundle: all(event["event_type"] != "tampered" for event in bundle.events)),
        ("step_results", b'{"write":{"status":"tampered"}}', lambda bundle: bundle.step_results["write"]["status"] == "succeeded"),
    ],
)
def test_strict_replay_returns_captured_bytes_after_preflight_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_key: str,
    replacement: bytes,
    assertion,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    target = fixture.artifact_path(artifact_key)
    original_read_bytes = Path.read_bytes
    replaced = False

    def replace_after_capture(path: Path) -> bytes:
        nonlocal replaced
        data = original_read_bytes(path)
        if path == target and not replaced:
            replaced = True
            target.write_bytes(replacement)
        return data

    monkeypatch.setattr(Path, "read_bytes", replace_after_capture)
    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    assert replaced is True
    assert assertion(bundle)


def test_strict_replay_returns_captured_manifest_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    original_read_bytes = Path.read_bytes
    reads = 0

    def replace_after_capture(path: Path) -> bytes:
        nonlocal reads
        captured = original_read_bytes(path)
        if path == fixture.manifest_path:
            reads += 1
            if reads == 1:
                fixture.manifest_path.write_bytes(
                    json.dumps({"run_id": "tampered"}).encode("utf-8")
                )
        return captured

    monkeypatch.setattr(Path, "read_bytes", replace_after_capture)
    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    assert reads == 1
    assert bundle.manifest["run_id"] == "run-1"
    manifest_record = bundle.artifact_by_key("manifest")
    assert manifest_record is not None
    assert manifest_record.content["run_id"] == "run-1"


def test_strict_replay_post_preflight_never_uses_path_readers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    output_path = fixture.artifact_path("output")
    original_read_bytes = Path.read_bytes
    reads: dict[Path, int] = {}

    def count_reads(path: Path) -> bytes:
        reads[path] = reads.get(path, 0) + 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", count_reads)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict replay must not call Path.read_text")
        ),
    )
    monkeypatch.setattr(
        "framework.workflow.inspection.inspector.read_workflow_artifact_content",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict replay must not call tolerant artifact reader")
        ),
    )
    monkeypatch.setattr(
        "framework.workflow.inspection.inspector._read_json_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict replay must not call _read_json_file")
        ),
    )
    monkeypatch.setattr(
        "framework.workflow.inspection.inspector.read_artifact_index_content_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict replay must not call tolerant index reader")
        ),
    )
    inspector = WorkflowRunInspector(tmp_path)
    monkeypatch.setattr(
        inspector,
        "read_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict replay must not call read_events")
        ),
    )
    monkeypatch.setattr(
        inspector,
        "read_json_artifact",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict replay must not call read_json_artifact")
        ),
    )

    bundle = inspector.build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    assert bundle.artifact_by_key("output").content["result"] == "verified-original"
    assert reads[output_path] == 1
    assert all(count == 1 for count in reads.values())


def test_strict_index_replay_never_uses_tolerant_path_readers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    _write_index_run(tmp_path, [_index_entry(content, nested=True)], content)
    monkeypatch.setattr(
        "framework.workflow.inspection.inspector._read_json_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict index must parse verified bytes")
        ),
    )
    monkeypatch.setattr(
        "framework.workflow.inspection.inspector.read_artifact_index_content_records",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("strict index must not call tolerant index reader")
        ),
    )

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    assert bundle.artifact_by_key("source_artifacts.source_item.feed.item-1") is not None


@pytest.mark.parametrize("artifact_key", ["output", "events"])
def test_strict_replay_redacts_structured_content_before_truncation(
    tmp_path: Path,
    artifact_key: str,
) -> None:
    secret = "TRUNCATED-SECRET-XYZ"
    fixture = write_canonical_terminal_run(
        tmp_path,
        events=[
            {
                "event_type": "workflow_started",
                "run_id": "run-1",
                "payload": {"token": secret, "padding": "x" * 200},
            }
        ],
        terminal_content={"token": secret, "padding": "x" * 200},
    )

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
        max_artifact_bytes=80,
    )

    record = bundle.artifact_by_key(artifact_key)
    assert record is not None
    assert record.truncated is True
    assert secret not in json.dumps(record.content)
    assert record.content["redacted"] is True
    assert record.content["preview_size_bytes"] == 80


def test_strict_replay_text_and_binary_preview_truncation(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(
        tmp_path,
        extra_artifacts={
            "notes": ("notes.txt", b"abcdefghij"),
            "blob": ("blob.bin", bytes(range(10))),
        },
    )

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
        max_artifact_bytes=4,
    )

    notes = bundle.artifact_by_key("notes")
    blob = bundle.artifact_by_key("blob")
    assert notes is not None and notes.content == "abcd" and notes.truncated is True
    assert blob is not None and blob.truncated is True
    assert blob.content == {
        "encoding": "hex",
        "bytes_preview": "00010203",
        "preview_size_bytes": 4,
    }


def test_strict_replay_uses_actual_manifest_snapshot_size(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest_size = fixture.manifest_path.stat().st_size
    assert fixture.manifest["artifact_metadata"]["manifest"]["size_bytes"] == 0

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    record = bundle.artifact_by_key("manifest")
    assert record is not None
    assert record.size_bytes == manifest_size
    assert record.metadata["size_bytes"] == 0


def test_strict_replay_preflights_all_artifacts_before_content_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").write_bytes(b'{"status":"tampered"}')

    monkeypatch.setattr(
        "framework.workflow.inspection.inspector._content_record_from_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("artifact content must not expand before strict preflight")
        ),
    )

    with pytest.raises(ArtifactChecksumMismatchError, match="output"):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


def test_replay_content_bundle_keeps_non_strict_default(tmp_path: Path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").write_bytes(b'{"status":"tampered"}')

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(run_id="run-1")

    assert bundle.artifact_by_key("output").content == {"status": "tampered"}


def test_strict_replay_verifies_index_top_level_checksum(tmp_path: Path) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=False)
    fixture = _write_index_run(tmp_path, [entry], content)

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    record = bundle.artifact_by_key("source_artifacts.source_item.feed.item-1")
    assert record is not None
    assert record.content == {"item": {"title": "verified"}}


def test_strict_replay_verifies_index_nested_checksum_fallback(tmp_path: Path) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=True)
    _write_index_run(tmp_path, [entry], content)

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    assert bundle.artifact_by_key("source_artifacts.source_item.feed.item-1") is not None


@pytest.mark.parametrize(
    ("location", "value"),
    [
        ("top", None),
        ("top", 7),
        ("nested", None),
        ("nested", 7),
    ],
)
def test_strict_replay_rejects_explicit_invalid_checksum_declaration(
    tmp_path: Path,
    location: str,
    value: object,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=True)
    if location == "top":
        entry["checksum"] = value
    else:
        entry["checksum"] = sha256(content).hexdigest()
        entry["artifact_ref"]["checksum"] = value
    _write_index_run(tmp_path, [entry], content)

    with pytest.raises(ArtifactStoreMetadataError, match="lowercase SHA-256"):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_checksum",
        "conflicting_checksum",
        "unsafe_path",
        "missing_target",
        "non_regular",
        "duplicate_key",
        "size_mismatch",
        "content_type_mismatch",
    ],
)
def test_strict_replay_rejects_invalid_index_entry_as_one_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=True)
    entries = [entry]
    if mutation == "missing_checksum":
        entry["artifact_ref"].pop("checksum")
    elif mutation == "conflicting_checksum":
        entry["checksum"] = "0" * 64
    elif mutation == "unsafe_path":
        entry["path"] = entry["artifact_ref"]["path"] = "../outside.json"
    elif mutation == "duplicate_key":
        entries.append(json.loads(json.dumps(entry)))
    elif mutation == "size_mismatch":
        entry["size_bytes"] = entry["artifact_ref"]["size_bytes"] = len(content) + 1
    elif mutation == "content_type_mismatch":
        entry["content_type"] = entry["artifact_ref"]["content_type"] = "text/plain"
    fixture = _write_index_run(tmp_path, entries, content)
    target = fixture.run_dir / "sources/items/feed/item-1.json"
    if mutation == "missing_target":
        target.unlink()
    elif mutation == "non_regular":
        target.unlink()
        target.mkdir()

    monkeypatch.setattr(
        "framework.workflow.inspection.inspector._content_record_from_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("no replay content may decode before complete index preflight")
        ),
    )
    expected = ArtifactPathError if mutation == "unsafe_path" else (
        ArtifactNotFoundError if mutation == "missing_target" else ArtifactStoreMetadataError
    )
    with pytest.raises(expected):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


def test_strict_replay_rejects_tampered_index_target(tmp_path: Path) -> None:
    content = b'{"item":{"title":"verified"}}'
    fixture = _write_index_run(tmp_path, [_index_entry(content, nested=True)], content)
    (fixture.run_dir / "sources/items/feed/item-1.json").write_bytes(b'{"tampered":true}')

    with pytest.raises(ArtifactChecksumMismatchError):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


def test_strict_index_checksum_mismatch_emits_once(
    tmp_path: Path,
    caplog,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    fixture = _write_index_run(tmp_path, [_index_entry(content, nested=True)], content)
    (fixture.run_dir / "sources/items/feed/item-1.json").write_bytes(b"tampered-secret")
    caplog.set_level("WARNING", logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactChecksumMismatchError):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )

    records = _artifact_event_records(caplog)
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_CHECKSUM_MISMATCH_EVENT
    ]
    assert records[0].artifact_event_dimensions == {
        "store": "strict_workflow",
        "operation": "strict_read",
    }


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("top", "run_id", "other-run"),
        ("nested", "run_id", "other-run"),
        ("top", "artifact_id", 7),
        ("nested", "artifact_type", ""),
    ],
)
def test_strict_replay_rejects_invalid_index_identity(
    tmp_path: Path,
    location: str,
    field: str,
    value: object,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=True)
    target = entry if location == "top" else entry["artifact_ref"]
    target[field] = value
    _write_index_run(tmp_path, [entry], content)

    with pytest.raises(ArtifactStoreMetadataError):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


def test_strict_replay_rejects_top_nested_identity_conflict(tmp_path: Path) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=True)
    entry["artifact_ref"]["artifact_id"] = "other-id"
    _write_index_run(tmp_path, [entry], content)

    with pytest.raises(ArtifactStoreMetadataError, match="artifact_id declarations conflict"):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


@pytest.mark.parametrize("field", ["artifact_id", "run_id", "artifact_type", "path"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_strict_replay_requires_nested_canonical_identity_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    entry = _index_entry(content, nested=True)
    if value is None:
        entry["artifact_ref"].pop(field)
    else:
        entry["artifact_ref"][field] = value
    _write_index_run(tmp_path, [entry], content)

    with pytest.raises(ArtifactStoreMetadataError, match="artifact_ref field"):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


def test_strict_replay_returns_captured_index_target_after_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b'{"item":{"title":"verified"}}'
    fixture = _write_index_run(tmp_path, [_index_entry(content, nested=True)], content)
    target = fixture.run_dir / "sources/items/feed/item-1.json"
    original_read_bytes = Path.read_bytes
    replaced = False

    def replace_after_capture(path: Path) -> bytes:
        nonlocal replaced
        captured = original_read_bytes(path)
        if path == target and not replaced:
            replaced = True
            target.write_bytes(b'{"item":{"title":"tampered"}}')
        return captured

    monkeypatch.setattr(Path, "read_bytes", replace_after_capture)
    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    assert replaced is True
    record = bundle.artifact_by_key("source_artifacts.source_item.feed.item-1")
    assert record is not None
    assert record.content["item"]["title"] == "verified"


def test_strict_replay_preserves_source_response_business_content_type(tmp_path: Path) -> None:
    content = b'{"headers":{"Content-Type":"application/rss+xml"}}'
    entry = _index_entry(
        content,
        nested=True,
        artifact_type="source_response_headers",
    )
    entry["content_type"] = "application/rss+xml"
    fixture = _write_index_run(tmp_path, [entry], content)

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    record = bundle.artifact_by_key(
        "source_artifacts.source_response_headers.feed.item-1"
    )
    assert record is not None
    assert record.content_type == "application/json"
    assert record.metadata["content_type"] == "application/rss+xml"
    assert record.metadata["artifact_ref"]["content_type"] == "application/json"


def test_strict_replay_uses_nested_source_response_identity_for_dual_content_type(
    tmp_path: Path,
) -> None:
    content = b'{"headers":{"Content-Type":"application/rss+xml"}}'
    entry = _index_entry(
        content,
        nested=True,
        artifact_type="source_response_headers",
    )
    entry.pop("artifact_type")
    entry["content_type"] = "application/rss+xml"
    _write_index_run(tmp_path, [entry], content)

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
    )

    record = bundle.artifact_by_key(
        "source_artifacts.source_response_headers.feed.item-1"
    )
    assert record is not None
    assert record.content_type == "application/json"
    assert record.metadata["content_type"] == "application/rss+xml"


def test_strict_replay_redacts_index_json_before_truncation(tmp_path: Path) -> None:
    secret = "INDEX-TRUNCATED-SECRET"
    content = json.dumps(
        {"item": {"token": secret, "padding": "x" * 200}},
        separators=(",", ":"),
    ).encode("utf-8")
    _write_index_run(tmp_path, [_index_entry(content, nested=True)], content)

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(
        run_id="run-1",
        strict_artifact_integrity=True,
        max_artifact_bytes=80,
    )

    record = bundle.artifact_by_key("source_artifacts.source_item.feed.item-1")
    assert record is not None and record.truncated is True
    assert secret not in json.dumps(record.content)
    assert record.content["redacted"] is True


def _write_index_run(
    root: Path,
    entries: list[dict[str, object]],
    target_content: bytes,
) -> CanonicalWorkflowRunFixture:
    index_bytes = json.dumps(
        {"entries": entries},
        separators=(",", ":"),
    ).encode("utf-8")
    fixture = write_canonical_terminal_run(
        root,
        extra_artifacts={
            "source_artifacts": ("source_artifacts/index.json", index_bytes),
        },
    )
    target = fixture.run_dir / "sources/items/feed/item-1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(target_content)
    return fixture


def _index_entry(
    content: bytes,
    *,
    nested: bool,
    artifact_type: str = "source_item",
) -> dict[str, object]:
    checksum = sha256(content).hexdigest()
    entry: dict[str, object] = {
        "artifact_id": "source-item-1",
        "artifact_type": artifact_type,
        "source_id": "feed",
        "object_id": "item-1",
        "path": "sources/items/feed/item-1.json",
        "size_bytes": len(content),
        "content_type": "application/json",
    }
    if nested:
        entry["artifact_ref"] = {
            "artifact_id": "source-item-1",
            "run_id": "run-1",
            "artifact_type": artifact_type,
            "path": "sources/items/feed/item-1.json",
            "size_bytes": len(content),
            "content_type": "application/json",
            "checksum": checksum,
        }
    else:
        entry["checksum"] = checksum
    return entry


def _manifest_copy(fixture: CanonicalWorkflowRunFixture) -> dict[str, object]:
    return json.loads(json.dumps(fixture.manifest))


def _artifact_event_records(caplog):
    return [
        record
        for record in caplog.records
        if record.name == ARTIFACT_OBSERVABILITY_LOGGER
    ]
