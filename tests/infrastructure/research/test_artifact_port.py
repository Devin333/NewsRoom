from __future__ import annotations

import json
import logging
import math
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
    compute_checksum,
)
from framework.harness import ArtifactWriteRequest
from framework.shared.json import stable_json_dumps
from framework.workflow.runtime.manifest import manifest_hash
from infrastructure.research.artifact_port import (
    ArtifactPublicationVisibilityError,
    ArtifactRunBindingError,
    ArtifactWriteConflictError,
    FilesystemHarnessArtifactPort,
)
from infrastructure.research.diagnostics import (
    MISSING_IDENTITY_REF,
    RESEARCH_PERSISTENCE_LOGGER,
    RESEARCH_PERSISTENCE_OPERATION_EVENT,
)


def test_run_binding_is_required_nested_and_reset(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    request = ArtifactWriteRequest("research-analysis", {"status": "ok"})

    with pytest.raises(ArtifactRunBindingError, match="bound run"):
        port.write_artifact(request)

    with port.bind_run("run-outer"):
        assert port.current_run_id == "run-outer"
        with port.bind_run("run-inner"):
            assert port.current_run_id == "run-inner"
        assert port.current_run_id == "run-outer"
    assert port.current_run_id is None


def test_round_trip_is_restart_safe_and_records_integrity_metadata(tmp_path) -> None:
    request = ArtifactWriteRequest(
        "research-analysis",
        {"status": "ok", "score": 0.9},
        metadata={"source": "research"},
    )
    port = FilesystemHarnessArtifactPort(tmp_path)

    with port.bind_run("run-1"):
        ref = port.write_artifact(request)

    content = stable_json_dumps(request.to_dict()).encode("utf-8")
    checksum = compute_checksum(content)
    assert ref.ref == "artifact://run-1/research-analysis"
    assert ref.checksum == f"sha256:{checksum}"
    assert (tmp_path / "run-1" / "artifacts" / "research-analysis.json").read_bytes() == content

    manifest = port.manager.read_run_manifest("run-1")
    metadata = manifest["artifact_metadata"]["research-analysis"]
    assert metadata == {
        "artifact_id": "research-analysis",
        "run_id": "run-1",
        "kind": "research-analysis",
        "path": "artifacts/research-analysis.json",
        "content_type": "application/json",
        "size_bytes": len(content),
        "checksum": checksum,
    }
    assert manifest["artifact_refs"][0]["content_hash"] == checksum
    assert manifest["artifact_index"][0]["run_id"] == "run-1"
    assert manifest["manifest_hash"] == manifest_hash(manifest)

    restarted = FilesystemHarnessArtifactPort(tmp_path)
    assert restarted.read_artifact(ref.ref) == request.to_dict()


def test_artifact_ref_verifier_checks_integrity_without_publication_access(
    tmp_path,
) -> None:
    publication_calls: list[object] = []
    port = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda claim: (publication_calls.append(claim) or False),
    )
    with port.bind_run("run-1"):
        ref = port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"status": "candidate"})
        )

    assert port.verify_artifact_ref(ref.ref, expected_run_id="run-1") is None
    assert publication_calls == []
    with pytest.raises(ArtifactPublicationVisibilityError):
        port.read_artifact(ref.ref)
    assert len(publication_calls) == 1


def test_artifact_ref_verifier_rejects_missing_and_cross_run_refs(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"status": "candidate"})
        )

    with pytest.raises(ArtifactRunBindingError, match="expected parent run"):
        port.verify_artifact_ref(ref.ref, expected_run_id="run-2")
    with pytest.raises(ArtifactNotFoundError):
        port.verify_artifact_ref(
            "artifact://missing-run/research-analysis",
            expected_run_id="missing-run",
        )


def test_verified_graph_result_member_is_excluded_from_public_member_set(
    tmp_path,
) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    identity = "a" * 64
    artifact_type = f"graph-result-{identity}"
    with port.bind_run("run-1"):
        port.write_artifact(
            ArtifactWriteRequest(
                artifact_type,
                {"candidate_checksum": f"sha256:{identity}"},
                metadata={
                    "run_id": "run-1",
                    "graph_result_ref_only": True,
                    "identity_checksum": f"sha256:{identity}",
                },
            )
        )
        port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"status": "candidate"},
                metadata={"run_id": "run-1"},
            )
        )

    manifest = port.manager.read_run_manifest("run-1")

    assert port._v2_artifact_types(manifest, run_id="run-1") == (
        "research-analysis",
    )


def test_graph_result_internal_reader_allows_only_verified_ref_only_objects(
    tmp_path,
) -> None:
    publication_calls: list[object] = []
    port = FilesystemHarnessArtifactPort(
        tmp_path,
        accepted_run_resolver=lambda claim: (publication_calls.append(claim) or False),
    )
    identity = "a" * 64
    artifact_type = f"graph-result-{identity}"
    with port.bind_run("run-1"):
        graph_ref = port.write_artifact(
            ArtifactWriteRequest(
                artifact_type,
                {"candidate_checksum": f"sha256:{identity}"},
                metadata={
                    "run_id": "run-1",
                    "graph_result_ref_only": True,
                    "identity_checksum": f"sha256:{identity}",
                },
            )
        )
        public_ref = port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"status": "candidate"},
                metadata={"run_id": "run-1"},
            )
        )

    assert port.read_graph_result_artifact(
        graph_ref.ref,
        expected_run_id="run-1",
    )["payload"] == {"candidate_checksum": f"sha256:{identity}"}
    assert publication_calls == []
    with pytest.raises(ArtifactStoreMetadataError, match="ref-only"):
        port.read_graph_result_artifact(
            public_ref.ref,
            expected_run_id="run-1",
        )
    with pytest.raises(ArtifactRunBindingError, match="expected run"):
        port.read_graph_result_artifact(
            graph_ref.ref,
            expected_run_id="run-2",
        )


def test_long_artifact_type_uses_bounded_hashed_path_without_changing_ref(
    tmp_path,
) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    artifact_type = "context-source-snapshot-" + "a" * 64

    with port.bind_run("run-1"):
        stored = port.write_artifact(
            ArtifactWriteRequest(
                artifact_type=artifact_type,
                payload={"snapshot": "verified"},
            )
        )

    manifest = port.manager.read_run_manifest("run-1")
    relative_path = manifest["artifacts"][artifact_type]
    assert stored.ref == f"artifact://run-1/{artifact_type}"
    assert relative_path.startswith("artifacts/a-")
    assert len(Path(relative_path).name) == 71
    assert port.read_artifact(stored.ref)["payload"] == {
        "snapshot": "verified"
    }


def test_same_type_identical_write_is_idempotent(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)

    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"version": 1}))
        duplicate = port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"version": 1})
        )

    manifest = port.manager.read_run_manifest("run-1")
    assert len(manifest["artifact_refs"]) == 1
    assert len(manifest["artifact_index"]) == 1
    assert duplicate == ref
    assert port.read_artifact(ref.ref)["payload"] == {"version": 1}


def test_same_type_different_write_fails_before_replacing_committed_bytes(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"version": 1}))
        with pytest.raises(ArtifactWriteConflictError, match="immutable"):
            port.write_artifact(
                ArtifactWriteRequest("research-analysis", {"version": 2})
            )

    assert port.read_artifact(ref.ref)["payload"] == {"version": 1}


