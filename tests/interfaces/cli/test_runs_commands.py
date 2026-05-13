import json

import interfaces.cli.news as news_cli


def test_news_cli_runs_list_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "list", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_count"] == 1
    assert payload["runs"][0]["run_id"] == "run-1"


def test_news_cli_runs_show_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "show", "run-1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["manifest"]["status"] == "succeeded"


def test_news_cli_runs_events_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "events", "run-1", "--limit", "1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["event_count"] == 1
    assert payload["events"][0]["event_type"] == "workflow_started"


def test_news_cli_runs_events_invalid_limit_returns_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "events", "run-1", "--limit", "0", "--json"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "limit must be greater than zero" in captured.out


def test_news_cli_runs_replay_json_reads_real_files(tmp_path, capsys) -> None:
    _write_replay_run(tmp_path)

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
    assert payload["event_count"] == 1
    assert artifacts["report_json"]["content"]["password"] == "[redacted]"


def test_news_cli_runs_replay_text_reads_real_files(tmp_path, capsys) -> None:
    _write_replay_run(tmp_path)

    exit_code = news_cli.main(["runs", "replay", "run-1", "--artifact-root", str(tmp_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "run_id=run-1" in captured.out
    assert "artifact_count=3" in captured.out
    assert "- report_json path=report.json" in captured.out


def test_news_cli_runs_diagnostics_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "diagnostics", "run-1", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["run_id"] == "run-1"
    assert payload["diagnostics"]["healthy"] is True


def test_news_cli_runs_health_text(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "health", "run-1"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "severity=ok" in captured.out
    assert "healthy=true" in captured.out


def test_news_cli_runs_catalog_health_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "catalog-health", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["health"]["severity"] == "ok"
    assert payload["health"]["run_count"] == 1


def test_news_cli_runs_compare_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "RunInspectionService", _FakeRunInspectionService)

    exit_code = news_cli.main(["runs", "compare", "run-1", "run-2", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["base_run_id"] == "run-1"
    assert payload["target_run_id"] == "run-2"
    assert payload["comparison"]["same_workflow"] is True


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


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


def _write_replay_run(root) -> None:
    run_dir = root / "run-1"
    run_dir.mkdir()
    manifest = {
        "run_id": "run-1",
        "status": "succeeded",
        "artifacts": {
            "events": "events.jsonl",
            "report_json": "report.json",
            "report_markdown": "report.md",
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "workflow_started", "payload": {"profile": "live"}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Report", "password": "hidden"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
