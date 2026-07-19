from __future__ import annotations

import ast
from pathlib import Path

import pytest

from business.research.application import (
    AnalyzePaperRequest,
    AnalyzePaperUseCase,
    AskPaperUseCase,
)
from business.research.application.single_paper_runtime import (
    ResearchAnalysisResult,
    ResearchSinglePaperRuntime,
)
from business.research.ports.run_store import (
    ResearchRunStoreConflictError,
    ResearchRunStoreReason,
    ResearchRunStoreUnavailableError,
)
from interfaces.services.research_service import (
    InMemoryResearchRunStore,
    ResearchActorAuthorizationError,
    ResearchActorInput,
    ResearchAnalyzeInput,
    ResearchApplicationService,
    ResearchAskInput,
    ResearchRunRecord,
    ResearchServiceError,
    bind_research_actor_input,
)
from framework.harness import FakeArtifactPort, InMemoryHarnessEventPort
from infrastructure.research.filesystem_run_store import FilesystemResearchRunStore
from interfaces.models import ActorContext
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)
from tests.interfaces.research_fixtures import FakeAnalyzeUseCase, make_research_result


def test_research_service_analyze_calls_research_application_and_stores_result() -> None:
    use_case = FakeAnalyzeUseCase()
    store = InMemoryResearchRunStore()
    service = ResearchApplicationService(analyze_use_case=use_case, run_store=store)

    response = service.analyze_paper(
        ResearchAnalyzeInput(
            paper_id="paper-1",
            source_url="https://arxiv.org/abs/2606.00001",
            run_id="research-run-1",
            user_id="user-1",
            metadata={"source": "arxiv"},
            options={"max_turns": 8},
            tenant_id="tenant-a",
            memory_namespace="research:tenant:tenant-a:user:user-1",
        )
    )

    assert response["runId"] == "research-run-1"
    assert response["paperId"] == "paper-1"
    assert response["analysisRef"] == "artifact://research-run-1/analysis"
    assert use_case.calls[0].source_ref == "https://arxiv.org/abs/2606.00001"
    assert use_case.calls[0].tenant_id == "tenant-a"
    assert use_case.calls[0].user_id == "user-1"
    assert (
        use_case.calls[0].memory_namespace
        == "research:tenant:tenant-a:user:user-1"
    )
    assert use_case.calls[0].options["metadata"] == {"source": "arxiv"}
    assert store.get_latest_by_paper_id("paper-1") is not None


def test_research_service_reader_and_analysis_return_research_payloads() -> None:
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    analysis = service.get_analysis("paper-1")
    reader = service.get_reader("paper-1")

    assert analysis["analysis"]["summary"]["core_idea"] == "Separate Harness routing from LLM candidate generation."
    assert reader["paper"]["paper_id"] == "paper-1"
    assert reader["document"]["sections"][0]["section_id"] == "sec-intro"
    assert reader["metadata"]["readerPayloadRef"] == "artifact://research-run-1/reader"


def test_research_service_ask_returns_grounded_evidence_refs() -> None:
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    answer = service.ask_paper(
        "paper-1",
        ResearchAskInput(question="What is the method?", selection={"sourceRefs": ["paper://paper-1/sec-intro"]}),
    )

    assert answer["answer"] == "A controlled PLAN EXECUTE VERIFY runtime."
    assert "paper://paper-1/sec-intro" in answer["evidenceRefs"]
    assert answer["traceRef"] == "harness-trace://research-run-1"


def test_research_service_dispatches_chunk_rag_mode_without_run_store_lookup() -> None:
    rag_ask_use_case = _CapturingRagAskUseCase()
    service = ResearchApplicationService(rag_ask_use_case=rag_ask_use_case)

    response = service.ask_paper(
        "paper-1",
        ResearchAskInput(
            question="What is the method?",
            mode="chunk_rag",
            section_index=2,
            limit=7,
            generate=True,
            gated=True,
            tenant_id="tenant-a",
            user_id="user-1",
        ),
    )

    assert response == {"mode": "chunk_rag", "paper_id": "paper-1"}
    assert rag_ask_use_case.calls == [
        (
            "paper-1",
            "What is the method?",
            {
                "section_index": 2,
                "limit": 7,
                "generate": True,
                "gated": True,
                "tenant_id": "tenant-a",
                "user_id": "user-1",
                "memory_namespace": "research:tenant:tenant-a:user:user-1",
            },
        )
    ]