def test_context_local_binding_isolates_concurrent_runs(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    barrier = Barrier(2)

    def publish(run_id: str) -> tuple[str, str | None]:
        with port.bind_run(run_id):
            barrier.wait()
            ref = port.write_artifact(
                ArtifactWriteRequest("research-analysis", {"run_id": run_id})
            )
            return ref.ref, port.current_run_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, ("run-a", "run-b")))

    assert set(results) == {
        ("artifact://run-a/research-analysis", "run-a"),
        ("artifact://run-b/research-analysis", "run-b"),
    }
    assert port.current_run_id is None
    assert port.read_artifact("artifact://run-a/research-analysis")["payload"]["run_id"] == "run-a"
    assert port.read_artifact("artifact://run-b/research-analysis")["payload"]["run_id"] == "run-b"


def test_conflicting_metadata_run_id_fails_closed(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)

    with port.bind_run("run-1"), pytest.raises(
        ArtifactRunBindingError,
        match="conflicts",
    ):
        port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"status": "ok"},
                metadata={"run_id": "run-2"},
            )
        )

    assert not (tmp_path / "run-1").exists()


@pytest.mark.parametrize(
    "ref",
    [
        "artifact://run-1/../research-analysis",
        "artifact://run-1/research-analysis?raw=1",
        "artifact://run-1/research-analysis#fragment",
        "file://run-1/research-analysis",
    ],
)
def test_noncanonical_references_are_rejected(tmp_path, ref: str) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)

    with pytest.raises((ArtifactStoreMetadataError, ValueError)):
        port.read_artifact(ref)
    with pytest.raises((ArtifactStoreMetadataError, ValueError)):
        port.verify_artifact_ref(ref, expected_run_id="run-1")


def test_artifact_byte_tamper_is_detected(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"status": "ok"}))

    (tmp_path / "run-1" / "artifacts" / "research-analysis.json").write_bytes(b"tampered")

    with pytest.raises(ArtifactChecksumMismatchError):
        port.read_artifact(ref.ref)
    with pytest.raises(ArtifactChecksumMismatchError):
        port.verify_artifact_ref(ref.ref, expected_run_id="run-1")


def test_manifest_hash_is_required_by_research_adapter(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"status": "ok"}))
    path = tmp_path / "run-1" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.pop("manifest_hash")
    port.manager.write_json("run-1", "manifest.json", manifest)

    with pytest.raises(ArtifactStoreMetadataError, match="hash is missing"):
        port.read_artifact(ref.ref)


def test_manifest_tamper_is_detected_before_artifact_read(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"status": "ok"}))
    path = tmp_path / "run-1" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["artifact_index"][0]["path"] = "artifacts/forged.json"
    port.manager.write_json("run-1", "manifest.json", manifest)

    with pytest.raises(ArtifactStoreMetadataError, match="manifest hash mismatch"):
        port.read_artifact(ref.ref)


def test_non_regular_artifact_is_rejected(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"status": "ok"}))
    path = tmp_path / "run-1" / "artifacts" / "research-analysis.json"
    path.unlink()
    path.mkdir()

    with pytest.raises(ArtifactStoreMetadataError, match="regular file"):
        port.read_artifact(ref.ref)


def test_symlinked_manifest_is_rejected(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"status": "ok"}))
    manifest_path = tmp_path / "run-1" / "manifest.json"
    target = manifest_path.with_name("manifest-target.json")
    target.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    try:
        manifest_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ArtifactStoreMetadataError, match="symlink"):
        port.read_artifact(ref.ref)


def test_symlinked_artifact_write_target_cannot_replace_manifest(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        committed = port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"version": 1})
        )
    manifest_path = tmp_path / "run-1" / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    malicious_target = (
        tmp_path / "run-1" / "artifacts" / "research-reader.json"
    )
    try:
        malicious_target.symlink_to(manifest_path)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with port.bind_run("run-1"), pytest.raises(
        ArtifactStoreMetadataError,
        match="reparse point",
    ):
        port.write_artifact(
            ArtifactWriteRequest("research-reader", {"version": 1})
        )

    assert manifest_path.read_bytes() == manifest_before
    assert port.read_artifact(committed.ref)["payload"] == {"version": 1}


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_junctioned_artifact_directory_cannot_redirect_write(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-junction"):
        committed = port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"version": 1})
        )

    run_dir = tmp_path / "run-junction"
    artifacts_dir = run_dir / "artifacts"
    committed_dir = run_dir / "committed-artifacts"
    victim_dir = run_dir / "victim"
    victim_dir.mkdir()
    victim_path = victim_dir / "research-reader.json"
    victim_before = b'{"owner":"victim"}'
    victim_path.write_bytes(victim_before)
    manifest_path = run_dir / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    artifacts_dir.rename(committed_dir)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(artifacts_dir), str(victim_dir)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        committed_dir.rename(artifacts_dir)
        pytest.skip("junction creation unavailable")

    try:
        with pytest.raises(
            ArtifactStoreMetadataError,
            match="reparse point",
        ):
            port.read_artifact(committed.ref)
        with port.bind_run("run-junction"), pytest.raises(
            ArtifactStoreMetadataError,
            match="reparse point",
        ):
            port.write_artifact(
                ArtifactWriteRequest("research-reader", {"owner": "research"})
            )
        assert victim_path.read_bytes() == victim_before
        assert manifest_path.read_bytes() == manifest_before
    finally:
        artifacts_dir.rmdir()
        committed_dir.rename(artifacts_dir)

    assert port.read_artifact(committed.ref)["payload"] == {"version": 1}


@pytest.mark.parametrize(
    ("content", "error_pattern"),
    [
        (b"not-json", "invalid artifact JSON"),
        (
            b'{"artifact_type":"research-analysis","media_type":"application/json",'
            b'"metadata":{},"payload":{"score":NaN}}',
            "non-finite",
        ),
    ],
)
def test_noncanonical_json_is_rejected_after_integrity_verification(
    tmp_path,
    content: bytes,
    error_pattern: str,
) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        ref = port.write_artifact(ArtifactWriteRequest("research-analysis", {"status": "ok"}))

    checksum = compute_checksum(content)
    port.manager.write_bytes("run-1", "artifacts/research-analysis.json", content)
    manifest = port.manager.read_run_manifest("run-1")
    metadata = manifest["artifact_metadata"]["research-analysis"]
    metadata.update(checksum=checksum, size_bytes=len(content))
    manifest_ref = manifest["artifact_refs"][0]
    manifest_ref.update(checksum=checksum, content_hash=checksum, size_bytes=len(content))
    manifest_index = manifest["artifact_index"][0]
    manifest_index.update(checksum=checksum, size_bytes=len(content))
    manifest["manifest_hash"] = manifest_hash(manifest)
    port.manager.write_json("run-1", "manifest.json", manifest)

    with pytest.raises(ArtifactStoreMetadataError, match=error_pattern):
        port.read_artifact(ref.ref)


def test_manifest_append_failure_does_not_replace_previous_committed_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"):
        committed = port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"version": 1})
        )

    def fail_manifest_append(*args, **kwargs):
        raise OSError("injected manifest replace failure")

    monkeypatch.setattr(port.manager, "append_manifest_artifact", fail_manifest_append)
    with port.bind_run("run-1"), pytest.raises(OSError, match="manifest replace"):
        port.write_artifact(ArtifactWriteRequest("research-reader", {"version": 1}))

    assert port.read_artifact(committed.ref)["payload"] == {"version": 1}
    manifest = port.manager.read_run_manifest("run-1")
    assert "research-reader" not in manifest["artifacts"]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(value: float, tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path)
    with port.bind_run("run-1"), pytest.raises(ArtifactStoreMetadataError, match="non-finite"):
        port.write_artifact(
            ArtifactWriteRequest("research-analysis", {"score": value})
        )


