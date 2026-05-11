import json

import pytest

from interfaces.services.run_inspection_service import RunInspectionService


def test_run_inspection_lists_runs_sorted_by_started_at(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "old-run",
        {"run_id": "old-run", "status": "succeeded", "started_at": "2026-05-10T01:00:00Z"},
    )
    _write_manifest(
        tmp_path,
        "new-run",
        {"run_id": "new-run", "status": "failed", "started_at": "2026-05-11T01:00:00Z"},
    )

    result = RunInspectionService(tmp_path).list_runs()

    payload = result.to_dict()
    assert payload["run_count"] == 2
    assert [run["run_id"] for run in payload["runs"]] == ["new-run", "old-run"]
    assert payload["runs"][0]["status"] == "failed"


def test_run_inspection_get_run_reads_manifest(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {"run_id": "run-1", "status": "succeeded", "workflow_id": "daily"},
    )

    result = RunInspectionService(tmp_path).get_run("run-1")

    assert result.run_id == "run-1"
    assert result.to_dict()["manifest"]["workflow_id"] == "daily"


def test_run_inspection_reads_events_jsonl(tmp_path) -> None:
    _write_run_with_events(
        tmp_path,
        "run-1",
        [
            {"event_type": "workflow_started", "payload": {"profile": "live"}},
            {"event_type": "workflow_succeeded", "payload": {"status": "ok"}},
        ],
    )

    result = RunInspectionService(tmp_path).get_run_events("run-1")

    payload = result.to_dict()
    assert payload["event_count"] == 2
    assert payload["events"][0]["event_type"] == "workflow_started"
    assert payload["events"][1]["payload"] == {"status": "ok"}


def test_run_inspection_limits_events(tmp_path) -> None:
    _write_run_with_events(
        tmp_path,
        "run-1",
        [
            {"event_type": "event-1", "payload": {}},
            {"event_type": "event-2", "payload": {}},
        ],
    )

    result = RunInspectionService(tmp_path).get_run_events("run-1", limit=1)

    assert result.to_dict()["event_count"] == 1
    assert result.to_dict()["events"][0]["event_type"] == "event-1"


def test_run_inspection_redacts_sensitive_event_keys(tmp_path) -> None:
    _write_run_with_events(
        tmp_path,
        "run-1",
        [
            {
                "event_type": "tool_called",
                "payload": {"api_key": "hidden-value", "nested": {"authorization": "bearer"}},
            }
        ],
    )

    result = RunInspectionService(tmp_path).get_run_events("run-1")

    payload = result.to_dict()
    assert payload["events"][0]["payload"]["api_key"] == "[redacted]"
    assert payload["events"][0]["payload"]["nested"]["authorization"] == "[redacted]"
    assert "hidden-value" not in json.dumps(payload)


def test_run_inspection_replay_reads_real_artifacts_and_redacts(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    manifest = {
        "run_id": "run-1",
        "status": "succeeded",
        "artifacts": {
            "events": "events.jsonl",
            "report_json": "report.json",
            "report_markdown": "report.md",
            "missing": "missing.json",
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "workflow_started", "payload": {"token": "hidden"}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Report", "api_key": "hidden-key"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")

    result = RunInspectionService(tmp_path).replay_run("run-1")

    payload = result.to_dict()
    artifacts = {artifact["artifact_key"]: artifact for artifact in payload["artifacts"]}
    assert payload["event_count"] == 1
    assert payload["events"][0]["payload"]["token"] == "[redacted]"
    assert artifacts["report_json"]["content"]["api_key"] == "[redacted]"
    assert artifacts["report_markdown"]["content"] == "# Report\n"
    assert artifacts["missing"]["read_error"] == "artifact file not found: missing.json"
    assert "hidden-key" not in json.dumps(payload)


def test_run_inspection_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(ValueError):
        RunInspectionService(tmp_path).get_run("../secret")


def test_run_inspection_rejects_invalid_event_limit(tmp_path) -> None:
    with pytest.raises(ValueError):
        RunInspectionService(tmp_path).get_run_events("run-1", limit=0)


def _write_manifest(root, run_id, payload) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_run_with_events(root, run_id, events) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    manifest = {
        "run_id": run_id,
        "status": "succeeded",
        "artifacts": {"events": "events.jsonl"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
