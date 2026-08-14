from __future__ import annotations

import json

import pytest

from framework.agent.artifacts import ArtifactManager, ArtifactReference


def test_artifact_reference_new_and_legacy_payload_round_trip() -> None:
    ref = ArtifactReference.from_dict(
        {
            "artifact_id": "a1",
            "run_id": "run-1",
            "kind": "metrics",
            "path": "metrics.json",
            "content_type": "application/json",
            "checksum": "abc",
            "size_bytes": 12,
            "metadata": {"source": "test"},
        }
    )
    legacy = ArtifactReference.from_dict({"artifact_id": "a2", "uri": "old.txt"})

    assert ref.uri == "metrics.json"
    assert ref.to_dict()["path"] == "metrics.json"
    assert ref.to_dict()["run_id"] == "run-1"
    assert legacy.uri == "old.txt"


def test_artifact_manager_is_raw_storage_not_manifest_authority(tmp_path) -> None:
    manager = ArtifactManager(tmp_path)

    manager.write_json("run-1", "artifacts/metrics.json", {"count": 2})

    stored = json.loads(
        (tmp_path / "run-1" / "artifacts" / "metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == {"count": 2}
    assert all(
        not hasattr(manager, method_name)
        for method_name in (
            "create_run_manifest",
            "read_run_manifest",
            "update_run_manifest",
            "append_manifest_artifact",
            "finalize_run_manifest",
        )
    )


@pytest.mark.parametrize(
    "name",
    (
        "../outside.json",
        "artifacts/../../outside.json",
        "/absolute.json",
    ),
)
def test_artifact_manager_rejects_unsafe_raw_paths_without_write(
    tmp_path,
    name: str,
) -> None:
    manager = ArtifactManager(tmp_path)

    with pytest.raises((TypeError, ValueError)):
        manager.write_json("run-1", name, {"unsafe": True})

    assert not (tmp_path / "outside.json").exists()
