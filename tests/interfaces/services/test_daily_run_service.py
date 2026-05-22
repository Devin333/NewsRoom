from __future__ import annotations

from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.daily_run_service import DailyRunApplicationService


def test_daily_run_service_migrates_runs_persists_and_indexes_memory(tmp_path) -> None:
    order = []
    persistence = _Persistence(order)
    memory = _Memory()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=persistence,
        memory_ingestion_service=memory,
        board_service_factory=lambda: _Board(order),
        runner_cls_resolver=lambda profile: lambda artifact_root: _Runner(order),
    )

    result = service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert result.run_id == "run-1"
    assert result.output["memory_ingestion_result"]["documents_indexed"] == 1
    assert order == ["migrate", "run", "persist", "board"]


class _Persistence:
    def __init__(self, order):
        self.order = order

    def prepare_repository(self):
        self.order.append("migrate")
        return object()

    def persist_prepared_result(self, repository, result, *, profile):
        self.order.append("persist")


class _Runner:
    def __init__(self, order):
        self.order = order

    def run(self, *, profile, topic, source_limit, run_id=None):
        self.order.append("run")
        return RunResult(
            run_id=run_id or "generated",
            workflow_id="daily",
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={},
        )


class _Memory:
    def ingest_run_output(self, output, *, run_id, report_id, topic):
        return _Payload({"documents_indexed": 1})


class _Board:
    def __init__(self, order):
        self.order = order

    def attach_run_board_outputs(self, output, *, topic):
        self.order.append("board")


class _Payload:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload
