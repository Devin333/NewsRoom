from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

from framework.agent.artifacts import ArtifactPathError
from framework.agent.artifacts.models import ArtifactRef
from framework.workflow.checkpoint.envelope import WorkflowCheckpointEnvelope
from framework.workflow.checkpoint.model import WorkflowCheckpoint as RuntimeCheckpoint
from framework.workflow.checkpoint.recovery import inspect_checkpoint_artifacts
from framework.workflow.checkpoint.store import LocalJsonCheckpointStore as RuntimeCheckpointStore
from framework.workflow.inspection.inspector import (
    WorkflowRunInspectionError,
    WorkflowRunInspector,
    resolve_artifact_path,
    resolve_run_dir,
)
from framework.workflow.operations.service import LocalWorkflowRunOperationService
from framework.workflow.runtime.artifact_publishers import _populate_artifact_metadata
from framework.workflow.runtime.execution_context import build_execution_context
from framework.workflow.runtime.executor import _load_checkpoint_manifest
from framework.workflow.runtime.manifest import (
    JsonManifestStore,
    RunManifestError,
    register_manifest_artifact,
)
from framework.workflow.runtime.runner import (
    LocalJsonWorkflowArtifactIndexStore,
)
from infrastructure.storage.checkpoint.local_json import (
    LocalJsonCheckpointStore as InfrastructureCheckpointStore,
)
from infrastructure.storage.checkpoint.models import (
    WorkflowCheckpoint as InfrastructureCheckpoint,
)


class _RecordingArtifactManager:
    def __init__(self) -> None:
        self.started_run_ids: list[str] = []

    def start_run(self, run_id: str) -> Path:
        self.started_run_ids.append(run_id)
        raise AssertionError("start_run must not be called for an unsafe explicit run id")


class _RecordingEventRuntime:
    def __init__(self) -> None:
        self.published: list[Any] = []

    def publish(self, event: Any, *, unit_of_work: Any = None) -> Any:
        self.published.append(event)
        raise AssertionError("publish must not be called for an unsafe explicit run id")


class _FailIfReadEventReader:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"event reader must not be used for an unsafe run id: {name}")


@pytest.mark.parametrize(
    "run_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "/absolute",
        "nested/run",
        "nested\\run",
        "C:\\absolute",
        "C:drive-relative",
        "\\\\server\\share",
        "\\\\?\\C:\\device",
        "run:stream",
        "CON",
        "con.txt",
        "NUL",
        "LPT1",
    ],
)
def test_execution_context_rejects_unsafe_explicit_run_id_before_manager(
    run_id: str,
) -> None:
    manager = _RecordingArtifactManager()
    runtime = _RecordingEventRuntime()

    with pytest.raises(ArtifactPathError):
        build_execution_context(
            workflow=cast(Any, object()),
            request={},
            profile="default",
            artifact_manager=cast(Any, manager),
            step_runner_registry=cast(Any, object()),
            event_runtime=cast(Any, runtime),
            event_reader=cast(Any, _FailIfReadEventReader()),
            started_monotonic=0.0,
            run_id=run_id,
        )

    assert manager.started_run_ids == []
    assert runtime.published == []


