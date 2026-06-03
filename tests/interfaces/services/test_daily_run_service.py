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


def test_daily_run_service_projects_namespaced_output_for_service_consumers(tmp_path) -> None:
    persistence = _CapturingPersistence()
    memory = _CapturingMemory()
    board = _CapturingBoard()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=persistence,
        memory_ingestion_service=memory,
        board_service_factory=lambda: board,
        runner_cls_resolver=lambda profile: lambda artifact_root: _NamespacedRunner(),
    )

    result = service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert result.output["final_report"] == {"title": "Namespaced report", "sections": []}
    assert result.output["quality_result"] == {"decision": "pass", "route": "final"}
    assert persistence.persisted_input.final_report == result.output["final_report"]
    assert persistence.persisted_input.quality_result == result.output["quality_result"]
    assert persistence.persisted_input.evidence_bundle == {"items": []}
    assert memory.output["final_report"] == result.output["final_report"]
    assert memory.output["quality_result"] == result.output["quality_result"]
    assert memory.output == {
        "final_report": result.output["final_report"],
        "evidence_bundle": {"items": []},
        "quality_result": result.output["quality_result"],
    }
    assert board.output["ranked_items"] == [{"title": "Namespaced item"}]
    assert result.output["ranked_items"] == [{"title": "Namespaced item"}]
    assert result.output["board_outputs"] == {"ai_news": {"cards": []}}
    assert result.output["cross_board_output"] == {"board_type": "cross_board"}


def test_daily_run_service_does_not_expose_internal_daily_aliases(tmp_path) -> None:
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=_CapturingPersistence(),
        runner_cls_resolver=lambda profile: lambda artifact_root: _NamespacedRunner(),
    )

    result = service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert result.output["final_report"] == {"title": "Namespaced report", "sections": []}
    assert result.output["quality_result"] == {"decision": "pass", "route": "final"}
    assert "agent_feedback_summary" not in result.output
    assert "writer_agent_loop_metrics" not in result.output
    assert "source_pipeline_metrics" not in result.output


def test_daily_run_service_memory_ingestion_ignores_legacy_only_daily_outputs(tmp_path) -> None:
    memory = _CapturingMemory()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=_CapturingPersistence(),
        memory_ingestion_service=memory,
        runner_cls_resolver=lambda profile: lambda artifact_root: _LegacyOnlyRunner(),
    )

    result = service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert memory.output == {}
    assert result.output["final_report"] == {"title": "Legacy report", "sections": []}
    assert result.output["memory_ingestion_result"]["documents_indexed"] == 1


def test_daily_run_service_board_attachment_ignores_legacy_only_daily_outputs(tmp_path) -> None:
    board = _CapturingBoard()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=_CapturingPersistence(),
        board_service_factory=lambda: board,
        runner_cls_resolver=lambda profile: lambda artifact_root: _LegacyOnlyRunner(),
    )

    result = service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert board.output == {}
    assert result.output["ranked_items"] == [{"title": "Legacy item"}]
    assert "board_outputs" not in result.output
    assert "cross_board_output" not in result.output


def test_daily_run_service_persistence_input_ignores_legacy_only_daily_outputs(tmp_path) -> None:
    persistence = _CapturingPersistence()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=persistence,
        runner_cls_resolver=lambda profile: lambda artifact_root: _LegacyOnlyRunner(),
    )

    service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert persistence.persisted_input.final_report is None
    assert persistence.persisted_input.evidence_bundle is None
    assert persistence.persisted_input.quality_result is None


def test_daily_run_service_falls_back_to_projected_result_when_input_writer_is_unconfigured(
    tmp_path,
) -> None:
    persistence = _InputMethodWithoutWriterPersistence()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=persistence,
        runner_cls_resolver=lambda profile: lambda artifact_root: _NamespacedRunner(),
    )

    service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert persistence.persisted_output["final_report"] == {
        "title": "Namespaced report",
        "sections": [],
    }
    assert persistence.persisted_output["evidence_bundle"] == {"items": []}


def test_daily_run_service_persistence_result_fallback_ignores_legacy_only_daily_outputs(
    tmp_path,
) -> None:
    persistence = _InputMethodWithoutWriterPersistence()
    service = DailyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=persistence,
        runner_cls_resolver=lambda profile: lambda artifact_root: _LegacyOnlyRunner(),
    )

    service.run_daily(
        profile="live-offline",
        topic="AI",
        source_limit=1,
        run_id="run-1",
    )

    assert persistence.persisted_output == {}


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


class _NamespacedRunner:
    def run(self, *, profile, topic, source_limit, run_id=None):
        return RunResult(
            run_id=run_id or "generated",
            workflow_id="daily",
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={
                "report.final": {"title": "Namespaced report", "sections": []},
                "evidence.bundle": {"items": []},
                "quality.result": {"decision": "pass", "route": "final"},
                "sources.ranked_items": [{"title": "Namespaced item"}],
                "agent.feedback.summary": {"event_count": 1},
                "agent.writer.loop.metrics": {"llm_calls": 3},
                "sources.pipeline_metrics": {"raw_items_count": 1},
            },
        )


class _LegacyOnlyRunner:
    def run(self, *, profile, topic, source_limit, run_id=None):
        return RunResult(
            run_id=run_id or "generated",
            workflow_id="daily",
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={
                "final_report": {"title": "Legacy report", "sections": []},
                "evidence_bundle": {"items": []},
                "quality_result": {"decision": "pass", "route": "final"},
                "ranked_items": [{"title": "Legacy item"}],
            },
        )


class _Memory:
    def ingest_run_output(self, output, *, run_id, report_id, topic):
        return _Payload({"documents_indexed": 1})


class _CapturingMemory:
    def __init__(self):
        self.output = {}

    def ingest_run_output(self, output, *, run_id, report_id, topic):
        self.output = dict(output)
        return _Payload({"documents_indexed": 1})


class _Board:
    def __init__(self, order):
        self.order = order

    def attach_run_board_outputs(self, output, *, topic):
        self.order.append("board")


class _CapturingBoard:
    def __init__(self):
        self.output = {}

    def attach_run_board_outputs(self, output, *, topic):
        self.output = dict(output)
        if "ranked_items" not in output:
            return
        output["ranked_items"] = [{"title": "board-mutated item"}]
        output["board_outputs"] = {"ai_news": {"cards": []}}
        output["cross_board_output"] = {"board_type": "cross_board"}


class _CapturingPersistence:
    def __init__(self):
        self.persisted_input = None

    def prepare_repository(self):
        return object()

    def persist_prepared_input(self, repository, input_model):
        self.persisted_input = input_model

    def persist_prepared_result(self, repository, result, *, profile):
        raise AssertionError("namespaced daily output should persist via RunPersistenceInput")


class _InputMethodWithoutWriterPersistence:
    persist_input = None

    def __init__(self):
        self.persisted_output = {}

    def prepare_repository(self):
        return object()

    def persist_prepared_input(self, repository, input_model):
        raise AssertionError("unconfigured input persistence should use result fallback")

    def persist_prepared_result(self, repository, result, *, profile):
        self.persisted_output = dict(result.output)


class _Payload:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload
