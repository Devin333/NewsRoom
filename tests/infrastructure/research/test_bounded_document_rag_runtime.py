from __future__ import annotations

from pathlib import Path

from backend.research.application.bounded_document_rag import (
    BoundedDocumentRAGRuntime,
)
from backend.research.document.chunk_storage import PaperChunkStoreAdapter
from backend.research.domain.common import SourceLineage
from backend.research.domain.document import ResearchDocument, ResearchSection
from backend.research.graphs import build_paper_analysis_context_graph_identity
from backend.research.rag.models import ResearchRetrievalGoal
from backend.research.services.rag_policy import ResearchRAGPolicyBuilder
from framework.harness.rag.models import RAGBudget
from framework.harness.rag.replay import replay_rag_session
from infrastructure.research.local_chunk_store import LocalChunkPayloadStore


def _document(
    paper_id: str = "2407.00001",
    *,
    include_experiment: bool = True,
) -> ResearchDocument:
    sections = [
        ResearchSection(
            section_id="abstract",
            title="Abstract",
            text="A bounded evidence runtime keeps deterministic routing in the Harness.",
            source_ref=f"paper://{paper_id}/sections/abstract",
        ),
        ResearchSection(
            section_id="method",
            title="Method",
            text=(
                "The bounded retrieval method indexes accepted document chunks and "
                "uses deterministic gates to verify source-backed evidence."
            ),
            page_start=1,
            page_end=2,
            source_ref=f"paper://{paper_id}/sections/method",
        ),
    ]
    if include_experiment:
        sections.append(
            ResearchSection(
                section_id="experiments",
                title="Experiments",
                text=(
                    "The experiment reports that isolated runs preserve every evidence "
                    "identifier and transcript without cross-run leakage."
                ),
                page_start=3,
                page_end=3,
                source_ref=f"paper://{paper_id}/sections/experiments",
            )
        )
    else:
        sections.append(
            ResearchSection(
                section_id="related-work",
                title="Related Work",
                text="Prior systems mix routing decisions with candidate generation.",
                source_ref=f"paper://{paper_id}/sections/related-work",
            )
        )
    sections.append(
        ResearchSection(
            section_id="conclusion",
            title="Conclusion",
            text="Deterministic verification keeps publication decisions outside the model.",
            page_start=4,
            page_end=4,
            source_ref=f"paper://{paper_id}/sections/conclusion",
        )
    )
    return ResearchDocument(
        paper_id=paper_id,
        source_hash=f"sha256:{paper_id}:source",
        sections=sections,
        lineage=SourceLineage(
            source_refs=[f"arxiv://{paper_id}/latex"],
            source_hash=f"sha256:{paper_id}:source",
        ),
        metadata={"parse_source": "latex"},
    )


def _budget(
    *,
    max_queries: int = 4,
    max_rounds: int = 2,
    max_replans: int = 1,
) -> RAGBudget:
    return RAGBudget(
        max_rounds=max_rounds,
        max_replans=max_replans,
        max_queries=max_queries,
        max_source_reads=4,
        max_memory_hits=2,
        max_context_items=8,
        max_context_tokens=2048,
        max_worker_calls=8,
    )


def _spec(
    document: ResearchDocument,
    *,
    run_id: str,
    session_id: str,
    required_types: tuple[str, ...],
    question: str,
    budget: RAGBudget | None = None,
):
    return ResearchRAGPolicyBuilder().build_session_spec(
        graph_identity=build_paper_analysis_context_graph_identity(
            run_id=run_id,
            stage_id="run_research_rag",
        ),
        session_id=session_id,
        goal=ResearchRetrievalGoal(
            goal_id=f"goal-{run_id}",
            paper_id=document.paper_id,
            question=question,
            required_evidence_types=list(required_types),
            target_sections=[section.section_id for section in document.sections],
            allowed_source_refs=list(document.lineage.source_refs),
            allowed_memory_namespaces=["research:public"],
            constraints={"paper_only": True},
        ),
        budget=budget or _budget(),
    )


def _runtime(root: Path) -> tuple[BoundedDocumentRAGRuntime, LocalChunkPayloadStore]:
    payload_store = LocalChunkPayloadStore(
        root,
        collection="bounded_runtime_chunks",
    )
    chunk_store = PaperChunkStoreAdapter(payload_store)
    return BoundedDocumentRAGRuntime(chunk_store), payload_store