def test_max_write_bytes_is_enforced_before_filesystem_side_effect(tmp_path) -> None:
    port = FilesystemHarnessArtifactPort(tmp_path, max_write_bytes=16)

    with port.bind_run("run-1"), pytest.raises(ValueError, match="max_write_bytes"):
        port.write_artifact(ArtifactWriteRequest("research-analysis", {"content": "large"}))

    assert not (tmp_path / "run-1").exists()


def test_artifact_diagnostics_are_allow_listed_and_exclude_payloads(
    tmp_path,
    caplog,
) -> None:
    run_id = "run-sensitive-identity"
    secrets = (
        "paper content must stay private",
        "prompt=hidden-system-instruction",
        "credential=provider-top-secret",
        str(tmp_path / "private" / "artifact.json"),
    )
    port = FilesystemHarnessArtifactPort(tmp_path)
    caplog.set_level(logging.INFO, logger=RESEARCH_PERSISTENCE_LOGGER)

    with port.bind_run(run_id):
        ref = port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {
                    "paper_content": secrets[0],
                    "prompt": secrets[1],
                    "credential": secrets[2],
                    "path": secrets[3],
                },
            )
        )
    port.read_artifact(ref.ref)

    records = _research_persistence_records(caplog)
    assert [record.research_event_dimensions["operation"] for record in records] == [
        "artifact_write",
        "artifact_read",
    ]
    assert all(
        set(record.research_event_dimensions)
        == {
            "component",
            "operation",
            "outcome",
            "reason",
            "run_identity",
            "paper_identity",
        }
        for record in records
    )
    assert all(
        record.research_event_dimensions["component"] == "artifact_store"
        for record in records
    )
    assert all(
        record.research_event_dimensions["outcome"] == "succeeded"
        for record in records
    )
    assert all(
        record.research_event_dimensions["reason"] == "completed"
        for record in records
    )
    assert all(
        record.research_event_dimensions["paper_identity"]
        == MISSING_IDENTITY_REF
        for record in records
    )
    assert (
        records[0].research_event_dimensions["run_identity"]
        == records[1].research_event_dimensions["run_identity"]
    )
    assert records[0].research_event_dimensions["run_identity"].startswith(
        "redacted:sha256:"
    )
    assert all(record.exc_info is None and record.stack_info is None for record in records)
    for secret in (*secrets, run_id):
        assert secret not in caplog.text
        assert all(secret not in repr(record.research_event_dimensions) for record in records)


def test_artifact_failure_diagnostic_excludes_raw_exception_and_path(
    tmp_path,
    caplog,
    monkeypatch,
) -> None:
    raw_exception = f"credential=secret path={tmp_path / 'private' / 'manifest.json'}"
    port = FilesystemHarnessArtifactPort(tmp_path)
    caplog.set_level(logging.INFO, logger=RESEARCH_PERSISTENCE_LOGGER)

    def fail_write(*_args, **_kwargs):
        raise OSError(raw_exception)

    monkeypatch.setattr(port.manager, "write_bytes", fail_write)
    with port.bind_run("run-failure"), pytest.raises(OSError, match="credential"):
        port.write_artifact(
            ArtifactWriteRequest(
                "research-analysis",
                {"paper_content": "must-not-be-logged"},
            )
        )

    records = _research_persistence_records(caplog)
    assert len(records) == 1
    assert records[0].research_event_dimensions == {
        "component": "artifact_store",
        "operation": "artifact_write",
        "outcome": "failed",
        "reason": "filesystem_unavailable",
        "run_identity": records[0].research_event_dimensions["run_identity"],
        "paper_identity": MISSING_IDENTITY_REF,
    }
    assert records[0].exc_info is None
    assert records[0].stack_info is None
    assert raw_exception not in caplog.text
    assert "must-not-be-logged" not in caplog.text


def _research_persistence_records(caplog):
    return [
        record
        for record in caplog.records
        if getattr(record, "research_event_name", None)
        == RESEARCH_PERSISTENCE_OPERATION_EVENT
    ]
