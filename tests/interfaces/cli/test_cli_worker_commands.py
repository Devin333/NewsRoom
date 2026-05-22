from __future__ import annotations

import json

import interfaces.cli.news as news_cli
from interfaces.cli.commands import workers as worker_commands


def test_cli_worker_and_workers_alias_use_worker_service(monkeypatch, capsys) -> None:
    calls = []

    class FakeWorkerService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def list_worker_status(self, **kwargs):
            calls.append(kwargs)
            return _FakeResult(
                {
                    "worker_count": 0,
                    "workers": [],
                    "stale_after_seconds": kwargs["stale_after_seconds"],
                }
            )

    monkeypatch.setattr(worker_commands, "WorkerApplicationService", FakeWorkerService)

    assert news_cli.main(["worker", "status", "--stale-after-seconds", "5", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stale_after_seconds"] == 5
    assert news_cli.main(["workers", "status", "--stale-after-seconds", "7", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stale_after_seconds"] == 7
    assert calls[0]["stale_after_seconds"] == 5
    assert calls[1]["stale_after_seconds"] == 7


class _FakeResult:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload
