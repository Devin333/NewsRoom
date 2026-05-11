import json

import interfaces.cli.news as news_cli


def test_news_cli_worker_enqueue_daily_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "enqueue-daily",
            "--profile",
            "live-offline",
            "--topic",
            "AI policy",
            "--source-limit",
            "2",
            "--run-id",
            "queued-run",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["task_id"] == "task-1"
    assert payload["queue_name"] == "news:queue:daily"
    assert payload["topic"] == "AI policy"


def test_news_cli_worker_enqueue_memory_reindex_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "enqueue-memory-reindex",
            "--run-id",
            "run-1",
            "--topic",
            "AI policy",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["task_id"] == "task-1"
    assert payload["task_type"] == "memory.reindex"
    assert payload["queue_name"] == "news:queue:memory"
    assert payload["run_id"] == "run-1"
    assert payload["topic"] == "AI policy"


def test_news_cli_worker_run_once_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "run-once",
            "--worker-id",
            "worker-1",
            "--block-ms",
            "10",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["processed"] is True
    assert payload["task_id"] == "task-1"
    assert payload["workflow_run_id"] == "workflow-1"


class _FakeWorkerService:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def enqueue_daily(self, **kwargs):
        return _FakeResult(
            {
                "message_id": "1-0",
                "task_id": "task-1",
                "task_type": "daily_intelligence.run",
                "queue_name": kwargs["queue_name"],
                "status": "queued",
                "profile": kwargs["profile"],
                "topic": kwargs["topic"],
                "source_limit": kwargs["source_limit"],
                "run_id": kwargs["run_id"],
            }
        )

    def enqueue_memory_reindex(self, **kwargs):
        return _FakeResult(
            {
                "message_id": "1-0",
                "task_id": "task-1",
                "task_type": "memory.reindex",
                "queue_name": kwargs["queue_name"],
                "status": "queued",
                "profile": None,
                "topic": kwargs["topic"],
                "source_limit": None,
                "run_id": kwargs["run_id"],
            }
        )

    def run_once(self, **kwargs):
        return _FakeRunOnceResult()


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeRunOnceResult:
    success = True

    def to_dict(self):
        return {
            "processed": True,
            "worker_id": "worker-1",
            "queue_name": "news:queue:daily",
            "message_id": "1-0",
            "task_id": "task-1",
            "task_type": "daily_intelligence.run",
            "success": True,
            "task_status": "succeeded",
            "workflow_run_id": "workflow-1",
            "error_type": None,
            "error_message": None,
        }
