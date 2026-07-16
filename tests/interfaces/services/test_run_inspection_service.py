import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from framework.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactNotFoundError,
    ArtifactStoreMetadataError,
)
from framework.artifacts.paths import ArtifactPathError
from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
)
from framework.events.errors import EventStoreUnavailableError
from framework.events.schema import default_event_schema_catalog
from framework.workflow.runtime.event_projection import WorkflowEventProjectionExporter
from infrastructure.storage.events.sqlite import SQLiteEventStore
from interfaces.services.run_inspection_factory import build_run_inspection_service
from interfaces.services.run_inspection_service import RunInspectionService
from tests.fixtures.workflow_runs import rewrite_manifest, write_canonical_terminal_run


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


def test_run_inspection_missing_events_file_returns_projection_unavailable(tmp_path) -> None:
    _write_manifest(
        tmp_path,
        "run-1",
        {"run_id": "run-1", "status": "succeeded", "artifacts": {"events": "events.jsonl"}},
    )

    result = RunInspectionService(tmp_path).get_run_events("run-1").to_dict()

    assert result["availability"] == "unavailable"
    assert result["projection_status"] == "unavailable"
    assert result["events"] == []
    assert result["unavailable_reason_class"] == "EventStoreUnavailableError"


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


def test_run_inspection_reads_authoritative_durable_events_with_stable_cursor(
    tmp_path,
) -> None:
    store, service = _durable_inspection_run(tmp_path, event_count=3)

    first = service.get_run_events("run-durable", limit=1)
    first_payload = first.to_dict()

    assert first_payload["availability"] == "available"
    assert first_payload["source"] == "durable_store"
    assert first_payload["projection_status"] == "current"
    assert first_payload["high_watermark"] == 3
    assert first_payload["events"][0]["stream_sequence"] == 1
    assert first_payload["next_sequence_cursor"]

    store.append_event(_durable_event(4))
    second = service.get_run_events(
        "run-durable",
        limit=10,
        sequence_cursor=first_payload["next_sequence_cursor"],
    ).to_dict()

    assert second["high_watermark"] == 3
    assert [event["stream_sequence"] for event in second["events"]] == [2, 3]
    assert second["next_sequence_cursor"] is None


def test_run_inspection_legacy_offset_and_filters_do_not_skip_cursor_boundary(
    tmp_path,
) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=4)

    page = service.get_run_events("run-durable", offset=1, limit=1).to_dict()

    assert [event["stream_sequence"] for event in page["events"]] == [2]
    resumed = service.get_run_events(
        "run-durable",
        sequence_cursor=page["next_sequence_cursor"],
        limit=10,
    ).to_dict()
    assert [event["stream_sequence"] for event in resumed["events"]] == [3, 4]

    filtered = service.get_run_events(
        "run-durable",
        event_type="step_started",
        step_id="step-3",
        limit=10,
    ).to_dict()
    assert [event["stream_sequence"] for event in filtered["events"]] == [3]


def test_run_inspection_rejects_tampered_or_cross_run_sequence_cursor(tmp_path) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=2)
    _write_manifest(
        tmp_path,
        "other-run",
        {"run_id": "other-run", "status": "succeeded", "artifacts": {"events": "events.jsonl"}},
    )
    (tmp_path / "other-run" / "events.jsonl").write_text("", encoding="utf-8")
    cursor = service.get_run_events("run-durable", limit=1).next_sequence_cursor
    assert cursor is not None
    padded = cursor + "=" * (-len(cursor) % 4)
    tampered_payload = json.loads(
        base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    )
    tampered_payload["after_sequence"] += 1
    tampered = base64.urlsafe_b64encode(
        json.dumps(
            tampered_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).decode("ascii").rstrip("=")

    with pytest.raises(ValueError, match="invalid|integrity"):
        service.get_run_events("run-durable", sequence_cursor=tampered)
    with pytest.raises(ValueError, match="scope"):
        service.get_run_events("other-run", sequence_cursor=cursor)


def test_run_inspection_marks_projection_fallback_unavailable_and_stale(
    tmp_path,
) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=2)
    service._event_reader_service = _UnavailableEventReaderService()

    result = service.get_run_events("run-durable", limit=1).to_dict()

    assert result["availability"] == "unavailable"
    assert result["source"] == "projection"
    assert result["projection_status"] == "stale"
    assert result["projection_high_watermark"] == 2
    assert result["unavailable_reason_class"] == "EventStoreUnavailableError"
    assert result["event_count"] == 1