def test_real_local_runtime_persists_isolated_runs_and_replays_recorded_chunks(
    tmp_path: Path,
) -> None:
    document = _document()
    runtime, payload_store = _runtime(tmp_path)
    spec_a = _spec(
        document,
        run_id="run-a",
        session_id="session-a",
        required_types=("method",),
        question="How does the bounded retrieval method verify evidence?",
    )
    spec_b = _spec(
        document,
        run_id="run-b",
        session_id="session-b",
        required_types=("method",),
        question="How does the bounded retrieval method verify evidence?",
    )

    context_a = runtime.run(session_spec=spec_a, document=document)
    context_b = runtime.run(session_spec=spec_b, document=document)

    assert context_a.accepted_evidence
    assert {item.evidence_type for item in context_a.accepted_evidence} >= {"method"}
    assert context_a.gap_report.missing_information == []
    assert context_b.accepted_evidence
    payloads = payload_store.list_paper_payloads(document.paper_id)
    run_a = [payload for payload in payloads if payload["run_id"] == "run-a"]
    run_b = [payload for payload in payloads if payload["run_id"] == "run-b"]
    assert run_a and run_b
    assert {payload["chunk_id"] for payload in run_a}.isdisjoint(
        {payload["chunk_id"] for payload in run_b}
    )
    assert {payload["metadata"]["canonical_chunk_id"] for payload in run_a} == {
        payload["metadata"]["canonical_chunk_id"] for payload in run_b
    }

    reopened = LocalChunkPayloadStore(
        tmp_path,
        collection="bounded_runtime_chunks",
    )
    accepted_physical_id = context_a.accepted_evidence[0].metadata[
        "physical_chunk_id"
    ]
    assert reopened.get_payload(accepted_physical_id) is not None
    assert reopened.search_payloads(
        document.paper_id,
        "bounded retrieval method",
        filters={"run_id": "run-a"},
        limit=20,
    )

    replay = replay_rag_session(context_a.metadata["transcript"])
    assert replay.replayable is True
    assert replay.status.value == context_a.metadata["session_status"]
    assert replay.context_pack is not None
    assert replay.context_pack["pack_id"] == context_a.metadata["context_pack_id"]
    assert replay.context_pack["budget_snapshot"] == context_a.metadata[
        "budget_snapshot"
    ]


def test_real_local_runtime_reports_missing_evidence_without_synthesis(
    tmp_path: Path,
) -> None:
    document = _document(include_experiment=False)
    runtime, _payload_store = _runtime(tmp_path)
    spec = _spec(
        document,
        run_id="run-missing",
        session_id="session-missing",
        required_types=("experiment",),
        question="Which experiment result is reported?",
        budget=_budget(max_rounds=1, max_replans=0),
    )

    context = runtime.run(session_spec=spec, document=document)

    assert "experiment" in context.gap_report.missing_information
    assert not any(
        item.evidence_type == "experiment" for item in context.accepted_evidence
    )
    assert context.metadata["session_status"] == "insufficient_evidence"
    pack = runtime.last_context_pack
    assert pack is not None
    assert pack.pack_id == "rag-context://session-missing/empty"
    assert context.metadata["context_pack_id"] == pack.pack_id
    assert pack.goal == spec.goal
    assert not any(
        item.evidence_type == "experiment" for item in pack.accepted_evidence
    )
    assert "experiment" in pack.gap_report["missing_evidence_types"]
    assert pack.budget_snapshot is not None
    assert pack.budget_snapshot.to_dict() == context.metadata["budget_snapshot"]
    assert {
        key: pack.metadata[key]
        for key in (
            "run_id",
            "graph_id",
            "graph_ref",
            "stage_id",
            "session_id",
            "status",
        )
    } == {
        "run_id": "run-missing",
        "graph_id": spec.graph_identity.graph_id,
        "graph_ref": spec.graph_identity.graph_ref,
        "stage_id": "run_research_rag",
        "session_id": "session-missing",
        "status": "insufficient_evidence",
    }
    assert pack.metadata["decision"] == context.metadata["decision"]
    assert pack.metadata["terminal_gap_pack"] is True


def test_real_local_runtime_halts_before_retrieval_when_query_budget_is_zero(
    tmp_path: Path,
) -> None:
    document = _document()
    runtime, _payload_store = _runtime(tmp_path)
    spec = _spec(
        document,
        run_id="run-budget",
        session_id="session-budget",
        required_types=("method",),
        question="How does the bounded retrieval method work?",
        budget=_budget(max_queries=0, max_rounds=1, max_replans=0),
    )

    context = runtime.run(session_spec=spec, document=document)

    event_types = [
        event["event_type"] for event in context.metadata["transcript"]["events"]
    ]
    assert context.metadata["session_status"] == "halted"
    assert context.accepted_evidence == []
    assert "method" in context.gap_report.missing_information
    assert "rag_step_executed" not in event_types
    assert event_types[-1] == "rag_halted"
    assert context.metadata["budget_snapshot"]["queries_used"] == 0
