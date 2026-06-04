import json

from interfaces.cli import news as news_cli
from interfaces.cli.commands import schedules as schedule_commands


def test_news_cli_schedules_list_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(schedule_commands, "ScheduleApplicationService", _FakeScheduleService)

    exit_code = news_cli.main(["schedules", "list", "--enabled-only", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["schedule_count"] == 1
    assert _FakeScheduleService.last_instance.list_calls == [{"enabled_only": True}]


def test_news_cli_schedules_tick_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(schedule_commands, "ScheduleApplicationService", _FakeScheduleService)

    exit_code = news_cli.main(
        [
            "schedules",
            "tick",
            "--now",
            "2026-05-11T01:00:00Z",
            "--include-disabled",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    instance = _FakeScheduleService.last_instance
    assert exit_code == 0
    assert payload["evaluated_count"] == 1
    assert payload["enqueued_count"] == 1
    assert instance.tick_calls[0]["enabled_only"] is False
    assert instance.tick_calls[0]["now"].isoformat().replace("+00:00", "Z") == "2026-05-11T01:00:00Z"


def test_news_cli_schedules_run_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(schedule_commands, "ScheduleApplicationService", _FakeScheduleService)

    exit_code = news_cli.main(
        [
            "schedules",
            "run",
            "--now",
            "2026-05-11T01:00:00Z",
            "--max-idle-ticks",
            "1",
            "--tick-interval-seconds",
            "0",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    instance = _FakeScheduleService.last_instance
    assert exit_code == 0
    assert payload["stop_reason"] == "max_idle_ticks"
    assert instance.run_loop_calls[0]["max_idle_ticks"] == 1
    assert instance.run_loop_calls[0]["tick_interval_seconds"] == 0
    assert instance.run_loop_calls[0]["now"].isoformat().replace("+00:00", "Z") == "2026-05-11T01:00:00Z"


def test_news_cli_schedules_trigger_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(schedule_commands, "ScheduleApplicationService", _FakeScheduleService)

    exit_code = news_cli.main(
        [
            "schedules",
            "trigger",
            "manual-memory-reindex",
            "--now",
            "2026-05-11T01:05:00Z",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    instance = _FakeScheduleService.last_instance
    assert exit_code == 0
    assert payload["schedule_id"] == "manual-memory-reindex"
    assert instance.trigger_calls[0]["schedule_id"] == "manual-memory-reindex"
    assert instance.trigger_calls[0]["now"].isoformat().replace("+00:00", "Z") == "2026-05-11T01:05:00Z"


class _FakeScheduleService:
    last_instance = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.list_calls = []
        self.tick_calls = []
        self.trigger_calls = []
        self.run_loop_calls = []
        _FakeScheduleService.last_instance = self

    def list_schedules(self, *, enabled_only=False):
        self.list_calls.append({"enabled_only": enabled_only})
        return _Result(
            {
                "schedule_count": 1,
                "schedules": [
                    {
                        "spec": {
                            "schedule_id": "daily",
                            "trigger_type": "interval",
                            "enabled": True,
                            "task_type": "memory.reindex",
                            "queue_name": "news:queue:memory",
                        }
                    }
                ],
            }
        )

    def tick(self, *, now=None, enabled_only=True):
        self.tick_calls.append({"now": now, "enabled_only": enabled_only})
        return _Result(
            {
                "evaluated_count": 1,
                "enqueued_count": 1,
                "evaluations": [],
                "enqueued": [],
                "state_updates": {"daily": "2026-05-11T01:00:00Z"},
                "updated_schedules": [],
            }
        )

    def run_loop(self, **kwargs):
        self.run_loop_calls.append(kwargs)
        return _Result(
            {
                "tick_count": 1,
                "enqueued_count": 0,
                "idle_tick_count": 1,
                "stop_reason": "max_idle_ticks",
                "last_tick": {},
            }
        )

    def trigger_manual(self, schedule_id, *, now=None):
        self.trigger_calls.append({"schedule_id": schedule_id, "now": now})
        return _Result(
            {
                "schedule_id": schedule_id,
                "enqueued": {
                    "message_id": "msg-1",
                    "task": {
                        "task_id": "task-1",
                        "status": "queued",
                    },
                },
                "updated_schedule": {},
            }
        )


class _Result:
    def __init__(self, payload) -> None:
        self.payload = payload

    def to_dict(self):
        return self.payload