@pytest.mark.parametrize("mutation", ["append", "truncate"])
def test_run_inspection_does_not_serve_corrupt_projection_fallback(
    tmp_path,
    mutation,
) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=2)
    projection_path = tmp_path / "run-durable" / "events.jsonl"
    content = projection_path.read_bytes()
    projection_path.write_bytes(
        content + b"{}\n" if mutation == "append" else content[:-1]
    )
    service._event_reader_service = _UnavailableEventReaderService()

    result = service.get_run_events("run-durable").to_dict()

    assert result["availability"] == "unavailable"
    assert result["projection_status"] == "unavailable"
    assert result["events"] == []
    assert result["unavailable_reason_class"] == "EventProjectionConflictError"


def test_run_inspection_cursor_never_falls_back_to_projection(tmp_path) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=2)
    cursor = service.get_run_events("run-durable", limit=1).next_sequence_cursor
    service._event_reader_service = _UnavailableEventReaderService()

    result = service.get_run_events(
        "run-durable",
        sequence_cursor=cursor,
    ).to_dict()

    assert result["availability"] == "unavailable"
    assert result["source"] == "projection"
    assert result["events"] == []
    assert result["next_sequence_cursor"] is None


def test_run_inspection_cursor_fallback_requires_existing_verified_projection(
    tmp_path,
) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=2)
    cursor = service.get_run_events("run-durable", limit=1).next_sequence_cursor
    (tmp_path / "run-durable" / "events.jsonl").unlink()
    service._event_reader_service = _UnavailableEventReaderService()

    result = service.get_run_events(
        "run-durable",
        sequence_cursor=cursor,
    ).to_dict()

    assert result["availability"] == "unavailable"
    assert result["projection_status"] == "unavailable"
    assert result["events"] == []
    assert result["unavailable_reason_class"] == "EventProjectionConflictError"


def test_run_inspection_store_unavailable_without_projection_is_not_not_found(
    tmp_path,
) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=1)
    run_dir = tmp_path / "run-durable"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"] = {}
    manifest.pop("event_projection")
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").unlink()
    service._event_reader_service = _UnavailableEventReaderService()

    result = service.get_run_events("run-durable").to_dict()

    assert result["availability"] == "unavailable"
    assert result["projection_status"] == "unavailable"
    assert result["events"] == []
    assert result["events_path"] is None
    assert result["unavailable_reason_class"] == "EventStoreUnavailableError"


def test_run_inspection_sse_resume_cursor_follows_live_stream_tail(tmp_path) -> None:
    store, service = _durable_inspection_run(tmp_path, event_count=2)

    first = service.get_run_events_for_sse("run-durable", limit=10).to_dict()
    cursor = first["sse_resume_cursor"]
    assert cursor == first["events"][-1]["sse_resume_cursor"]

    empty = service.get_run_events_for_sse(
        "run-durable",
        last_event_id=cursor,
    ).to_dict()
    assert empty["events"] == []
    assert empty["sse_resume_cursor"] == cursor

    store.append_event(_durable_event(3))
    resumed = service.get_run_events_for_sse(
        "run-durable",
        last_event_id=cursor,
    ).to_dict()
    assert [event["stream_sequence"] for event in resumed["events"]] == [3]
    assert resumed["sse_resume_cursor"] != cursor


def test_run_inspection_rejects_tampered_or_cross_run_sse_cursor(tmp_path) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=1)
    cursor = service.get_run_events_for_sse("run-durable").sse_resume_cursor
    assert cursor is not None

    with pytest.raises(ValueError, match="invalid|integrity"):
        service.get_run_events_for_sse(
            "run-durable",
            last_event_id=cursor[:-1] + ("A" if cursor[-1] != "A" else "B"),
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        service.get_run_events_for_sse(
            "run-durable",
            sequence_cursor="snapshot-cursor",
            last_event_id=cursor,
        )


def test_run_inspection_rejects_nonzero_sse_cursor_for_empty_stream(tmp_path) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=1)
    cursor = service.get_run_events_for_sse("run-durable").sse_resume_cursor
    assert cursor is not None
    service._event_reader_service = _EmptyHighWatermarkEventReaderService()

    with pytest.raises(ValueError, match="does not exist"):
        service.get_run_events_for_sse(
            "run-durable",
            last_event_id=cursor,
        )