@pytest.mark.parametrize(
    ("ask_input", "message"),
    [
        (ResearchAskInput(question="question", mode="unknown"), "mode must be"),
        (
            ResearchAskInput(question="question", mode="chunk_rag", section_index=-1),
            "sectionIndex must be",
        ),
        (
            ResearchAskInput(question="question", mode="chunk_rag", limit=21),
            "limit must be",
        ),
    ],
)
def test_research_service_rejects_invalid_ask_mode_or_chunk_bounds(
    ask_input: ResearchAskInput,
    message: str,
) -> None:
    service = ResearchApplicationService(rag_ask_use_case=_CapturingRagAskUseCase())

    with pytest.raises(ResearchServiceError, match=message) as failed:
        service.ask_paper("paper-1", ask_input)

    assert failed.value.code == "invalid_request"
    assert failed.value.status_code == 400


def test_research_service_ask_propagates_canonical_actor_scope() -> None:
    ask_use_case = _CapturingAskPaperUseCase()
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        ask_use_case=ask_use_case,
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(
        ResearchAnalyzeInput(
            paper_id="paper-1",
            source_url="https://arxiv.org/abs/2606.00001",
        )
    )

    service.ask_paper(
        "paper-1",
        ResearchAskInput(
            question="What is the method?",
            tenant_id="tenant-a",
            user_id="user-1",
            memory_namespace="research:tenant:tenant-a:user:user-1",
        ),
    )

    goal = ask_use_case.goals[0]
    assert goal.allowed_memory_namespaces == [
        "research:tenant:tenant-a:user:user-1"
    ]
    assert goal.metadata["tenant_id"] == "tenant-a"
    assert goal.metadata["user_id"] == "user-1"
    assert goal.metadata["memory_namespace"] == goal.allowed_memory_namespaces[0]


def test_research_service_rejects_tenant_namespace_without_tenant_actor() -> None:
    service = ResearchApplicationService(run_store=InMemoryResearchRunStore())

    with pytest.raises(ResearchServiceError) as failed:
        service.ask_paper(
            "paper-1",
            ResearchAskInput(
                question="What is the method?",
                memory_namespace="research:tenant:tenant-a:public",
            ),
        )

    assert failed.value.code == "invalid_request"
    assert failed.value.status_code == 400


def test_authenticated_actor_scope_overrides_or_rejects_requested_scope() -> None:
    actor = ActorContext(
        actor_id="service-a",
        actor_type="service",
        roles=["service"],
        request_id="request-1",
        metadata={"tenant_id": "tenant-a"},
    )

    implicit = bind_research_actor_input(ResearchActorInput(), actor)
    matching = bind_research_actor_input(
        ResearchActorInput(
            tenant_id="tenant-a",
            memory_namespace="research:tenant:tenant-a:public",
        ),
        actor,
    )

    assert implicit == ResearchActorInput(
        tenant_id="tenant-a",
        memory_namespace="research:tenant:tenant-a:public",
    )
    assert matching == implicit
    with pytest.raises(ResearchActorAuthorizationError) as forbidden:
        bind_research_actor_input(
            ResearchActorInput(tenant_id="tenant-b"),
            actor,
        )
    assert forbidden.value.status_code == 403
    assert forbidden.value.code == "forbidden"


def test_research_service_ask_preserves_options_user_id_compatibility() -> None:
    ask_use_case = _CapturingAskPaperUseCase()
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        ask_use_case=ask_use_case,
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(
        ResearchAnalyzeInput(
            paper_id="paper-1",
            source_url="https://arxiv.org/abs/2606.00001",
        )
    )

    service.ask_paper(
        "paper-1",
        ResearchAskInput(
            question="What is the method?",
            options={"userId": "legacy-user"},
        ),
    )

    assert ask_use_case.goals[0].allowed_memory_namespaces == [
        "research:user:legacy-user"
    ]


