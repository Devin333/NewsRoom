from __future__ import annotations

from pathlib import Path
from typing import Callable

from business.layers.memory.ingestion import MemoryIngestionService
from framework import RunResult
from framework.specs import WorkflowStatus

from interfaces.services.run_persistence_service import RunPersistenceApplicationService


class DailyRunApplicationService:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        persistence_service: RunPersistenceApplicationService,
        memory_ingestion_service: MemoryIngestionService | None = None,
        memory_ingestion_service_factory: Callable[[], MemoryIngestionService | None] | None = None,
        board_service_factory: Callable[[], object] | None = None,
        runner_cls_resolver: Callable[[str], Callable] | None = None,
        agentic_runner_cls: Callable | None = None,
        test_no_llm_runner: Callable | None = None,
        test_agent_loop_runner: Callable | None = None,
    ) -> None:
        self.artifact_root = Path(artifact_root)
        self.persistence_service = persistence_service
        self.memory_ingestion_service = memory_ingestion_service
        self.memory_ingestion_service_factory = memory_ingestion_service_factory
        self.board_service_factory = board_service_factory
        self.runner_cls_resolver = runner_cls_resolver
        self.agentic_runner_cls = agentic_runner_cls
        self.test_no_llm_runner = test_no_llm_runner
        self.test_agent_loop_runner = test_agent_loop_runner

    def run_test_no_llm(self, *, topic: str, run_id: str | None = None) -> RunResult:
        if self.test_no_llm_runner is None:
            raise RuntimeError("test_no_llm_runner is not configured")
        return self.test_no_llm_runner(
            artifact_root=self.artifact_root,
            request={"topic": topic},
            run_id=run_id,
        )

    def run_test_agent_loop(self, *, topic: str, run_id: str | None = None) -> RunResult:
        if self.test_agent_loop_runner is None:
            raise RuntimeError("test_agent_loop_runner is not configured")
        return self.test_agent_loop_runner(
            artifact_root=self.artifact_root,
            request={"topic": topic},
            run_id=run_id,
        )

    def run_daily(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None = None,
    ) -> RunResult:
        if self.runner_cls_resolver is None:
            raise RuntimeError("runner_cls_resolver is not configured")
        return self._run_daily_with_runner(
            runner_cls=self.runner_cls_resolver(profile),
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )

    def run_daily_agentic(
        self,
        *,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None = None,
    ) -> RunResult:
        if self.agentic_runner_cls is None:
            raise RuntimeError("agentic_runner_cls is not configured")
        return self._run_daily_with_runner(
            runner_cls=self.agentic_runner_cls,
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )

    def _run_daily_with_runner(
        self,
        *,
        runner_cls: Callable,
        profile: str,
        topic: str,
        source_limit: int,
        run_id: str | None,
    ) -> RunResult:
        repository = self.persistence_service.prepare_repository()
        result = runner_cls(artifact_root=self.artifact_root).run(
            profile=profile,
            topic=topic,
            source_limit=source_limit,
            run_id=run_id,
        )
        self.persistence_service.persist_prepared_result(repository, result, profile=profile)
        self._attach_board_outputs_if_possible(result, topic=topic)
        self._index_memory_if_configured(result, topic=topic)
        return result

    def _index_memory_if_configured(self, result: RunResult, *, topic: str) -> None:
        memory_service = self.memory_ingestion_service
        if memory_service is None and self.memory_ingestion_service_factory is not None:
            memory_service = self.memory_ingestion_service_factory()
        if memory_service is None:
            return
        ingestion_result = memory_service.ingest_run_output(
            result.output,
            run_id=result.run_id,
            report_id=f"{result.run_id}:final",
            topic=topic,
        )
        result.output["memory_ingestion_result"] = ingestion_result.to_dict()

    def _attach_board_outputs_if_possible(self, result: RunResult, *, topic: str) -> None:
        if result.status != WorkflowStatus.SUCCEEDED:
            return
        if not isinstance(result.output, dict):
            return
        if self.board_service_factory is None:
            return
        try:
            self.board_service_factory().attach_run_board_outputs(result.output, topic=topic)
        except (TypeError, ValueError):
            return


__all__ = ["DailyRunApplicationService"]