def test_run_inspection_uses_default_page_size_of_one_hundred(tmp_path) -> None:
    _, service = _durable_inspection_run(tmp_path, event_count=101)

    page = service.get_run_events("run-durable")
    sse_page = service.get_run_events_for_sse("run-durable")

    assert len(page.events) == 100
    assert page.next_sequence_cursor is not None
    assert len(sse_page.events) == 100
    assert sse_page.sse_resume_cursor == sse_page.events[-1]["sse_resume_cursor"]


def test_run_inspection_replay_reads_real_artifacts_and_redacts(tmp_path) -> None:
    _write_replay_run(tmp_path)

    result = RunInspectionService(tmp_path).replay_run("run-1")

    payload = result.to_dict()
    artifacts = {artifact["artifact_key"]: artifact for artifact in payload["artifacts"]}
    assert payload["event_count"] == 2
    assert payload["step_result_count"] == 1
    assert payload["step_results"]["write"]["status"] == "succeeded"
    assert payload["integrity"]["valid"] is True
    assert payload["events"][0]["payload"]["token"] == "[redacted]"
    assert artifacts["report_json"]["content"]["api_key"] == "[redacted]"
    assert artifacts["report_markdown"]["content"] == "# Report\n"
    assert artifacts["manifest"]["content"]["artifact_metadata"]["manifest"]["checksum"] == "pending"
    assert "hidden-key" not in json.dumps(payload)


@pytest.mark.parametrize("projection_mutation", ["delete", "tamper"])
def test_run_inspection_online_replay_uses_durable_events_not_projection(
    tmp_path,
    projection_mutation,
) -> None:
    run_dir = _write_replay_run(tmp_path)
    _, service = _durable_service(
        tmp_path,
        [
            _durable_run_event("run-1", 1, "workflow_started"),
            _durable_run_event("run-1", 2, "workflow_succeeded"),
        ],
    )
    projection_path = run_dir / "events.jsonl"
    if projection_mutation == "delete":
        projection_path.unlink()
    else:
        projection_path.write_text(
            json.dumps(
                {
                    "event_id": "projection-only",
                    "event_type": "workflow_failed",
                    "run_id": "run-1",
                    "payload": {"path": [], "error": {"error_type": "forged"}},
                }
            )
            + "\n",
            encoding="utf-8",
        )

    payload = service.replay_run("run-1").to_dict()

    assert [event["event_id"] for event in payload["events"]] == [
        "evt-run-1-1",
        "evt-run-1-2",
    ]
    assert [event["event_type"] for event in payload["events"]] == [
        "workflow_started",
        "workflow_succeeded",
    ]
    projection_artifact = next(
        artifact
        for artifact in payload["artifacts"]
        if artifact["artifact_key"] == "events"
    )
    assert projection_artifact["content"] is None
    assert payload["integrity"]["valid"] is True


def test_run_inspection_online_replay_still_verifies_non_event_artifacts(
    tmp_path,
) -> None:
    run_dir = _write_replay_run(tmp_path)
    _, service = _durable_service(
        tmp_path,
        [_durable_run_event("run-1", 1, "workflow_started")],
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Tampered"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactChecksumMismatchError, match="report_json"):
        service.replay_run("run-1")


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


def test_run_inspection_replay_rejects_invalid_canonical_manifest(tmp_path) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    manifest = json.loads(json.dumps(fixture.manifest))
    manifest.pop("workflow_id")
    rewrite_manifest(fixture, manifest)

    with pytest.raises(ArtifactStoreMetadataError, match="canonical run manifest"):
        RunInspectionService(tmp_path).replay_run("run-1")


def test_run_inspection_replay_uses_verified_snapshot_after_target_replacement(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    output_path = fixture.artifact_path("output")
    original_read_bytes = type(output_path).read_bytes
    replaced = False

    def replace_after_capture(path):
        nonlocal replaced
        content = original_read_bytes(path)
        if path == output_path and not replaced:
            replaced = True
            output_path.write_bytes(b'{"result":"tampered"}')
        return content

    monkeypatch.setattr(type(output_path), "read_bytes", replace_after_capture)

    result = RunInspectionService(tmp_path).replay_run("run-1")
    artifacts = {artifact.artifact_key: artifact for artifact in result.artifacts}

    assert replaced is True
    assert artifacts["output"].content["result"] == "verified-original"


def test_run_inspection_replay_preflights_unsafe_manifest_artifact_path(
    tmp_path,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path, run_id="run-unsafe")
    outside = tmp_path / "outside.txt"
    outside.write_text("artifact-secret", encoding="utf-8")
    manifest = json.loads(json.dumps(fixture.manifest))
    manifest["artifacts"]["output"] = "../outside.txt"
    rewrite_manifest(fixture, manifest)

    with pytest.raises(ArtifactStoreMetadataError, match="canonical run manifest"):
        RunInspectionService(tmp_path).replay_run("run-unsafe")

    assert outside.read_text(encoding="utf-8") == "artifact-secret"


def test_run_inspection_replay_expands_source_artifacts(tmp_path) -> None:
    item_bytes = json.dumps(
        {"item": {"title": "Item", "metadata": {"api_key": "hidden-key"}}}
    ).encode("utf-8")
    error_bytes = json.dumps(
        {"error": {"error_type": "fetch_timeout", "url": "https://example.com"}}
    ).encode("utf-8")
    source_index = {
        "entries": [
            {
                "artifact_type": "source_item",
                "source_id": "feed/source",
                "object_id": "item-1",
                "path": "sources/items/feed/item-1.json",
                "checksum": sha256(item_bytes).hexdigest(),
                "content_type": "application/json",
                "size_bytes": len(item_bytes),
            },
            {
                "artifact_type": "source_error",
                "source_id": "feed/source",
                "object_id": "error-1",
                "path": "sources/errors/feed/error-1.json",
                "checksum": sha256(error_bytes).hexdigest(),
                "content_type": "application/json",
                "size_bytes": len(error_bytes),
            },
        ],
        "item_count": 1,
        "error_count": 1,
    }
    source_index_bytes = json.dumps(source_index).encode("utf-8")
    fixture = write_canonical_terminal_run(
        tmp_path,
        extra_artifacts={
            "source_artifacts": ("source_artifacts/index.json", source_index_bytes),
        },
    )
    item_path = fixture.run_dir / "sources/items/feed/item-1.json"
    item_path.parent.mkdir(parents=True)
    item_path.write_bytes(item_bytes)
    error_path = fixture.run_dir / "sources/errors/feed/error-1.json"
    error_path.parent.mkdir(parents=True)
    error_path.write_bytes(error_bytes)

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


def test_run_inspection_replay_preserves_source_response_business_content_type(
    tmp_path,
) -> None:
    content = b'{"headers":{"Content-Type":"application/rss+xml"}}'
    checksum = sha256(content).hexdigest()
    entry = {
        "artifact_id": "source-response-headers-1",
        "artifact_type": "source_response_headers",
        "source_id": "feed",
        "object_id": "request-1",
        "path": "sources/response_headers/feed/request-1.json",
        "content_type": "application/rss+xml",
        "size_bytes": len(content),
        "checksum": checksum,
        "artifact_ref": {
            "artifact_id": "source-response-headers-1",
            "run_id": "run-1",
            "artifact_type": "source_response_headers",
            "path": "sources/response_headers/feed/request-1.json",
            "content_type": "application/json",
            "size_bytes": len(content),
            "checksum": checksum,
        },
    }
    index_bytes = json.dumps({"entries": [entry]}).encode("utf-8")
    fixture = write_canonical_terminal_run(
        tmp_path,
        extra_artifacts={
            "source_artifacts": ("source_artifacts/index.json", index_bytes),
        },
    )
    target = fixture.run_dir / entry["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(content)

    payload = RunInspectionService(tmp_path).replay_run("run-1").to_dict()
    records = {record["artifact_key"]: record for record in payload["artifacts"]}
    record = records[
        "source_artifacts.source_response_headers.feed.request-1"
    ]

    assert record["content_type"] == "application/json"
    assert record["metadata"]["content_type"] == "application/rss+xml"
    assert record["metadata"]["artifact_ref"]["content_type"] == "application/json"


def test_run_inspection_replay_rejects_tampered_selected_index_target(tmp_path) -> None:
    content = b'{"item":{"title":"verified"}}'
    fixture = _write_service_index_run(tmp_path, content, include_checksum=True)
    (fixture.run_dir / "sources/items/feed/item-1.json").write_bytes(
        b'{"item":{"title":"tampered"}}'
    )

    with pytest.raises(ArtifactChecksumMismatchError):
        RunInspectionService(tmp_path).replay_run("run-1")


def test_run_inspection_replay_rejects_selected_index_without_checksum(tmp_path) -> None:
    content = b'{"item":{"title":"verified"}}'
    _write_service_index_run(tmp_path, content, include_checksum=False)

    with pytest.raises(ArtifactStoreMetadataError, match="checksum is missing"):
        RunInspectionService(tmp_path).replay_run("run-1")


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


@pytest.mark.parametrize("projection_mutation", ["delete", "tamper"])
def test_run_inspection_online_diagnostics_and_health_use_durable_events(
    tmp_path,
    projection_mutation,
) -> None:
    _write_complete_inspection_run(tmp_path, "run-1")
    _, service = _durable_service(
        tmp_path,
        [
            _durable_run_event("run-1", 1, "workflow_started"),
            _durable_run_event("run-1", 2, "workflow_succeeded"),
        ],
    )
    projection_path = tmp_path / "run-1" / "events.jsonl"
    if projection_mutation == "delete":
        projection_path.unlink()
    else:
        projection_path.write_text("{not-json\n", encoding="utf-8")

    diagnostics = service.get_run_diagnostics("run-1").to_dict()["diagnostics"]
    health = service.get_run_health("run-1").to_dict()["health"]

    assert diagnostics["timeline_summary"]["event_count"] == 2
    assert diagnostics["timeline_summary"]["terminal_event_type"] == "workflow_succeeded"
    assert diagnostics["checksum_failures"] == []
    assert diagnostics["missing_artifacts"] == []
    assert health["event_count"] == 2
    assert health["severity"] == "ok"


def test_run_inspection_derived_read_pages_through_fixed_high_watermark(
    tmp_path,
) -> None:
    _write_complete_inspection_run(tmp_path, "run-1")
    store, service = _durable_service(
        tmp_path,
        [
            _durable_run_event("run-1", 1, "workflow_started"),
            _durable_run_event("run-1", 2, "workflow_succeeded"),
        ],
    )
    reader = _AppendingCappedEventReaderService(
        service._event_reader_service,
        store=store,
        appended_event=_durable_run_event("run-1", 3, "step_started"),
    )
    service._event_reader_service = reader

    diagnostics = service.get_run_diagnostics("run-1").to_dict()["diagnostics"]

    assert diagnostics["timeline_summary"]["event_count"] == 2
    assert reader.requested_watermarks == [2, 2]
    assert store.get_stream_high_watermark(
        "run:run-1",
        tenant_id="tenant-a",
    ) == 3


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


def test_run_inspection_online_compare_reads_each_durable_stream(tmp_path) -> None:
    _write_complete_inspection_run(tmp_path, "run-v1", workflow_version="1.0")
    _write_complete_inspection_run(tmp_path, "run-v2", workflow_version="2.0")
    _, service = _durable_service(
        tmp_path,
        [
            _durable_run_event("run-v1", 1, "workflow_started"),
            _durable_run_event("run-v1", 2, "workflow_succeeded"),
            _durable_run_event("run-v2", 1, "workflow_started"),
            _durable_run_event("run-v2", 2, "step_started"),
            _durable_run_event("run-v2", 3, "workflow_succeeded"),
        ],
    )
    (tmp_path / "run-v1" / "events.jsonl").write_text(
        "{not-json\n",
        encoding="utf-8",
    )
    (tmp_path / "run-v2" / "events.jsonl").unlink()

    comparison = service.compare_runs("run-v1", "run-v2").to_dict()["comparison"]

    assert comparison["event_count_delta"] == 1
    assert comparison["workflow_version_changed"] is True


def test_run_inspection_online_derived_reads_fail_when_store_is_unavailable(
    tmp_path,
) -> None:
    _write_replay_run(tmp_path)
    _write_complete_inspection_run(tmp_path, "run-2")
    _, service = _durable_service(
        tmp_path,
        [_durable_run_event("run-1", 1, "workflow_started")],
    )
    service._event_reader_service = _UnavailableEventReaderService()

    operations = (
        lambda: service.replay_run("run-1"),
        lambda: service.get_run_diagnostics("run-1"),
        lambda: service.get_run_health("run-1"),
        lambda: service.compare_runs("run-1", "run-2"),
    )
    for operation in operations:
        with pytest.raises(EventStoreUnavailableError, match="durable event store"):
            operation()


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
    fixture = write_canonical_terminal_run(
        root,
        events=[
            {
                "event_type": "workflow_started",
                "run_id": "run-1",
                "payload": {"token": "hidden"},
            },
            {
                "event_type": "workflow_succeeded",
                "run_id": "run-1",
                "payload": {},
            },
        ],
        extra_artifacts={
            "report_json": (
                "report.json",
                json.dumps({"title": "Report", "api_key": "hidden-key"}).encode("utf-8"),
            ),
            "report_markdown": ("report.md", b"# Report\n"),
        },
    )
    return fixture.run_dir


def _write_service_index_run(root, content, *, include_checksum):
    entry = {
        "artifact_id": "source-item-1",
        "artifact_type": "source_item",
        "source_id": "feed",
        "object_id": "item-1",
        "path": "sources/items/feed/item-1.json",
        "content_type": "application/json",
        "size_bytes": len(content),
    }
    if include_checksum:
        entry["checksum"] = sha256(content).hexdigest()
    index_bytes = json.dumps({"entries": [entry]}).encode("utf-8")
    fixture = write_canonical_terminal_run(
        root,
        extra_artifacts={
            "source_artifacts": ("source_artifacts/index.json", index_bytes),
        },
    )
    target = fixture.run_dir / entry["path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    return fixture


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


def _durable_inspection_run(root, *, event_count: int):
    run_id = "run-durable"
    run_dir = root / run_id
    run_dir.mkdir()
    store = SQLiteEventStore(root / "event-store.sqlite3", clock=lambda: datetime(2026, 7, 16, 4, tzinfo=UTC))
    for sequence in range(1, event_count + 1):
        store.append_event(_durable_event(sequence))
    catalog = default_event_schema_catalog()
    projection = WorkflowEventProjectionExporter(
        reader=store,
        schema_catalog=catalog,
    ).export(
        stream_id=f"run:{run_id}",
        tenant_id="tenant-a",
        target=run_dir / "events.jsonl",
        through_sequence=event_count,
    )
    manifest = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": run_id,
        "status": "succeeded",
        "artifacts": {"events": "events.jsonl"},
        "event_count": event_count,
        "event_projection": {
            "path": "events.jsonl",
            "stream_id": projection.stream_id,
            "high_watermark": projection.high_watermark,
            "event_count": projection.event_count,
            "checksum": projection.checksum,
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    storage = SimpleNamespace(event_store=store, schema_catalog=catalog)
    service = build_run_inspection_service(
        artifact_root=root,
        event_storage=storage,
        tenant_id="tenant-a",
    )
    return store, service


def _durable_service(root, events):
    store = SQLiteEventStore(
        root / "derived-event-store.sqlite3",
        clock=lambda: datetime(2026, 7, 17, 4, tzinfo=UTC),
    )
    for event in events:
        store.append_event(event)
    catalog = default_event_schema_catalog()
    storage = SimpleNamespace(event_store=store, schema_catalog=catalog)
    return store, build_run_inspection_service(
        artifact_root=root,
        event_storage=storage,
        tenant_id="tenant-a",
    )


def _durable_run_event(
    run_id: str,
    sequence: int,
    event_type: str,
) -> EventCandidate:
    if event_type == "workflow_started":
        payload = {"workflow_version": "1.0", "profile": "test"}
        step_id = None
    elif event_type == "workflow_succeeded":
        payload = {"path": ["step"]}
        step_id = None
    elif event_type == "step_started":
        payload = {"step_type": "function", "attempt": 1, "max_attempts": 1}
        step_id = "step"
    else:
        raise ValueError(f"unsupported durable test event: {event_type}")
    return EventCandidate(
        event_id=f"evt-{run_id}-{sequence}",
        event_type=event_type,
        data_schema="newsroom.workflow-event/v1",
        source="io.newsroom.workflow.runtime",
        occurred_at=datetime(2026, 7, 17, 1, tzinfo=UTC)
        + timedelta(seconds=sequence),
        stream_id=f"run:{run_id}",
        business_context=BusinessContext(
            run_id=run_id,
            workflow_id="daily",
            step_id=step_id,
        ),
        producer=ProducerIdentity(
            component="framework.workflow.runtime",
            version="1",
        ),
        tenant_id="tenant-a",
        payload=payload,
    )


def _durable_event(sequence: int) -> EventCandidate:
    first = sequence == 1
    return EventCandidate(
        event_id=f"evt-durable-{sequence}",
        event_type="workflow_started" if first else "step_started",
        data_schema="newsroom.workflow-event/v1",
        source="io.newsroom.workflow.runtime",
        occurred_at=datetime(2026, 7, 16, 1, tzinfo=UTC) + timedelta(seconds=sequence),
        stream_id="run:run-durable",
        business_context=BusinessContext(
            run_id="run-durable",
            workflow_id="workflow-1",
            step_id=None if first else f"step-{sequence}",
        ),
        producer=ProducerIdentity(component="framework.workflow.runtime", version="1"),
        tenant_id="tenant-a",
        payload=(
            {"workflow_version": "1", "profile": "test"}
            if first
            else {"step_type": "function", "attempt": 1, "max_attempts": 1}
        ),
    )


class _UnavailableEventReaderService:
    def get_high_watermark(self, stream_id, *, authorization):
        from interfaces.services.event_reader_service import (
            EventHighWatermarkResult,
            EventServiceAvailability,
        )

        return EventHighWatermarkResult(
            availability=EventServiceAvailability.UNAVAILABLE,
            stream_id=stream_id,
            tenant_id=authorization.tenant_id,
            unavailable_reason_class=EventStoreUnavailableError.__name__,
        )

    def read_run_events(self, run_id, *, authorization, **kwargs):
        from interfaces.services.event_reader_service import (
            EventServiceAvailability,
            EventStreamReadResult,
        )

        return EventStreamReadResult(
            availability=EventServiceAvailability.UNAVAILABLE,
            stream_id=f"run:{run_id}",
            tenant_id=authorization.tenant_id,
            unavailable_reason_class=EventStoreUnavailableError.__name__,
        )


class _EmptyHighWatermarkEventReaderService:
    def get_high_watermark(self, stream_id, *, authorization):
        from interfaces.services.event_reader_service import (
            EventHighWatermarkResult,
            EventServiceAvailability,
        )

        return EventHighWatermarkResult(
            availability=EventServiceAvailability.AVAILABLE,
            stream_id=stream_id,
            tenant_id=authorization.tenant_id,
            high_watermark=None,
        )


class _AppendingCappedEventReaderService:
    def __init__(self, delegate, *, store, appended_event) -> None:
        self._delegate = delegate
        self._store = store
        self._appended_event = appended_event
        self._appended = False
        self.requested_watermarks = []

    def get_high_watermark(self, stream_id, *, authorization):
        result = self._delegate.get_high_watermark(
            stream_id,
            authorization=authorization,
        )
        if not self._appended:
            self._store.append_event(self._appended_event)
            self._appended = True
        return result

    def read_run_events(self, run_id, *, authorization, **kwargs):
        kwargs["limit"] = 1
        self.requested_watermarks.append(kwargs.get("through_sequence"))
        return self._delegate.read_run_events(
            run_id,
            authorization=authorization,
            **kwargs,
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
