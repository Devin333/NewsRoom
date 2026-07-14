import json
from hashlib import sha256

import pytest

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.artifacts.paths import ArtifactPathError
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


def test_run_inspection_list_skips_unreadable_manifest(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {"run_id": "run-1", "status": "succeeded", "started_at": "2026-05-10T01:00:00Z"},
    )
    bad_run_dir = tmp_path / "bad-run"
    bad_run_dir.mkdir()
    (bad_run_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    result = RunInspectionService(tmp_path).list_runs()

    assert [run.run_id for run in result.runs] == ["run-1"]


def test_run_inspection_get_run_reads_manifest(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {
            "run_id": "run-1",
            "status": "succeeded",
            "workflow_id": "daily",
            "workflow_version": "1.0",
            "profile": "test",
            "started_at": "2026-05-11T00:00:00Z",
            "path": [],
            "steps": {},
            "output": {
                "quality_result": {
                    "decision": "blocked",
                    "route": "human_review",
                    "metadata": {"citation_failure_categories": []},
                },
                "citation_check_result": {"unsupported_claims": [], "rejected_claim_usage": []},
                "support_matrix": {"unsupported_sections": []},
                "evidence_bundle": {"bundle_id": "bundle-1"},
                "candidate_claims": [{"claim_id": "claim-1", "source_evidence_ids": ["ev-1"]}],
                "verified_findings": {
                    "accepted_claims": [{"claim_id": "claim-1"}],
                    "rejected_claims": [],
                    "uncertain_claims": [],
                },
            },
            "artifacts": {
                "request": "request.json",
                "workflow_spec": "workflow_spec.json",
                "workflow_version": "workflow_version.json",
                "events": "events.jsonl",
                "manifest": "manifest.json",
                "data_buffer_snapshot": "data_buffer_snapshot.json",
                "data_buffer_initial": "data_buffer.initial.json",
                "data_buffer_final": "data_buffer.final.json",
                "data_buffer_diff": "data_buffer.diff.json",
                "step_results": "step_results.json",
                "metrics": "metrics.json",
                "redaction_report": "redaction_report.json",
            },
        },
    )

    result = RunInspectionService(tmp_path).get_run("run-1")

    assert result.run_id == "run-1"
    assert result.to_dict()["manifest"]["workflow_id"] == "daily"
    assert result.to_dict()["manifest"]["schema_version"] == "newsroom.workflow_run_manifest.v1"
    assert result.to_dict()["output_preview"]["partial_artifacts"]["required_artifact_keys"] == [
        "request",
        "events",
        "step_results",
        "manifest",
    ]
    assert result.to_dict()["output_preview"]["quality_trace"]["quality_lineage"]["claim_count"] == 1


def test_run_inspection_projects_namespaced_daily_output_for_quality_preview(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {
            "run_id": "run-1",
            "status": "succeeded",
            "workflow_id": "daily-intelligence-agentic",
            "workflow_version": "1.0",
            "profile": "test",
            "started_at": "2026-05-11T00:00:00Z",
            "path": [],
            "steps": {},
            "output": {
                "quality_result": {"decision": "legacy", "route": "legacy"},
                "quality.result": {
                    "decision": "blocked",
                    "route": "human_review",
                    "metadata": {"citation_failure_categories": ["unsupported_claims"]},
                },
                "quality.citation_check_result": {
                    "unsupported_claims": ["claim-1"],
                    "rejected_claim_usage": [],
                },
                "quality.support_matrix": {"unsupported_sections": ["Summary"]},
                "report.final": {"report_id": "run-1:final", "title": "Daily"},
                "evidence.candidate_claims": [{"claim_id": "claim-1"}],
                "evidence.verified_findings": {
                    "accepted_claims": [{"claim_id": "claim-1"}],
                    "rejected_claims": [],
                    "uncertain_claims": [],
                },
                "sources.ranked_items": [{"title": "ranked"}],
                "agent.feedback.summary": {"event_count": 1},
            },
        },
    )

    result = RunInspectionService(tmp_path).get_run("run-1")

    quality_trace = result.to_dict()["output_preview"]["quality_trace"]
    assert quality_trace["decision"] == "blocked"
    assert quality_trace["route"] == "human_review"
    assert quality_trace["citation_failure_categories"] == ["unsupported_claims"]
    assert quality_trace["unsupported_claims"] == ["claim-1"]
    assert quality_trace["unsupported_sections"] == ["Summary"]
    assert quality_trace["quality_lineage"]["claim_count"] == 1
    assert quality_trace["quality_lineage"]["report_id"] == "run-1:final"


def test_run_inspection_projects_canonical_quality_output_when_namespaced_absent(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {
            "run_id": "run-1",
            "status": "succeeded",
            "workflow_id": "daily-intelligence-agentic",
            "workflow_version": "1.0",
            "profile": "test",
            "started_at": "2026-05-11T00:00:00Z",
            "path": [],
            "steps": {},
            "output": {
                "quality_result": {"decision": "legacy", "route": "legacy"},
                "citation_check_result": {"unsupported_claims": ["claim-1"]},
                "support_matrix": {"unsupported_sections": ["Summary"]},
                "final_report": {"report_id": "legacy-final", "title": "Daily"},
                "candidate_claims": [{"claim_id": "claim-1"}],
                "verified_findings": {
                    "accepted_claims": [{"claim_id": "claim-1"}],
                    "rejected_claims": [],
                    "uncertain_claims": [],
                },
            },
        },
    )

    result = RunInspectionService(tmp_path).get_run("run-1")

    quality_trace = result.to_dict()["output_preview"]["quality_trace"]
    assert quality_trace["decision"] == "legacy"
    assert quality_trace["route"] == "legacy"
    assert quality_trace["unsupported_claims"] == ["claim-1"]
    assert quality_trace["unsupported_sections"] == ["Summary"]
    assert quality_trace["quality_lineage"]["report_id"] == "legacy-final"
    assert quality_trace["quality_lineage"]["claim_count"] == 1


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


def test_run_inspection_missing_events_file_raises_not_found(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {"run_id": "run-1", "status": "succeeded", "artifacts": {"events": "events.jsonl"}},
    )

    with pytest.raises(FileNotFoundError):
        RunInspectionService(tmp_path).get_run_events("run-1")


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
    _write_replay_run(tmp_path)

    result = RunInspectionService(tmp_path).replay_run("run-1")

    payload = result.to_dict()
    artifacts = {artifact["artifact_key"]: artifact for artifact in payload["artifacts"]}
    assert payload["event_count"] == 1
    assert payload["step_result_count"] == 1
    assert payload["step_results"]["write"]["status"] == "succeeded"
    assert payload["integrity"]["valid"] is False
    assert payload["events"][0]["payload"]["token"] == "[redacted]"
    assert artifacts["report_json"]["content"]["api_key"] == "[redacted]"
    assert artifacts["report_markdown"]["content"] == "# Report\n"
    assert artifacts["manifest"]["content"]["artifact_metadata"]["manifest"]["checksum"] == "pending"
    assert "hidden-key" not in json.dumps(payload)


def test_run_inspection_replay_rejects_tampered_artifact(tmp_path) -> None:
    run_dir = _write_replay_run(tmp_path)
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Tampered", "api_key": "hidden-key"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactChecksumMismatchError, match="report_json"):
        RunInspectionService(tmp_path).replay_run("run-1")


@pytest.mark.parametrize("checksum", [None, "invalid", "A" * 64])
def test_run_inspection_replay_rejects_missing_or_invalid_checksum(
    tmp_path,
    checksum,
) -> None:
    run_dir = _write_replay_run(tmp_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if checksum is None:
        manifest["artifact_metadata"]["report_json"].pop("checksum")
    else:
        manifest["artifact_metadata"]["report_json"]["checksum"] = checksum
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ArtifactStoreMetadataError):
        RunInspectionService(tmp_path).replay_run("run-1")


def test_run_inspection_replay_rejects_manifest_listed_missing_file(tmp_path) -> None:
    run_dir = _write_replay_run(tmp_path)
    (run_dir / "report.json").unlink()

    with pytest.raises(ArtifactNotFoundError, match="report.json"):
        RunInspectionService(tmp_path).replay_run("run-1")


def test_run_inspection_replay_preflights_unsafe_manifest_artifact_path(
    tmp_path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run-unsafe"
    run_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("artifact-secret", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-unsafe",
                "status": "succeeded",
                "artifacts": {"output": "../outside.txt"},
            }
        ),
        encoding="utf-8",
    )
    service = RunInspectionService(tmp_path)

    def fail_if_bundle_is_built(*args, **kwargs):
        raise AssertionError("replay bundle must not be built for an unsafe artifact path")

    monkeypatch.setattr(
        service._inspector,
        "build_replay_content_bundle",
        fail_if_bundle_is_built,
    )

    with pytest.raises(ArtifactPathError, match="invalid artifact path"):
        service.replay_run("run-unsafe")

    assert outside.read_text(encoding="utf-8") == "artifact-secret"