def test_research_service_does_not_expose_tenant_run_without_tenant_actor() -> None:
    result = make_research_result()
    result.trace["metadata"] = {
        "tenant_id": "tenant-a",
        "user_id": "user-1",
        "memory_namespace": "research:tenant:tenant-a:user:user-1",
    }
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(result),
        run_store=InMemoryResearchRunStore(),
    )
    service.analyze_paper(
        ResearchAnalyzeInput(
            paper_id="paper-1",
            source_url="https://arxiv.org/abs/2606.00001",
            tenant_id="tenant-a",
            user_id="user-1",
        )
    )

    with pytest.raises(ResearchServiceError) as hidden:
        service.ask_paper(
            "paper-1",
            ResearchAskInput(question="What is the method?"),
        )

    assert hidden.value.code == "paper_not_found"
    allowed = service.ask_paper(
        "paper-1",
        ResearchAskInput(
            question="What is the method?",
            tenant_id="tenant-a",
            user_id="user-1",
        ),
    )
    assert allowed["evidenceRefs"]


def test_research_queries_select_latest_record_visible_to_actor() -> None:
    store = InMemoryResearchRunStore()
    for run_id, tenant_id, user_id in (
        ("run-tenant-a", "tenant-a", "user-a"),
        ("run-tenant-b", "tenant-b", "user-b"),
    ):
        result = make_research_result(run_id=run_id, paper_id="paper-1")
        result.trace["metadata"] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "memory_namespace": f"research:tenant:{tenant_id}:user:{user_id}",
        }
        store.save(
            ResearchRunRecord(
                run_id=run_id,
                paper_id="paper-1",
                result=result,
            )
        )
    service = ResearchApplicationService(run_store=store)
    actor_a = ResearchActorInput(
        tenant_id="tenant-a",
        user_id="user-a",
        memory_namespace="research:tenant:tenant-a:user:user-a",
    )

    analysis = service.get_analysis("paper-1", actor=actor_a)
    reader = service.get_reader("paper-1", actor=actor_a)
    trace = service.get_trace("run-tenant-a", actor=actor_a)

    assert analysis["runId"] == "run-tenant-a"
    assert reader["metadata"]["runId"] == "run-tenant-a"
    assert trace["runId"] == "run-tenant-a"

    for hidden_call in (
        lambda: service.get_analysis("paper-1"),
        lambda: service.get_reader("paper-1"),
        lambda: service.get_trace("run-tenant-a"),
        lambda: service.get_analysis(
            "paper-1",
            actor=ResearchActorInput(
                tenant_id="tenant-b",
                user_id="user-other",
            ),
        ),
    ):
        with pytest.raises(ResearchServiceError) as hidden:
            hidden_call()
        assert hidden.value.code == "paper_not_found"


class _CapturingAskPaperUseCase(AskPaperUseCase):
    def __init__(self) -> None:
        self.goals = []

    def build_retrieval_goal(self, goal):
        self.goals.append(goal)
        return super().build_retrieval_goal(goal)


class _CapturingRagAskUseCase:
    def __init__(self) -> None:
        self.calls = []

    def rag_ask(self, paper_id, question, **kwargs):
        self.calls.append((paper_id, question, kwargs))
        return {"mode": "chunk_rag", "paper_id": paper_id}


def test_research_service_standardizes_missing_and_quality_errors() -> None:
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(make_research_result(quality_passed=False)),
        run_store=InMemoryResearchRunStore(),
    )

    with pytest.raises(ResearchServiceError) as missing:
        service.get_analysis("missing-paper")
    assert missing.value.code == "paper_not_found"

    with pytest.raises(ResearchServiceError) as quality:
        service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))
    assert quality.value.code == "quality_gate_failed"
    assert quality.value.details["gateFailures"][0]["gate_name"] == "ResearchReportReadinessGate"


def test_research_service_does_not_depend_on_old_papers_application_service() -> None:
    project_root = Path(__file__).resolve().parents[3]
    assert not (project_root / "interfaces" / "services" / "paper_service.py").exists()

    source = (project_root / "interfaces" / "services" / "research_service.py").read_text(
        encoding="utf-8"
    )
    imports = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert "interfaces.services.paper_service" not in imports

    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=InMemoryResearchRunStore(),
    )

    response = service.analyze_paper(ResearchAnalyzeInput(paper_id="paper-1", source_url="https://arxiv.org/abs/2606.00001"))

    assert response["status"] == "succeeded"


