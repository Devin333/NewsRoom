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
    _FakeWorkerService.run_once_calls = []
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
    assert payload["reclaimed"] is False
    assert _FakeWorkerService.run_once_calls[-1]["reclaim_stale_ms"] is None


def test_news_cli_worker_run_once_reclaim_stale_json(monkeypatch, capsys) -> None:
    _FakeWorkerService.run_once_calls = []
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "run-once",
            "--worker-id",
            "worker-1",
            "--block-ms",
            "10",
            "--reclaim-stale-ms",
            "60000",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["processed"] is True
    assert payload["reclaimed"] is True
    assert _FakeWorkerService.run_once_calls[-1]["reclaim_stale_ms"] == 60000


def test_news_cli_worker_run_json(monkeypatch, capsys) -> None:
    _FakeWorkerService.run_loop_calls = []
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "run",
            "--worker-id",
            "worker-1",
            "--max-idle-polls",
            "1",
            "--idle-sleep-seconds",
            "0",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["stop_reason"] == "max_idle_polls"
    assert _FakeWorkerService.run_loop_calls[-1]["max_idle_polls"] == 1
    assert _FakeWorkerService.run_loop_calls[-1]["idle_sleep_seconds"] == 0


def test_news_cli_worker_heartbeat_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "heartbeat",
            "--worker-id",
            "worker-1",
            "--queue-name",
            "news:queue:daily",
            "--current-task-id",
            "task-1",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["worker"]["worker_id"] == "worker-1"
    assert payload["worker"]["status"] == "running"
    assert payload["worker"]["current_task_id"] == "task-1"


def test_news_cli_worker_status_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "status",
            "--worker-id",
            "worker-1",
            "--stale-after-seconds",
            "30",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["worker_count"] == 1
    assert payload["workers"][0]["worker_id"] == "worker-1"
    assert payload["stale_after_seconds"] == 30


def test_news_cli_worker_queues_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(news_cli, "WorkerApplicationService", _FakeWorkerService)

    exit_code = news_cli.main(
        [
            "worker",
            "queues",
            "--queue-name",
            "news:queue:daily",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["queue_count"] == 1
    assert payload["queues"][0]["queue_name"] == "news:queue:daily"
    assert payload["queues"][0]["pending_count"] == 2


class _FakeWorkerService:
    run_once_calls = []
    run_loop_calls = []

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
        self.__class__.run_once_calls.append(kwargs)
        return _FakeRunOnceResult(reclaimed=kwargs.get("reclaim_stale_ms") is not None)

    def run_loop(self, **kwargs):
        self.__class__.run_loop_calls.append(kwargs)
        return _FakeLoopResult()

    def record_heartbeat(self, **kwargs):
        return _FakeResult(
            {
                "worker": {
                    "worker_id": kwargs["worker_id"],
                    "queue_names": kwargs["queue_names"],
                    "status": kwargs["status"],
                    "stored_status": kwargs["status"],
                    "stale": False,
                    "started_at": "2026-05-11T00:00:00Z",
                    "last_heartbeat_at": "2026-05-11T00:00:00Z",
                    "current_task_id": kwargs["current_task_id"],
                    "processed_count": 0,
                    "failed_count": 0,
                    "metadata": {},
                }
            }
        )

    def list_worker_status(self, **kwargs):
        return _FakeResult(
            {
                "worker_id": kwargs["worker_id"],
                "worker_count": 1,
                "unhealthy_count": 0,
                "stale_after_seconds": kwargs["stale_after_seconds"],
                "workers": [
                    {
                        "worker_id": "worker-1",
                        "queue_names": ["news:queue:daily"],
                        "status": "running",
                        "stored_status": "running",
                        "stale": False,
                        "started_at": "2026-05-11T00:00:00Z",
                        "last_heartbeat_at": "2026-05-11T00:00:00Z",
                        "current_task_id": None,
                        "processed_count": 1,
                        "failed_count": 0,
                        "metadata": {},
                    }
                ],
            }
        )

    def queue_status(self, **kwargs):
        return _FakeResult(
            {
                "queue_count": len(kwargs["queue_names"]),
                "total_stream_length": 3,
                "total_pending_count": 2,
                "queues": [
                    {
                        "queue_name": queue_name,
                        "stream_length": 3,
                        "group_name": "news-workers",
                        "group_exists": True,
                        "pending_count": 2,
                        "consumer_count": 1,
                        "consumers": [{"consumer_name": "worker-1", "pending_count": 2}],
                    }
                    for queue_name in kwargs["queue_names"]
                ],
            }
        )


class _FakeResult:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload


class _FakeRunOnceResult:
    success = True

    def __init__(self, *, reclaimed=False) -> None:
        self.reclaimed = reclaimed

    def to_dict(self):
        return {
            "processed": True,
            "worker_id": "worker-1",
            "reclaimed": self.reclaimed,
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


class _FakeLoopResult:
    def to_dict(self):
        return {
            "worker_id": "worker-1",
            "iterations": 1,
            "processed_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "idle_count": 1,
            "stop_reason": "max_idle_polls",
            "last_result": {
                "processed": False,
                "worker_id": "worker-1",
                "reclaimed": False,
                "queue_name": None,
                "message_id": None,
                "task_id": None,
                "task_type": None,
                "success": None,
                "task_status": None,
                "workflow_run_id": None,
                "error_type": None,
                "error_message": None,
            },
        }
