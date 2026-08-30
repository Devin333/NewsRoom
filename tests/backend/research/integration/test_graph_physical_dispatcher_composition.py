from __future__ import annotations

from pathlib import Path

from framework.harness.control_plane.harness import HarnessControlPlane
from framework.harness.runtime.graph_dispatcher import (
    HarnessGraphPhysicalActivityDispatcher,
)

from backend.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from backend.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from tests.backend.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
    in_memory_node_output_resource_factory,
)
from framework.harness import FakeArtifactPort, InMemoryHarnessEventPort


def _runtime() -> ResearchSinglePaperRuntime:
    return ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=FakeResearchLLMWorker(),
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=FakeArtifactPort(),
        event_port_factory=lambda _run_id: InMemoryHarnessEventPort(),
        node_output_resource_factory=in_memory_node_output_resource_factory,
    )


def test_research_runtime_installs_graph_physical_dispatcher_before_run(
    monkeypatch,
) -> None:
    installed: list[object] = []
    original = HarnessControlPlane.install_graph_activity_dispatcher

    def capture(self, dispatcher) -> None:
        installed.append(dispatcher)
        original(self, dispatcher)

    monkeypatch.setattr(
        HarnessControlPlane,
        "install_graph_activity_dispatcher",
        capture,
    )

    result = AnalyzePaperUseCase(_runtime()).analyze(
        AnalyzePaperRequest(
            run_id="research-graph-dispatcher-composition",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-graph-dispatcher",
        )
    )

    assert result.succeeded is True
    assert len(installed) == 1
    assert isinstance(installed[0], HarnessGraphPhysicalActivityDispatcher)


def test_sqlite_node_output_factory_creates_missing_parent_directory(tmp_path: Path) -> None:
    from infrastructure.storage.harness import SQLiteHarnessNodeOutputResource

    database = tmp_path / "nested" / "graph" / "node-output.sqlite3"
    resource = SQLiteHarnessNodeOutputResource(database)

    try:
        assert database.is_file()
        assert resource.path == str(database)
    finally:
        resource.close()
