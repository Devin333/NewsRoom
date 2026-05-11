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


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