def test_manifest_store_rejects_traversal_before_external_manifest_read(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    escaped_manifest = tmp_path / "escape" / "manifest.json"
    escaped_manifest.parent.mkdir()
    escaped_manifest.write_text('{"run_id":"escape"}\n', encoding="utf-8")

    with pytest.raises(ArtifactPathError):
        JsonManifestStore(root).exists("../escape")


@pytest.mark.parametrize("relative_path", ["../outside.json", "nested:stream", "CON/file.json"])
def test_manifest_registration_delegates_unsafe_paths_to_shared_boundary(
    relative_path: str,
) -> None:
    with pytest.raises(RunManifestError, match="manifest artifact path"):
        register_manifest_artifact({}, "unsafe", relative_path)


def test_checkpoint_manifest_loader_rejects_traversal_before_read(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    escaped_manifest = tmp_path / "escape" / "manifest.json"
    escaped_manifest.parent.mkdir()
    escaped_manifest.write_text('{"secret":"outside"}\n', encoding="utf-8")

    with pytest.raises(ArtifactPathError):
        _load_checkpoint_manifest(root, "../escape")


def test_manifest_metadata_population_rejects_unsafe_path_before_read(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "artifacts" / "run-1"
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret":true}\n', encoding="utf-8")
    manifest = {"artifacts": {"outside": "../../outside.json"}}

    with pytest.raises(ArtifactPathError):
        _populate_artifact_metadata(manifest, run_dir)


def test_manifest_metadata_population_keeps_self_checksum_pending(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts" / "run-1"
    run_dir.mkdir(parents=True)
    manifest_bytes = b'{"run_id":"run-1"}'
    output_bytes = b'{"status":"ok"}'
    (run_dir / "manifest.json").write_bytes(manifest_bytes)
    (run_dir / "output.json").write_bytes(output_bytes)
    manifest = {
        "artifacts": {
            "manifest": "manifest.json",
            "output": "output.json",
        }
    }

    _populate_artifact_metadata(manifest, run_dir)

    metadata = manifest["artifact_metadata"]
    assert metadata["manifest"] == {
        "checksum": "pending",
        "content_type": "application/json",
        "size_bytes": len(manifest_bytes),
    }
    assert metadata["output"]["checksum"] == sha256(output_bytes).hexdigest()


@pytest.mark.parametrize(
    ("store_type", "checkpoint_type"),
    [
        (RuntimeCheckpointStore, RuntimeCheckpoint),
        (InfrastructureCheckpointStore, InfrastructureCheckpoint),
    ],
)
def test_checkpoint_stores_reject_unsafe_checkpoint_id_without_files(
    tmp_path: Path,
    store_type: type[Any],
    checkpoint_type: type[Any],
) -> None:
    root = tmp_path / store_type.__module__.replace(".", "_")
    checkpoint = checkpoint_type(
        checkpoint_id="checkpoint:stream",
        run_id="run-1",
        workflow_id="workflow-1",
        workflow_version="1.0.0",
        current_step_ids=["step-1"],
        data_buffer_snapshot={"request": {}},
    )

    with pytest.raises(ArtifactPathError, match="invalid checkpoint_id"):
        store_type(root).save_checkpoint(checkpoint)

    assert not root.exists()


@pytest.mark.parametrize("store_type", [RuntimeCheckpointStore, InfrastructureCheckpointStore])
def test_checkpoint_stores_reject_unsafe_run_id_before_directory_scan(
    tmp_path: Path,
    store_type: type[Any],
) -> None:
    with pytest.raises(ArtifactPathError, match="invalid run_id"):
        store_type(tmp_path / "checkpoints").list_checkpoints("run:stream")


def test_checkpoint_recovery_rejects_unsafe_run_id_before_external_lookup(
    tmp_path: Path,
) -> None:
    checkpoint = WorkflowCheckpointEnvelope(
        checkpoint_id="checkpoint-1",
        schema_version="workflow-checkpoint/v1",
        run_id="../escape",
        workflow_id="workflow-1",
        workflow_version="1.0.0",
        current_step_ids=["step-1"],
        data_buffer_snapshot={"request": {}},
        step_results={},
        path=[],
        manifest_hash=None,
        checksum="pending",
        created_at="2026-07-14T00:00:00Z",
    )

    with pytest.raises(ArtifactPathError):
        inspect_checkpoint_artifacts(
            checkpoint=checkpoint,
            manifest=None,
            artifact_root=tmp_path / "artifacts",
            strict=False,
        )


def test_checkpoint_recovery_rejects_unsafe_manifest_artifact_path(
    tmp_path: Path,
) -> None:
    checkpoint = WorkflowCheckpointEnvelope(
        checkpoint_id="checkpoint-1",
        schema_version="workflow-checkpoint/v1",
        run_id="run-1",
        workflow_id="workflow-1",
        workflow_version="1.0.0",
        current_step_ids=["step-1"],
        data_buffer_snapshot={"request": {}},
        step_results={},
        path=[],
        manifest_hash=None,
        checksum="pending",
        created_at="2026-07-14T00:00:00Z",
    )

    with pytest.raises(ArtifactPathError):
        inspect_checkpoint_artifacts(
            checkpoint=checkpoint,
            manifest={"artifacts": {"outside": "../outside.json"}},
            artifact_root=tmp_path / "artifacts",
            strict=False,
        )


def test_operation_service_rejects_traversal_without_external_side_effect(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    escaped_run = tmp_path / "escape"
    escaped_run.mkdir()
    (escaped_run / "manifest.json").write_text(
        json.dumps({"run_id": "../escape", "status": "running"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactPathError):
        LocalWorkflowRunOperationService(artifact_root=artifact_root).cancel_run(
            "../escape",
            "stop",
        )

    assert not (escaped_run / "events.jsonl").exists()
    assert not (escaped_run / "cancel.json").exists()


@pytest.mark.parametrize("run_id", ["nested/run", "run:stream", "CON"])
def test_workflow_inspection_run_resolution_uses_shared_segment_boundary(
    tmp_path: Path,
    run_id: str,
) -> None:
    with pytest.raises(WorkflowRunInspectionError, match="artifact root"):
        resolve_run_dir(tmp_path, run_id)


@pytest.mark.parametrize("relative_path", ["../outside.json", "nested:stream", "CON/file.json"])
def test_workflow_inspection_artifact_resolution_uses_shared_relative_boundary(
    tmp_path: Path,
    relative_path: str,
) -> None:
    with pytest.raises(WorkflowRunInspectionError, match="run directory"):
        resolve_artifact_path(tmp_path, relative_path)


def test_workflow_artifact_list_fails_closed_for_unsafe_manifest_path(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    with pytest.raises(WorkflowRunInspectionError):
        WorkflowRunInspector().list_artifacts(
            run_dir,
            manifest={"artifacts": {"outside": "../outside.json"}},
        )


def test_workflow_inspector_rejects_explicit_run_dir_outside_configured_root(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    outside_run = tmp_path / "outside-run"
    outside_run.mkdir()
    (outside_run / "manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(WorkflowRunInspectionError, match="artifact root"):
        WorkflowRunInspector(artifact_root).inspect_run(run_dir=outside_run)


def test_workflow_catalog_does_not_follow_run_symlink_outside_root(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    outside_run = tmp_path / "outside-run"
    outside_run.mkdir()
    (outside_run / "manifest.json").write_text("{}\n", encoding="utf-8")
    linked_run = artifact_root / "linked-run"
    try:
        linked_run.symlink_to(outside_run, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    catalog = WorkflowRunInspector(artifact_root).list_runs(include_invalid=True)

    assert catalog.runs == []
    assert str(linked_run) in catalog.invalid_run_dirs


def test_workflow_artifact_index_rejects_unsafe_path_without_record(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "index"
    ref = ArtifactRef(
        artifact_id="artifact-1",
        run_id="run-1",
        artifact_type="result",
        path="payload:stream",
        content_type="application/json",
    )

    with pytest.raises(ArtifactPathError, match="invalid artifact path"):
        LocalJsonWorkflowArtifactIndexStore(index_root).index_artifact(ref)

    assert not index_root.exists()


def test_workflow_artifact_index_supports_hashed_logical_artifact_id(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "index"
    ref = ArtifactRef(
        artifact_id="custom:logical-id",
        run_id="run-1",
        artifact_type="result",
        path="artifacts/result.json",
        content_type="application/json",
    )

    record_path = LocalJsonWorkflowArtifactIndexStore(index_root).index_artifact(ref)

    assert record_path.name.startswith("a-")
    assert ":" not in record_path.name
    assert json.loads(record_path.read_text(encoding="utf-8"))["artifact_id"] == ref.artifact_id


@pytest.mark.parametrize("artifact_id", [None, "", " \t"])
def test_workflow_artifact_index_rejects_blank_logical_artifact_id_without_record(
    tmp_path: Path,
    artifact_id: object,
) -> None:
    index_root = tmp_path / "index"
    ref = ArtifactRef(
        artifact_id=cast(Any, artifact_id),
        run_id="run-1",
        artifact_type="result",
        path="artifacts/result.json",
        content_type="application/json",
    )

    with pytest.raises(ValueError, match="artifact_id is required"):
        LocalJsonWorkflowArtifactIndexStore(index_root).index_artifact(ref)

    assert not index_root.exists()
