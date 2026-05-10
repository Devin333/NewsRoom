import json

import pytest

from interfaces.services.artifact_service import ArtifactInspectionService


def test_artifact_service_lists_manifest_artifacts(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json", "report_markdown": "report.md"},
        files={"output.json": {"status": "ok"}, "report.md": "# Report"},
    )

    result = ArtifactInspectionService(tmp_path).list_artifacts("run-1")

    payload = result.to_dict()
    assert payload["artifact_count"] == 2
    assert payload["artifacts"][0]["artifact_key"] == "output"
    assert payload["artifacts"][0]["content_type"] == "application/json"
    assert payload["artifacts"][1]["artifact_key"] == "report_markdown"
    assert payload["artifacts"][1]["content_type"] == "text/markdown"


def test_artifact_service_reads_json_artifact(tmp_path) -> None:
    _write_run(
        tmp_path,
        "run-1",
        artifacts={"output": "output.json"},
        files={"output.json": {"status": "ok"}},
    )

    result = ArtifactInspectionService(tmp_path).get_artifact("run-1", "output")

    assert result.to_dict()["content"] == {"status": "ok"}
    assert result.to_dict()["size_bytes"] is not None


def test_artifact_service_rejects_unknown_artifact_key(tmp_path) -> None:
    _write_run(tmp_path, "run-1", artifacts={}, files={})

    with pytest.raises(FileNotFoundError):
        ArtifactInspectionService(tmp_path).get_artifact("run-1", "missing")


def _write_run(root, run_id, *, artifacts, files) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    manifest = {"run_id": run_id, "status": "succeeded", "artifacts": artifacts}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path, content in files.items():
        path = run_dir / relative_path
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content), encoding="utf-8")
