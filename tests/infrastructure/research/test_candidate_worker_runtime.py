from __future__ import annotations

import json

import pytest

from business.research.application import AnalyzePaperRequest, AnalyzePaperUseCase
from business.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from framework.harness import FakeArtifactPort, InMemoryHarnessEventPort
from framework.llm.clients.openai_compatible import (
    OpenAICompatibleClient,
    OpenAICompatibleConfig,
)
from infrastructure.research import StructuredResearchCandidateWorker
from tests.business.research.fakes import (
    FakeGithubRepositoryPort,
    FakeResearchDocumentCompiler,
    FakeResearchLLMWorker,
    FakeResearchRAGRuntime,
    FakeResearchSourceProvider,
)


def test_structured_candidate_worker_runs_through_deterministic_research_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_RESEARCH_RUNTIME_LLM_KEY", "recorded-key")
    candidate_source = FakeResearchLLMWorker()
    requested_tasks: list[str] = []

    def transport(request, timeout: float) -> bytes:
        assert timeout == 10.0
        request_payload = json.loads(request.data.decode("utf-8"))
        prompt = "\n".join(
            str(message.get("content") or "")
            for message in request_payload["messages"]
        )
        task = next(
            task_name
            for task_name in (
                "candidate_three_minute_read",
                "candidate_taxonomy",
                "candidate_experiment_claims",
            )
            if f"Candidate task: {task_name}" in prompt
        )
        requested_tasks.append(task)
        candidate = candidate_source.generate_candidate(task=task, payload={})
        return json.dumps(
            {
                "id": f"recorded-{task}",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(candidate),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }
        ).encode("utf-8")

    candidate_worker = StructuredResearchCandidateWorker(
        OpenAICompatibleClient(
            OpenAICompatibleConfig(
                provider="recorded",
                base_url="https://llm.example/v1",
                model="recorded-model",
                api_key_env="TEST_RESEARCH_RUNTIME_LLM_KEY",
                timeout_seconds=10.0,
            ),
            transport=transport,
        )
    )
    runtime = ResearchSinglePaperRuntime(
        source_provider=FakeResearchSourceProvider(),
        document_compiler=FakeResearchDocumentCompiler(),
        llm_worker=candidate_worker,
        github_repository=FakeGithubRepositoryPort(),
        rag_runtime=FakeResearchRAGRuntime(),
        artifact_port=FakeArtifactPort(),
        event_port_factory=lambda run_id: InMemoryHarnessEventPort(),
    )

    result = AnalyzePaperUseCase(runtime).analyze(
        AnalyzePaperRequest(
            run_id="structured-candidate-runtime",
            paper_id="paper-harness-001",
            source_ref="https://arxiv.org/abs/2606.00123",
            user_id="user-1",
        )
    )

    assert result.succeeded is True
    assert requested_tasks == [
        "candidate_three_minute_read",
        "candidate_taxonomy",
        "candidate_experiment_claims",
    ]
    gate_events = [
        event.to_dict()
        for event in result.trace.events
        if event.event_type.value == "gate_evaluated"
        and event.step_id
        in {"analyze_structure", "analyze_contribution", "analyze_experiments"}
    ]
    assert gate_events
    assert all(event["payload"]["passed"] is True for event in gate_events)
    assert all(
        "next_step" not in worker_result["output"]
        and "quality_passed" not in worker_result["output"]
        for worker_result in result.diagnostics["worker_results"].values()
    )
