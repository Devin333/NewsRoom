from __future__ import annotations

import interfaces.services.run_service as run_service_module
from interfaces.services.run_service import RunApplicationService


def test_run_service_facade_delegates_daily(monkeypatch, tmp_path) -> None:
    calls = []

    class FakeDailyService:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs["artifact_root"]))

        def run_daily(self, **kwargs):
            calls.append(("run_daily", kwargs))
            return "daily-result"

    monkeypatch.setattr(run_service_module, "DailyRunApplicationService", FakeDailyService)

    result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert result == "daily-result"
    assert calls[0] == ("init", tmp_path)
    assert calls[1] == (
        "run_daily",
        {"profile": "live-offline", "topic": "AI", "source_limit": 1, "run_id": "run-1"},
    )
