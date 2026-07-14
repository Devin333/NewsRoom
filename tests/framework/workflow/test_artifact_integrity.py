from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.workflow.inspection.inspector import (
    WorkflowRunInspector,
    read_strict_workflow_artifact_content,
)


def test_strict_artifact_read_verifies_before_decoding_and_redaction(tmp_path: Path) -> None:
    run_dir, manifest = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"token":"hidden","status":"ok"}')},
    )

    record = read_strict_workflow_artifact_content(run_dir, manifest, "output")

    assert record.content == {"token": "[redacted]", "status": "ok"}
    assert record.size_bytes == len(b'{"token":"hidden","status":"ok"}')


def test_strict_artifact_read_rejects_tampered_bytes(tmp_path: Path) -> None:
    run_dir, manifest = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
    )
    (run_dir / "output.json").write_bytes(b'{"status":"tampered"}')

    with pytest.raises(ArtifactChecksumMismatchError, match="output"):
        read_strict_workflow_artifact_content(run_dir, manifest, "output")


@pytest.mark.parametrize("checksum", [None, "pending", "A" * 64, "not-a-checksum"])
def test_strict_artifact_read_rejects_missing_or_invalid_checksum(
    tmp_path: Path,
    checksum: object,
) -> None:
    run_dir, manifest = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
    )
    if checksum is None:
        manifest["artifact_metadata"]["output"].pop("checksum")
    else:
        manifest["artifact_metadata"]["output"]["checksum"] = checksum

    with pytest.raises(ArtifactStoreMetadataError, match="lowercase SHA-256"):
        read_strict_workflow_artifact_content(run_dir, manifest, "output")


def test_strict_artifact_read_rejects_missing_file(tmp_path: Path) -> None:
    run_dir, manifest = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
    )
    (run_dir / "output.json").unlink()

    with pytest.raises(ArtifactNotFoundError, match="output.json"):
        read_strict_workflow_artifact_content(run_dir, manifest, "output")


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
    run_dir, manifest = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
    )
    manifest["artifact_metadata"]["output"][field] = value

    with pytest.raises(ArtifactStoreMetadataError, match=field):
        read_strict_workflow_artifact_content(run_dir, manifest, "output")


def test_strict_artifact_read_uses_step_artifact_metadata_fallback(tmp_path: Path) -> None:
    content = b'{"status":"ok"}'
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "output.json").write_bytes(content)
    artifact_key = "step.collect.result.artifact-1"
    manifest = {
        "run_id": "run-1",
        "artifacts": {artifact_key: "output.json"},
        "step_artifacts": [
            {
                "step_id": "collect",
                "artifact_type": "result",
                "artifact_id": "artifact-1",
                "path": "output.json",
                "checksum": sha256(content).hexdigest(),
            }
        ],
    }

    record = read_strict_workflow_artifact_content(run_dir, manifest, artifact_key)

    assert record.content == {"status": "ok"}


def test_strict_artifact_read_accepts_only_manifest_pending_sentinel(tmp_path: Path) -> None:
    run_dir, manifest = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
        include_manifest=True,
    )

    record = read_strict_workflow_artifact_content(run_dir, manifest, "manifest")

    assert record.content["artifact_metadata"]["manifest"]["checksum"] == "pending"
    assert record.content["run_id"] == "run-1"


def test_strict_replay_preflights_all_artifacts_before_content_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir, _ = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
        include_manifest=True,
    )
    (run_dir / "output.json").write_bytes(b'{"status":"tampered"}')

    def fail_if_content_expands(*args, **kwargs):
        raise AssertionError("artifact content must not expand before strict preflight")

    monkeypatch.setattr(
        "framework.workflow.inspection.inspector.read_workflow_artifact_content",
        fail_if_content_expands,
    )

    with pytest.raises(ArtifactChecksumMismatchError, match="output"):
        WorkflowRunInspector(tmp_path).build_replay_content_bundle(
            run_id="run-1",
            strict_artifact_integrity=True,
        )


def test_replay_content_bundle_keeps_non_strict_default(tmp_path: Path) -> None:
    run_dir, _ = _write_run(
        tmp_path,
        {"output": ("output.json", b'{"status":"ok"}')},
    )
    (run_dir / "output.json").write_bytes(b'{"status":"tampered"}')

    bundle = WorkflowRunInspector(tmp_path).build_replay_content_bundle(run_id="run-1")

    assert bundle.artifact_by_key("output").content == {"status": "tampered"}


def _write_run(
    root: Path,
    files: dict[str, tuple[str, bytes]],
    *,
    include_manifest: bool = False,
) -> tuple[Path, dict[str, object]]:
    run_dir = root / "run-1"
    run_dir.mkdir()
    artifacts = {key: relative_path for key, (relative_path, _) in files.items()}
    metadata = {
        key: {
            "checksum": sha256(content).hexdigest(),
            "content_type": "application/json",
            "size_bytes": len(content),
        }
        for key, (_, content) in files.items()
    }
    for relative_path, content in files.values():
        (run_dir / relative_path).write_bytes(content)
    if include_manifest:
        artifacts["manifest"] = "manifest.json"
        metadata["manifest"] = {
            "checksum": "pending",
            "content_type": "application/json",
            "size_bytes": 0,
        }
    manifest: dict[str, object] = {
        "run_id": "run-1",
        "status": "succeeded",
        "artifacts": artifacts,
        "artifact_metadata": metadata,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")),
        encoding="utf-8",
    )
    return run_dir, manifest
