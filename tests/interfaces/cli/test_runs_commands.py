import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest

import interfaces.cli.news as news_cli
from framework.agent.artifacts import (
    ArtifactChecksumMismatchError,
    ArtifactPathError,
    ArtifactStoreMetadataError,
    ArtifactStoreRequiredError,
)
from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore
from interfaces.cli.commands import runs as runs_commands
from tests.fixtures.workflow_runs import write_canonical_terminal_run


def test_news_cli_runs_list_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        _FakeRunInspectionService,
    )

    exit_code = news_cli.main(["runs", "list", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_count"] == 1
    assert payload["runs"][0]["run_id"] == "run-1"


def test_news_cli_runs_show_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        _FakeRunInspectionService,
    )

    exit_code = news_cli.main(["runs", "show", "run-1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["manifest"]["status"] == "succeeded"


def test_news_cli_runs_events_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        _FakeRunInspectionService,
    )

    exit_code = news_cli.main(["runs", "events", "run-1", "--limit", "1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["event_count"] == 1
    assert payload["events"][0]["event_type"] == "workflow_started"


def test_news_cli_runs_events_sse(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        _FakeRunInspectionService,
    )

    exit_code = news_cli.main(["runs", "events", "run-1", "--limit", "1", "--sse"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "event: workflow_started\n" in captured.out
    assert "event: run.events.done\n" in captured.out
    assert '"sequence": null' in captured.out
    assert '"event_count": 1' in captured.out


def test_news_cli_runs_events_invalid_limit_returns_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "run_inspection_service_from_env", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "events", "run-1", "--limit", "0", "--json"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "limit must be greater than zero" in captured.out


def test_news_cli_runs_replay_json_reads_real_files(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    write_canonical_terminal_run(tmp_path)
    monkeypatch.delenv("NEWS_DATABASE_DSN", raising=False)
    monkeypatch.setenv("NEWS_TENANT_ID", "tenant-a")
    _seed_durable_run_events(tmp_path)

    exit_code = news_cli.main(
        [
            "runs",
            "replay",
            "run-1",
            "--artifact-root",
            str(tmp_path),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    artifacts = {artifact["artifact_key"]: artifact for artifact in payload["artifacts"]}

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["event_count"] == 2
    assert payload["step_result_count"] == 1
    assert payload["step_results"]["write"]["status"] == "succeeded"
    assert payload["integrity"]["valid"] is True
    assert artifacts["output"]["content"]["token"] == "[redacted]"


def test_news_cli_runs_replay_text_reads_real_files(tmp_path, capsys) -> None:
    write_canonical_terminal_run(tmp_path)

    exit_code = news_cli.main(["runs", "replay", "run-1", "--artifact-root", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "run_id=run-1" in captured.out
    assert "artifact_count=13" in captured.out
    assert "- output path=output.json" in captured.out


def test_news_cli_runs_diagnostics_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "run_inspection_service_from_env", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "diagnostics", "run-1", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["diagnostics"]["healthy"] is True


def test_news_cli_runs_health_text(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "run_inspection_service_from_env", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "health", "run-1"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "severity=ok" in captured.out
    assert "healthy=true" in captured.out


def test_news_cli_runs_catalog_health_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "run_inspection_service_from_env", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "catalog-health", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["health"]["severity"] == "ok"
    assert payload["health"]["run_count"] == 1


def test_news_cli_runs_compare_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "run_inspection_service_from_env", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "compare", "run-1", "run-2", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["base_run_id"] == "run-1"
    assert payload["target_run_id"] == "run-2"
    assert payload["comparison"]["same_workflow"] is True


def test_news_cli_runs_artifacts_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "ArtifactInspectionService", _FakeArtifactService)

    exit_code = news_cli.main(["runs", "artifacts", "run-1", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["artifact_count"] == 1
    assert payload["artifacts"][0]["artifact_key"] == "report_json"


def test_news_cli_runs_artifacts_missing_returns_not_found(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "ArtifactInspectionService", _MissingArtifactService)

    exit_code = news_cli.main(["runs", "artifacts", "missing", "--json"])

    captured = capsys.readouterr()

    assert exit_code == 3
    assert "run not found: missing" in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        ["runs", "show", "run:stream", "--json"],
        ["runs", "events", "run:stream", "--json"],
        ["runs", "replay", "run:stream", "--json"],
        ["runs", "diagnostics", "run:stream", "--json"],
        ["runs", "health", "run:stream", "--json"],
        ["runs", "compare", "run:stream", "run-2", "--json"],
    ],
)
def test_news_cli_runs_inspection_path_error_uses_stderr_and_exit_one(
    monkeypatch,
    capsys,
    argv,
) -> None:
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        _ArtifactPathRunInspectionService,
    )

    exit_code = news_cli.main(argv)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid artifact path" in captured.err


def test_news_cli_runs_artifacts_path_error_precedes_plain_value_error(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        runs_commands,
        "ArtifactInspectionService",
        _ArtifactPathArtifactService,
    )

    exit_code = news_cli.main(["runs", "artifacts", "run:stream", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid artifact path" in captured.err


def test_news_cli_runs_artifacts_plain_value_error_keeps_exit_two(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        runs_commands,
        "ArtifactInspectionService",
        _InvalidArtifactService,
    )

    exit_code = news_cli.main(["runs", "artifacts", "run-1", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "invalid artifact request" in captured.out
    assert captured.err == ""


def test_news_cli_runs_replay_rejects_unsafe_manifest_artifact_path(
    tmp_path,
    capsys,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path, "run-unsafe")
    run_dir = fixture.run_dir
    (tmp_path / "outside.txt").write_text("artifact-secret", encoding="utf-8")
    manifest = dict(fixture.manifest)
    manifest["artifacts"] = dict(fixture.manifest["artifacts"])
    manifest["artifacts"]["output"] = "../outside.txt"
    fixture.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    exit_code = news_cli.main(
        [
            "runs",
            "replay",
            "run-unsafe",
            "--artifact-root",
            str(tmp_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid canonical run manifest" in captured.err
    assert "artifact-secret" not in captured.err


@pytest.mark.parametrize(
    "error_type",
    [
        ArtifactChecksumMismatchError,
        ArtifactStoreMetadataError,
        ArtifactStoreRequiredError,
    ],
)
def test_news_cli_runs_replay_integrity_error_uses_stderr_and_exit_one(
    monkeypatch,
    capsys,
    error_type,
) -> None:
    error = error_type("run replay integrity verification failed")
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        lambda *args, **kwargs: _ArtifactIntegrityRunInspectionService(error),
    )

    exit_code = news_cli.main(["runs", "replay", "run-1", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "run replay integrity verification failed\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["runs", "replay", "run-1", "--json"],
        ["runs", "diagnostics", "run-1", "--json"],
        ["runs", "health", "run-1", "--json"],
        ["runs", "compare", "run-1", "run-2", "--json"],
    ],
)
def test_news_cli_runs_derived_reads_report_store_unavailable(
    monkeypatch,
    capsys,
    argv,
) -> None:
    monkeypatch.setattr(
        runs_commands,
        "run_inspection_service_from_env",
        lambda *args, **kwargs: _UnavailableDerivedRunInspectionService(),
    )

    exit_code = news_cli.main(argv)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == (
        "availability=unavailable error_type=EventStoreUnavailableError\n"
    )
    assert "database-host" not in captured.err


def test_news_cli_runs_replay_real_tamper_uses_stderr_and_exit_one(
    tmp_path,
    capsys,
) -> None:
    fixture = write_canonical_terminal_run(tmp_path)
    fixture.artifact_path("output").write_text(
        json.dumps({"result": "tampered-cli-secret"}),
        encoding="utf-8",
    )

    exit_code = news_cli.main(
        [
            "runs",
            "replay",
            "run-1",
            "--artifact-root",
            str(tmp_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "artifact checksum mismatch" in captured.err
    assert "tampered-cli-secret" not in captured.err


def test_news_cli_runs_cancel_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "RunOperationApplicationService", _FakeRunOperationService)

    exit_code = news_cli.main(
        [
            "runs",
            "cancel",
            "run-1",
            "--reason",
            "manual stop",
            "--actor-id",
            "operator",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["operation_type"] == "cancel_run"
    assert payload["status"] == "accepted"
    assert payload["details"]["reason"] == "manual stop"
    assert payload["details"]["actor_id"] == "operator"


def test_news_cli_runs_rerun_from_step_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(runs_commands, "RunOperationApplicationService", _FakeRunOperationService)

    exit_code = news_cli.main(
        ["runs", "rerun-from-step", "run-1", "write_report", "--actor-id", "operator", "--json"]
    )

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["operation_type"] == "rerun_from_step"
    assert payload["status"] == "accepted"
    assert payload["details"]["step_id"] == "write_report"
    assert payload["details"]["actor_id"] == "operator"


class _FakeRunInspectionService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_runs(self, *, limit):
        return _FakeResult(
            {
                "run_count": 1,
                "runs": [
                    {
                        "run_id": "run-1",
                        "status": "succeeded",
                        "workflow_id": "daily",
                        "workflow_version": "0.1.0",
                        "profile": "live-offline",
                        "started_at": "2026-05-11T01:00:00Z",
                        "finished_at": "2026-05-11T01:00:01Z",
                        "quality_score": 1.0,
                        "step_count": 7,
                        "event_count": 16,
                        "manifest_path": ".newsroom/runs/run-1/manifest.json",
                    }
                ],
            }
        )

    def get_run(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "manifest": {"run_id": run_id, "status": "succeeded"},
                "manifest_path": f".newsroom/runs/{run_id}/manifest.json",
            }
        )

    def get_run_events(self, run_id, *, limit=None):
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        events = [
            {
                "event_type": "workflow_started",
                "occurred_at": "2026-05-11T01:00:00Z",
                "payload": {"profile": "live-offline"},
            },
            {
                "event_type": "workflow_succeeded",
                "occurred_at": "2026-05-11T01:00:01Z",
                "payload": {},
            },
        ]
        if limit is not None:
            events = events[:limit]
        return _FakeResult(
            {
                "run_id": run_id,
                "event_count": len(events),
                "events": events,
                "events_path": f".newsroom/runs/{run_id}/events.jsonl",
            }
        )

    def replay_run(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "manifest": {"run_id": run_id, "status": "succeeded"},
                "manifest_path": f".newsroom/runs/{run_id}/manifest.json",
                "event_count": 1,
                "events": [{"event_type": "workflow_started", "payload": {}}],
                "events_path": f".newsroom/runs/{run_id}/events.jsonl",
                "events_error": None,
                "artifact_count": 1,
                "artifacts": [
                    {
                        "artifact_key": "report_json",
                        "relative_path": "report.json",
                        "content_type": "application/json",
                        "size_bytes": 14,
                        "content": {"title": "Report"},
                        "read_error": None,
                    }
                ],
            }
        )

    def get_run_diagnostics(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "diagnostics": {
                    "healthy": True,
                    "health_report": {"severity": "ok"},
                    "timeline_summary": {"event_count": 2},
                    "artifact_inventory": {"artifact_count": 12, "missing_count": 0},
                },
            }
        )

    def get_run_health(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "health": {
                    "severity": "ok",
                    "healthy": True,
                    "summary": "run completed",
                    "failed_steps": [],
                    "warnings": [],
                },
            }
        )

    def get_catalog_health(self):
        return _FakeResult(
            {
                "health": {
                    "severity": "ok",
                    "healthy": True,
                    "run_count": 1,
                    "failed_count": 0,
                    "paused_count": 0,
                    "latest_run_id": "run-1",
                    "warnings": [],
                }
            }
        )

    def compare_runs(self, base_run_id, target_run_id):
        return _FakeResult(
            {
                "base_run_id": base_run_id,
                "target_run_id": target_run_id,
                "comparison": {
                    "same_workflow": True,
                    "status_changed": False,
                    "workflow_version_changed": True,
                    "has_behavioral_change": True,
                },
            }
        )


class _FakeArtifactService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_artifacts(self, run_id):
        return _FakeResult(
            {
                "run_id": run_id,
                "artifact_count": 1,
                "artifacts": [
                    {
                        "artifact_key": "report_json",
                        "relative_path": "report.json",
                        "content_type": "application/json",
                        "size_bytes": 14,
                    }
                ],
            }
        )


class _MissingArtifactService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_artifacts(self, run_id):
        raise FileNotFoundError(f"run not found: {run_id}")


class _ArtifactPathArtifactService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_artifacts(self, run_id):
        raise ArtifactPathError("invalid artifact path")


class _InvalidArtifactService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def list_artifacts(self, run_id):
        raise ValueError("invalid artifact request")


class _ArtifactPathRunInspectionService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def get_run(self, run_id):
        raise ArtifactPathError("invalid artifact path")

    def get_run_events(self, run_id, *, limit=None):
        raise ArtifactPathError("invalid artifact path")

    def replay_run(self, run_id):
        raise ArtifactPathError("invalid artifact path")

    def get_run_diagnostics(self, run_id):
        raise ArtifactPathError("invalid artifact path")

    def get_run_health(self, run_id):
        raise ArtifactPathError("invalid artifact path")

    def compare_runs(self, base_run_id, target_run_id):
        raise ArtifactPathError("invalid artifact path")


class _ArtifactIntegrityRunInspectionService:
    def __init__(self, error) -> None:
        self.error = error

    def replay_run(self, run_id):
        raise self.error


class _UnavailableDerivedRunInspectionService:
    def replay_run(self, run_id):
        self._raise()

    def get_run_diagnostics(self, run_id):
        self._raise()

    def get_run_health(self, run_id):
        self._raise()

    def compare_runs(self, base_run_id, target_run_id):
        self._raise()

    @staticmethod
    def _raise():
        from framework.events.errors import EventStoreUnavailableError

        raise EventStoreUnavailableError(
            "database-host.internal durable event store unavailable"
        )


class _FakeRunOperationService:
    def __init__(self, artifact_root=".newsroom/runs") -> None:
        self.artifact_root = artifact_root

    def cancel_run(self, run_id, *, reason=None, actor_id=None, metadata=None):
        return _FakeResult(
            {
                "operation_id": "op-cancel",
                "operation_type": "cancel_run",
                "status": "accepted",
                "run_id": run_id,
                "message": "accepted",
                "new_run_id": None,
                "details": {
                    "reason": reason,
                    "actor_id": actor_id,
                    "metadata": metadata or {},
                },
            }
        )

    def rerun_from_step(self, run_id, *, step_id, actor_id=None, metadata=None):
        return _FakeResult(
            {
                "operation_id": "op-rerun",
                "operation_type": "rerun_from_step",
                "status": "accepted",
                "run_id": run_id,
                "message": "accepted",
                "new_run_id": "run-2",
                "details": {
                    "step_id": step_id,
                    "actor_id": actor_id,
                    "metadata": metadata or {},
                },
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


def _seed_durable_run_events(root) -> None:
    store = SQLiteEventStore(root / "_records" / "events.sqlite3")
    events = (
        ("workflow_started", {"profile": "live-offline"}),
        ("workflow_succeeded", {"path": ["write"]}),
    )
    for sequence, (event_type, payload) in enumerate(events, start=1):
        store.append_event(
            EventCandidate(
                event_id=f"evt-run-1-{sequence}",
                event_type=event_type,
                data_schema="newsroom.workflow-event/v1",
                source="io.newsroom.workflow.runtime",
                occurred_at=datetime(2026, 5, 14, 1, 0, sequence - 1, tzinfo=UTC),
                stream_id="run:run-1",
                business_context=BusinessContext(
                    run_id="run-1",
                    workflow_id="daily",
                ),
                producer=ProducerIdentity(
                    component="framework.workflow.runtime",
                    version="1",
                ),
                tenant_id="tenant-a",
                payload=payload,
            )
        )


def _write_replay_run(root) -> None:
    run_dir = root / "run-1"
    run_dir.mkdir()
    artifact_contents = {
        "events": (
            "events.jsonl",
            json.dumps({"event_type": "workflow_started", "payload": {"profile": "live"}})
            + "\n",
        ),
        "step_results": (
            "step_results.json",
            json.dumps({"write": {"status": "succeeded", "outputs": {"report": "ok"}}}),
        ),
        "report_json": (
            "report.json",
            json.dumps({"title": "Report", "password": "hidden"}),
        ),
        "report_markdown": ("report.md", "# Report\n"),
    }
    manifest = {
        "run_id": "run-1",
        "status": "succeeded",
        "artifacts": {
            artifact_key: relative_path
            for artifact_key, (relative_path, _) in artifact_contents.items()
        },
        "artifact_metadata": {
            artifact_key: {"checksum": sha256(content.encode("utf-8")).hexdigest()}
            for artifact_key, (_, content) in artifact_contents.items()
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative_path, content in artifact_contents.values():
        (run_dir / relative_path).write_bytes(content.encode("utf-8"))
