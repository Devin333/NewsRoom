from __future__ import annotations

import json

import interfaces.cli.news as news_cli
from framework.specs import WorkflowStatus


def test_cli_run_daily_uses_facade_compat_path(monkeypatch, tmp_path, capsys) -> None:
    calls = []

    class FakeRunApplicationService:
        def __init__(self, artifact_root):
            self.artifact_root = artifact_root

        def run_daily(self, **kwargs):
            calls.append({"artifact_root": self.artifact_root, **kwargs})
            return _FakeRunResult(kwargs["run_id"])

    monkeypatch.setattr(news_cli, "RunApplicationService", FakeRunApplicationService)

    exit_code = news_cli.main(
        [
            "run",
            "daily",
            "--profile",
            "live-offline",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--json",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == "run-1"
    assert calls == [
        {
            "artifact_root": str(tmp_path),
            "profile": "live-offline",
            "topic": "AI",
            "source_limit": 3,
            "run_id": "run-1",
        }
    ]


class _FakeRunResult:
    status = WorkflowStatus.SUCCEEDED
    output = {}
    error = None
    artifact_dir = ".newsroom/runs/run-1"
    manifest_path = ".newsroom/runs/run-1/manifest.json"
    events_path = ".newsroom/runs/run-1/events.jsonl"

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def to_dict(self):
        return {"run_id": self.run_id, "status": self.status.value, "output": {}}
