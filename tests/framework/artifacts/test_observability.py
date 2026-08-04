from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from framework.agent.artifacts import (
    Artifact,
    ArtifactChecksumMismatchError,
    ArtifactIntegrityInspector,
    ArtifactManifest,
    ArtifactManager,
    ArtifactPathError,
    ArtifactReference,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
    LocalArtifactStore,
    compute_checksum,
    resolve_artifact_descendant,
)
from framework.agent.artifacts.observability import (
    ARTIFACT_CHECKSUM_MISMATCH_EVENT,
    ARTIFACT_CHECKSUM_MISSING_EVENT,
    ARTIFACT_INTEGRITY_INSPECTION_EVENT,
    ARTIFACT_METADATA_CORRUPT_EVENT,
    ARTIFACT_OBSERVABILITY_LOGGER,
    ARTIFACT_PATH_REJECTED_EVENT,
    ARTIFACT_RESERVED_METADATA_REJECTED_EVENT,
    SAFE_FALLBACK_LABEL,
    emit_artifact_checksum_mismatch,
    emit_artifact_checksum_missing,
    emit_artifact_integrity_inspection,
    emit_artifact_metadata_corrupt,
    emit_artifact_path_rejected,
    emit_artifact_reserved_metadata_rejected,
)
from framework.agent.artifacts.stores import verify_sha256_checksum
from framework.specs import StepSpec, StepStatus, StepType
from framework.workflow.buffer import DataBuffer
from framework.workflow.runners.artifact import ArtifactStepRunner


Emitter = Callable[..., None]


@pytest.mark.parametrize(
    ("emitter", "kwargs", "event_name", "level", "dimensions"),
    [
        (
            emit_artifact_path_rejected,
            {"field": "run_id", "operation": "validate_segment"},
            ARTIFACT_PATH_REJECTED_EVENT,
            logging.WARNING,
            {"field": "run_id", "operation": "validate_segment"},
        ),
        (
            emit_artifact_reserved_metadata_rejected,
            {"key": "run_id", "publisher": "local"},
            ARTIFACT_RESERVED_METADATA_REJECTED_EVENT,
            logging.WARNING,
            {"key": "run_id", "publisher": "local"},
        ),
        (
            emit_artifact_checksum_mismatch,
            {"store": "local", "operation": "read"},
            ARTIFACT_CHECKSUM_MISMATCH_EVENT,
            logging.WARNING,
            {"store": "local", "operation": "read"},
        ),
        (
            emit_artifact_metadata_corrupt,
            {"store": "strict_workflow"},
            ARTIFACT_METADATA_CORRUPT_EVENT,
            logging.WARNING,
            {"store": "strict_workflow"},
        ),
        (
            emit_artifact_checksum_missing,
            {"store": "artifact_store"},
            ARTIFACT_CHECKSUM_MISSING_EVENT,
            logging.WARNING,
            {"store": "artifact_store"},
        ),
        (
            emit_artifact_integrity_inspection,
            {"result": "valid"},
            ARTIFACT_INTEGRITY_INSPECTION_EVENT,
            logging.INFO,
            {"result": "valid"},
        ),
        (
            emit_artifact_integrity_inspection,
            {"result": "invalid"},
            ARTIFACT_INTEGRITY_INSPECTION_EVENT,
            logging.WARNING,
            {"result": "invalid"},
        ),
    ],
)
def test_artifact_events_have_fixed_names_levels_and_dimensions(
    caplog,
    emitter: Emitter,
    kwargs: dict[str, str],
    event_name: str,
    level: int,
    dimensions: dict[str, str],
) -> None:
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    emitter(**kwargs)

    records = _artifact_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.levelno == level
    assert record.getMessage() == event_name
    assert record.artifact_event_name == event_name
    assert record.artifact_event_dimensions == dimensions
    assert record.exc_info is None
    assert record.stack_info is None


def test_unknown_dimension_values_use_safe_fallback_without_leaking(caplog) -> None:
    secret = "C:/private/api_token=super-secret"
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    emit_artifact_path_rejected(field=secret, operation=secret)
    emit_artifact_reserved_metadata_rejected(key=secret, publisher=secret)
    emit_artifact_checksum_mismatch(store=secret, operation=secret)
    emit_artifact_metadata_corrupt(store=secret)
    emit_artifact_checksum_missing(store=secret)
    emit_artifact_integrity_inspection(result=secret)

    records = _artifact_records(caplog)
    assert len(records) == 6
    for record in records:
        assert set(record.artifact_event_dimensions.values()) == {
            SAFE_FALLBACK_LABEL
        }
        assert secret not in record.getMessage()
        assert secret not in repr(record.artifact_event_dimensions)
    assert secret not in caplog.text


def test_event_does_not_capture_ambient_exception_or_traceback(caplog) -> None:
    secret = "password=not-for-logs"
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    try:
        raise RuntimeError(secret)
    except RuntimeError:
        emit_artifact_metadata_corrupt(store="local")

    record = _artifact_records(caplog)[0]
    assert record.exc_info is None
    assert record.stack_info is None
    assert secret not in caplog.text


def test_path_boundary_emits_once_for_nested_rejection(
    tmp_path: Path,
    caplog,
) -> None:
    secret_path = "../api_token=super-secret"
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactPathError):
        resolve_artifact_descendant(
            tmp_path,
            secret_path,
            field="artifact_path",
        )

    records = _artifact_records(caplog)
    assert len(records) == 1
    assert records[0].artifact_event_name == ARTIFACT_PATH_REJECTED_EVENT
    assert records[0].artifact_event_dimensions == {
        "field": "artifact_path",
        "operation": "resolve_descendant",
    }
    assert secret_path not in caplog.text


def test_shared_checksum_verification_emits_once_without_content(caplog) -> None:
    secret_content = b"api_token=super-secret"
    secret_id = "password=not-for-logs"
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactChecksumMismatchError):
        verify_sha256_checksum(
            secret_content,
            compute_checksum(b"expected"),
            artifact_id=secret_id,
            store="local",
            operation="read",
        )

    records = _artifact_records(caplog)
    assert len(records) == 1
    assert records[0].artifact_event_name == ARTIFACT_CHECKSUM_MISMATCH_EVENT
    assert records[0].artifact_event_dimensions == {
        "store": "local",
        "operation": "read",
    }
    assert secret_content.decode() not in caplog.text
    assert secret_id not in caplog.text


@dataclass
class _ClassifyingStore:
    artifacts: dict[str, Artifact | Exception | None]

    def get(self, artifact_id: str) -> Artifact | None:
        result = self.artifacts[artifact_id]
        if isinstance(result, Exception):
            raise result
        return result


def test_integrity_inspection_emits_classifications_and_one_completion(caplog) -> None:
    secret = "credential=not-for-logs"
    legacy = Artifact(
        "legacy",
        "legacy.txt",
        "text/plain",
        secret.encode(),
        metadata={"_artifact_integrity": "checksum_missing"},
    )
    wrong = Artifact("wrong", "wrong.txt", "text/plain", b"actual")
    store = _ClassifyingStore(
        {
            "metadata": ArtifactStoreMetadataError(secret),
            "legacy": legacy,
            "wrong": wrong,
        }
    )
    manifest = ArtifactManifest(
        run_id="run-1",
        artifacts=[
            ArtifactReference(
                "metadata",
                "objects/metadata",
                checksum=compute_checksum(b"metadata"),
            ),
            ArtifactReference(
                "legacy",
                "objects/legacy",
                checksum=compute_checksum(secret.encode()),
            ),
            ArtifactReference(
                "wrong",
                "objects/wrong",
                checksum=compute_checksum(b"expected"),
            ),
        ],
    )
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    report = ArtifactIntegrityInspector(store).inspect(manifest)

    assert report.valid is False
    assert [record.artifact_event_name for record in _artifact_records(caplog)] == [
        ARTIFACT_METADATA_CORRUPT_EVENT,
        ARTIFACT_CHECKSUM_MISSING_EVENT,
        ARTIFACT_CHECKSUM_MISMATCH_EVENT,
        ARTIFACT_INTEGRITY_INSPECTION_EVENT,
    ]
    assert _artifact_records(caplog)[-1].artifact_event_dimensions == {
        "result": "invalid"
    }
    assert secret not in caplog.text


def test_local_store_inspection_does_not_double_count_propagated_outcomes(
    tmp_path: Path,
    caplog,
) -> None:
    secret = "api_token=super-secret"
    store = LocalArtifactStore(tmp_path)
    metadata_ref = store.put(
        Artifact("metadata", "metadata.txt", "text/plain", b"metadata")
    )
    missing_ref = store.put(
        Artifact("missing", "missing.txt", "text/plain", b"legacy")
    )
    mismatch_ref = store.put(
        Artifact("mismatch", "mismatch.txt", "text/plain", b"trusted")
    )

    metadata_path = tmp_path / ".metadata" / "metadata.json"
    metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_payload["uri"] = f"objects/{secret}"
    metadata_path.write_text(json.dumps(metadata_payload), encoding="utf-8")

    missing_path = tmp_path / ".metadata" / "missing.json"
    missing_payload = json.loads(missing_path.read_text(encoding="utf-8"))
    missing_payload.pop("checksum")
    missing_path.write_text(json.dumps(missing_payload), encoding="utf-8")

    store.path_for("mismatch").write_bytes(secret.encode())
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    report = ArtifactIntegrityInspector(store).inspect(
        ArtifactManifest(
            run_id="run-1",
            artifacts=[metadata_ref, missing_ref, mismatch_ref],
        )
    )

    assert report.valid is False
    assert [issue.reason for issue in report.issues] == [
        "metadata_corrupt",
        "checksum_missing",
        "checksum_mismatch",
    ]
    records = _artifact_records(caplog)
    assert [record.artifact_event_name for record in records] == [
        ARTIFACT_METADATA_CORRUPT_EVENT,
        ARTIFACT_CHECKSUM_MISSING_EVENT,
        ARTIFACT_CHECKSUM_MISMATCH_EVENT,
        ARTIFACT_INTEGRITY_INSPECTION_EVENT,
    ]
    assert [record.artifact_event_dimensions for record in records] == [
        {"store": "local"},
        {"store": "local"},
        {"store": "local", "operation": "read"},
        {"result": "invalid"},
    ]
    assert secret not in caplog.text


def test_integrity_inspection_logs_configuration_failure_once(caplog) -> None:
    manifest = ArtifactManifest(
        run_id="run-1",
        artifacts=[ArtifactReference("a1", "objects/a1")],
    )
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(ArtifactStoreRequiredError):
        ArtifactIntegrityInspector().inspect(manifest)

    records = _artifact_records(caplog)
    assert len(records) == 1
    assert records[0].artifact_event_name == ARTIFACT_INTEGRITY_INSPECTION_EVENT
    assert records[0].artifact_event_dimensions == {"result": "store_unavailable"}


def test_integrity_inspection_logs_unknown_failure_without_exception_text(caplog) -> None:
    secret = "permission denied for C:/private/api-token"
    store = _ClassifyingStore({"a1": PermissionError(secret)})
    manifest = ArtifactManifest(
        run_id="run-1",
        artifacts=[ArtifactReference("a1", "objects/a1")],
    )
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    with pytest.raises(PermissionError, match="permission denied"):
        ArtifactIntegrityInspector(store).inspect(manifest)

    records = _artifact_records(caplog)
    assert len(records) == 1
    assert records[0].artifact_event_dimensions == {"result": "error"}
    assert records[0].exc_info is None
    assert secret not in caplog.text


def test_artifact_step_reserved_metadata_emits_one_safe_event(
    tmp_path: Path,
    caplog,
) -> None:
    secret = "api_token=super-secret"
    step = StepSpec(
        step_id="artifact-step",
        step_type=StepType.ARTIFACT,
        write_keys=["artifact_ref"],
        metadata={
            "content": {"secret": secret},
            "artifact_metadata": {
                "run_id": secret,
                "publisher_id": secret,
            },
        },
    )
    buffer = DataBuffer().scope(
        step.read_keys,
        step.write_keys,
        step_id=step.step_id,
    )
    runner = ArtifactStepRunner(ArtifactManager(tmp_path), run_id="run-1")
    caplog.set_level(logging.INFO, logger=ARTIFACT_OBSERVABILITY_LOGGER)

    outcome = runner.run(step, buffer)

    assert outcome.status == StepStatus.FAILED
    records = _artifact_records(caplog)
    assert len(records) == 1
    assert records[0].artifact_event_name == (
        ARTIFACT_RESERVED_METADATA_REJECTED_EVENT
    )
    assert records[0].artifact_event_dimensions == {
        "key": "publisher_id",
        "publisher": "artifact_step",
    }
    assert secret not in caplog.text


def _artifact_records(caplog) -> list[Any]:
    return [
        record
        for record in caplog.records
        if record.name == ARTIFACT_OBSERVABILITY_LOGGER
    ]