def test_run_inspection_replay_expands_source_artifacts(tmp_path) -> None:
    run_dir = tmp_path / "run-1"
    item_dir = run_dir / "sources" / "items" / "feed"
    error_dir = run_dir / "sources" / "errors" / "feed"
    item_dir.mkdir(parents=True)
    error_dir.mkdir(parents=True)
    (run_dir / "source_artifacts").mkdir()
    manifest = {
        "run_id": "run-1",
        "status": "succeeded",
        "artifacts": {
            "source_artifacts": "source_artifacts/index.json",
        },
    }
    source_index = {
        "entries": [
            {
                "artifact_type": "source_item",
                "source_id": "feed/source",
                "object_id": "item-1",
                "path": "sources/items/feed/item-1.json",
            },
            {
                "artifact_type": "source_error",
                "source_id": "feed/source",
                "object_id": "error-1",
                "path": "sources/errors/feed/error-1.json",
            },
        ],
        "item_count": 1,
        "error_count": 1,
    }
    source_index_bytes = json.dumps(source_index).encode("utf-8")
    manifest["artifact_metadata"] = {
        "source_artifacts": {
            "checksum": sha256(source_index_bytes).hexdigest(),
            "content_type": "application/json",
            "size_bytes": len(source_index_bytes),
        }
    }
    (run_dir / "source_artifacts" / "index.json").write_text(
        source_index_bytes.decode("utf-8"),
        encoding="utf-8",
    )
    (item_dir / "item-1.json").write_text(
        json.dumps({"item": {"title": "Item", "metadata": {"api_key": "hidden-key"}}}),
        encoding="utf-8",
    )
    (error_dir / "error-1.json").write_text(
        json.dumps({"error": {"error_type": "fetch_timeout", "url": "https://example.com"}}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = RunInspectionService(tmp_path).replay_run("run-1")

    payload = result.to_dict()
    artifacts = {artifact["artifact_key"]: artifact for artifact in payload["artifacts"]}
    item_key = "source_artifacts.source_item.feed_source.item-1"
    error_key = "source_artifacts.source_error.feed_source.error-1"
    assert item_key in artifacts
    assert error_key in artifacts
    assert artifacts[item_key]["relative_path"] == "sources/items/feed/item-1.json"
    assert artifacts[item_key]["content"]["item"]["metadata"]["api_key"] == "[redacted]"
    assert artifacts[error_key]["content"]["error"]["error_type"] == "fetch_timeout"
    assert "hidden-key" not in json.dumps(payload)


def test_run_inspection_diagnostics_and_health_read_real_run(tmp_path) -> None:
    _write_complete_inspection_run(tmp_path, "run-1")

    service = RunInspectionService(tmp_path)
    diagnostics = service.get_run_diagnostics("run-1")
    health = service.get_run_health("run-1")

    diagnostics_payload = diagnostics.to_dict()
    health_payload = health.to_dict()
    assert diagnostics_payload["run_id"] == "run-1"
    assert diagnostics_payload["diagnostics"]["healthy"] is True
    assert diagnostics_payload["diagnostics"]["timeline_summary"]["event_count"] == 2
    assert health_payload["run_id"] == "run-1"
    assert health_payload["health"]["severity"] == "ok"


def test_run_inspection_catalog_health_reports_failed_run(tmp_path) -> None:
    _write_complete_inspection_run(tmp_path, "run-ok")
    _write_complete_inspection_run(tmp_path, "run-failed", status="failed", terminal_key="error")

    result = RunInspectionService(tmp_path).get_catalog_health()

    payload = result.to_dict()
    assert payload["health"]["run_count"] == 2
    assert payload["health"]["failed_count"] == 1
    assert payload["health"]["latest_failed_run_id"] == "run-failed"


def test_run_inspection_compare_runs_reports_version_change(tmp_path) -> None:
    _write_complete_inspection_run(tmp_path, "run-v1", workflow_version="1.0")
    _write_complete_inspection_run(tmp_path, "run-v2", workflow_version="2.0")

    result = RunInspectionService(tmp_path).compare_runs("run-v1", "run-v2")

    payload = result.to_dict()
    assert payload["base_run_id"] == "run-v1"
    assert payload["target_run_id"] == "run-v2"
    assert payload["comparison"]["workflow_version_changed"] is True


def test_run_inspection_diagnostics_rejects_missing_run(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        RunInspectionService(tmp_path).get_run_diagnostics("missing")


def test_run_inspection_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(ArtifactPathError):
        RunInspectionService(tmp_path).get_run("../secret")


@pytest.mark.parametrize(
    "run_id",
    ["C:secret", "\\\\server\\share", "run:stream", "NUL", "run. "],
)
def test_run_inspection_rejects_unsafe_run_identifiers(tmp_path, run_id) -> None:
    with pytest.raises(ArtifactPathError):
        RunInspectionService(tmp_path).get_run(run_id)


def test_run_inspection_rejects_invalid_event_limit(tmp_path) -> None:
    with pytest.raises(ValueError):
        RunInspectionService(tmp_path).get_run_events("run-1", limit=0)


def _write_replay_run(root):
    run_dir = root / "run-1"
    run_dir.mkdir()
    files = {
        "events": (
            "events.jsonl",
            (
                json.dumps(
                    {
                        "event_type": "workflow_started",
                        "payload": {"token": "hidden"},
                    }
                )
                + "\n"
            ).encode("utf-8"),
        ),
        "step_results": (
            "step_results.json",
            json.dumps(
                {"write": {"status": "succeeded", "outputs": {"report": "ok"}}}
            ).encode("utf-8"),
        ),
        "report_json": (
            "report.json",
            json.dumps({"title": "Report", "api_key": "hidden-key"}).encode("utf-8"),
        ),
        "report_markdown": ("report.md", b"# Report\n"),
    }
    artifacts = {key: relative_path for key, (relative_path, _) in files.items()}
    artifacts["manifest"] = "manifest.json"
    artifact_metadata = {
        key: {
            "checksum": sha256(content).hexdigest(),
            "content_type": (
                "application/x-ndjson"
                if relative_path.endswith(".jsonl")
                else "application/json"
                if relative_path.endswith(".json")
                else "text/markdown"
            ),
            "size_bytes": len(content),
        }
        for key, (relative_path, content) in files.items()
    }
    artifact_metadata["manifest"] = {
        "checksum": "pending",
        "content_type": "application/json",
        "size_bytes": 0,
    }
    manifest = {
        "run_id": "run-1",
        "status": "succeeded",
        "artifacts": artifacts,
        "artifact_metadata": artifact_metadata,
    }
    for relative_path, content in files.values():
        (run_dir / relative_path).write_bytes(content)
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


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


def _write_complete_inspection_run(
    root,
    run_id,
    *,
    status="succeeded",
    workflow_version="1.0",
    terminal_key="output",
) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    artifacts = {
        "request": "request.json",
        "workflow_spec": "workflow_spec.json",
        "workflow_version": "workflow_version.json",
        "events": "events.jsonl",
        "manifest": "manifest.json",
        "data_buffer_snapshot": "data_buffer_snapshot.json",
        "data_buffer_initial": "data_buffer.initial.json",
        "data_buffer_final": "data_buffer.final.json",
        "data_buffer_diff": "data_buffer.diff.json",
        "step_results": "step_results.json",
        "metrics": "metrics.json",
        "redaction_report": "redaction_report.json",
        terminal_key: f"{terminal_key}.json",
    }
    manifest = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": run_id,
        "workflow_id": "daily",
        "workflow_version": workflow_version,
        "profile": "test",
        "status": status,
        "started_at": "2026-05-14T01:00:00Z",
        "finished_at": "2026-05-14T01:00:01Z",
        "path": ["step"],
        "steps": {"step": {"status": "succeeded", "outputs": {"report": "ok"}}},
        "artifacts": artifacts,
        "step_count": 1,
        "event_count": 2,
        "checkpoint_count": 0,
    }
    payloads = {
        "request.json": {"topic": "ai"},
        "workflow_spec.json": {"workflow_id": "daily"},
        "workflow_version.json": {"workflow_version": workflow_version},
        "data_buffer_snapshot.json": {"request": {"topic": "ai"}, "report": "ok"},
        "data_buffer.initial.json": {"request": {"topic": "ai"}},
        "data_buffer.final.json": {"request": {"topic": "ai"}, "report": "ok"},
        "data_buffer.diff.json": {"added": {"report": "ok"}, "changed": {}, "removed": {}},
        "step_results.json": {"step": {"status": "succeeded", "outputs": {"report": "ok"}}},
        "metrics.json": {"status": status, "step_count": 1},
        "redaction_report.json": {"redacted": False},
        f"{terminal_key}.json": {"report": "ok"} if terminal_key == "output" else {"message": "failed"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path, payload in payloads.items():
        (run_dir / relative_path).write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_type": "workflow_started", "run_id": run_id, "payload": {}}),
                json.dumps({"event_type": f"workflow_{status}", "run_id": run_id, "payload": {}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