def test_in_memory_store_rejects_cross_paper_run_identity_reuse() -> None:
    store = InMemoryResearchRunStore()
    first = ResearchRunRecord(
        run_id="shared-run",
        paper_id="paper-a",
        result=make_research_result(run_id="shared-run", paper_id="paper-a"),
    )
    conflicting = ResearchRunRecord(
        run_id="shared-run",
        paper_id="paper-b",
        result=make_research_result(run_id="shared-run", paper_id="paper-b"),
    )

    store.save(first)

    with pytest.raises(ResearchRunStoreConflictError):
        store.save(conflicting)

    assert store.get_latest_by_paper_id("paper-a") == first
    assert store.get_latest_by_paper_id("paper-b") is None


def test_run_store_errors_map_to_sanitized_service_error() -> None:
    store = _UnavailableRunStore()
    service = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(),
        run_store=store,
    )

    with pytest.raises(ResearchServiceError) as failed:
        service.analyze_paper(
            ResearchAnalyzeInput(
                paper_id="paper-1",
                source_url="https://arxiv.org/abs/2606.00001",
                run_id="research-run-storage-failure",
            )
        )

    assert failed.value.code == "research_run_failed"
    assert failed.value.message == "research run storage operation failed"
    assert failed.value.details == {
        "operation": "save",
        "reason": "filesystem_unavailable",
    }
    assert failed.value.retryable is True
    assert failed.value.__cause__ is None
    assert "C:/private" not in str(failed.value.details)


class _UnavailableRunStore:
    def save(self, _record: ResearchRunRecord) -> None:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        )

    def get_by_run_id(self, _run_id: str) -> ResearchRunRecord | None:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        )

    def get_latest_by_paper_id(self, _paper_id: str) -> ResearchRunRecord | None:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        )

    def list_by_paper_id(self, _paper_id: str) -> list[ResearchRunRecord]:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        )


def test_research_service_queries_survive_durable_store_reconstruction(
    tmp_path: Path,
) -> None:
    """A reconstructed service must read the same typed result, not process state."""

    run_id = "research-run-service-restart"
    paper_id = "paper-harness-001"
    runtime = ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=FakeArtifactPort(),
        event_port_factory=lambda _run_id: InMemoryHarnessEventPort(),
    )
    result = AnalyzePaperUseCase(runtime).analyze(
        AnalyzePaperRequest(
            run_id=run_id,
            paper_id=paper_id,
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )
    assert isinstance(result, ResearchAnalysisResult)

    store_a = FilesystemResearchRunStore(
        tmp_path,
        result_decoder=ResearchAnalysisResult.from_dict,
    )
    service_a = ResearchApplicationService(
        analyze_use_case=FakeAnalyzeUseCase(result),
        run_store=store_a,
    )
    service_a.analyze_paper(
        ResearchAnalyzeInput(
            paper_id=paper_id,
            source_url="https://arxiv.org/abs/2606.00123",
            run_id=run_id,
            user_id="user-1",
        )
    )
    actor = ResearchActorInput(user_id="user-1")

    expected = {
        "analysis": service_a.get_analysis(paper_id, actor=actor),
        "reader": service_a.get_reader(paper_id, actor=actor),
        "ask": service_a.ask_paper(
            paper_id,
            ResearchAskInput(
                question="What is the method?",
                selection={"sourceRefs": ["paper://paper-harness-001/sec-intro"]},
                user_id="user-1",
            ),
        ),
        "trace": service_a.get_trace(run_id, actor=actor),
    }

    # A fresh store and service model a process restart. No in-memory result is
    # passed to the reconstructed service; only the durable root is shared.
    store_b = FilesystemResearchRunStore(
        tmp_path,
        result_decoder=ResearchAnalysisResult.from_dict,
    )
    service_b = ResearchApplicationService(run_store=store_b)

    actual = {
        "analysis": service_b.get_analysis(paper_id, actor=actor),
        "reader": service_b.get_reader(paper_id, actor=actor),
        "ask": service_b.ask_paper(
            paper_id,
            ResearchAskInput(
                question="What is the method?",
                selection={"sourceRefs": ["paper://paper-harness-001/sec-intro"]},
                user_id="user-1",
            ),
        ),
        "trace": service_b.get_trace(run_id, actor=actor),
    }

    assert actual == expected
    assert actual["analysis"]["metadata"]["artifactRefs"]
    assert actual["trace"]["transcript"]["run_id"] == run_id
