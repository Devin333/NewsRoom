from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from threading import Barrier, Lock
from typing import Any, Iterator

from backend.research.application import AnalyzePaperUseCase
from backend.research.application.bounded_document_rag import BoundedDocumentRAGRuntime
from backend.research.application.single_paper_runtime import ResearchSinglePaperRuntime
from backend.research.document.models import PaperChunk
from backend.research.domain import (
    PaperSourceRecord,
    ResearchDocument,
    ResearchPaper,
    ResearchSection,
    SourceLineage,
    stable_research_id,
)
from framework.harness import (
    ArtifactRef,
    ArtifactWriteRequest,
    EvidenceCandidate,
    InMemoryHarnessEventPort,
    RAGBudgetSnapshot,
    RAGContextPack,
    RAGDecision,
    RAGDecisionType,
    RAGSessionResult,
    RAGSessionSpec,
    RAGSessionStatus,
    RAGTranscript,
)
from framework.shared.json import stable_json_dumps
from infrastructure.research.context_runtime import build_research_context_assembler
from interfaces.services.research_service import (
    InMemoryResearchRunStore,
    ResearchActorInput,
    ResearchAnalyzeInput,
    ResearchApplicationService,
    ResearchServiceError,
)
from tests.backend.research.fakes import in_memory_node_output_resource_factory


_NOW = datetime(2026, 7, 19, tzinfo=UTC)


def test_same_paper_tenant_a_b_runs_overlap_without_cross_tenant_visibility() -> None:
    paper_id = "paper-shared-ab"
    service, run_store, rag_runtime, artifacts, sessions, chunks = (
        _shared_production_service(Barrier(2))
    )
    requests = [
        _RunRequest(0, paper_id, "tenant-a", "user-a", 3),
        _RunRequest(1, paper_id, "tenant-b", "user-b", 9),
    ]

    observations = _execute_concurrently(
        service,
        run_store,
        rag_runtime,
        requests,
    )

    _assert_isolated_observations(
        observations,
        artifacts=artifacts,
        sessions=sessions,
    )
    assert chunks.indexed_batch_count == 2
    assert _pairwise_disjoint(sessions.chunk_ids_by_run.values())
    for request in requests:
        actor = ResearchActorInput(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            memory_namespace=request.namespace,
        )
        assert service.get_analysis(paper_id, actor=actor)["runId"] == request.run_id

    for actor in (
        None,
        ResearchActorInput(tenant_id="tenant-c", user_id="user-c"),
    ):
        try:
            service.get_analysis(paper_id, actor=actor)
        except ResearchServiceError as exc:
            assert exc.code == "paper_not_found"
        else:
            raise AssertionError("a missing or foreign actor must not see tenant runs")


def test_shared_production_service_keeps_fifty_same_paper_runs_isolated() -> None:
    run_count = 50
    paper_id = "paper-shared-50"
    service, run_store, rag_runtime, artifacts, sessions, chunks = (
        _shared_production_service(Barrier(run_count))
    )
    requests = [
        _RunRequest(
            index,
            paper_id,
            f"tenant-{index % 5}",
            f"user-{index:02d}",
            1 + index % 12,
        )
        for index in range(run_count)
    ]

    observations = _execute_concurrently(
        service,
        run_store,
        rag_runtime,
        requests,
    )

    _assert_isolated_observations(
        observations,
        artifacts=artifacts,
        sessions=sessions,
    )
    assert len({item.result.run_id for item in observations}) == run_count
    assert len({item.result.context_envelope.envelope_id for item in observations}) == run_count
    assert chunks.indexed_batch_count == run_count
    assert _pairwise_disjoint(sessions.chunk_ids_by_run.values())
    assert rag_runtime.last_context_pack is None

    for request in requests:
        actor = ResearchActorInput(
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            memory_namespace=request.namespace,
        )
        assert service.get_analysis(paper_id, actor=actor)["runId"] == request.run_id


class _PerPaperSourceProvider:
    def fetch_paper(self, source_ref: str) -> ResearchPaper:
        paper_id = source_ref.removeprefix("memory://")
        return ResearchPaper(
            paper_id=paper_id,
            title=f"Isolated Research Paper {paper_id}",
            authors=["Research Runtime"],
            abstract=f"Bounded actor isolation evidence for {paper_id}.",
            published_at=_NOW,
            source="arxiv",
            source_url=source_ref,
            topics=["research", "isolation"],
        )

    def fetch_source_record(self, paper_id: str) -> PaperSourceRecord:
        return PaperSourceRecord(
            source_id=f"source-{paper_id}",
            paper_id=paper_id,
            source_type="arxiv",
            source_url=f"memory://{paper_id}",
            fetched_at=_NOW,
            source_hash=f"sha256-{paper_id}",
        )


class _PerPaperDocumentCompiler:
    def compile(self, source: PaperSourceRecord) -> ResearchDocument:
        sections = [
            ResearchSection(
                section_id=section_id,
                title=title,
                level=1,
                text=f"{title} evidence for {source.paper_id} remains run scoped.",
                source_ref=f"paper://{source.paper_id}/{section_id}",
            )
            for section_id, title in (
                ("sec-introduction", "Introduction"),
                ("sec-method", "Method"),
                ("sec-experiments", "Experiments"),
                ("sec-limitations", "Limitations"),
            )
        ]
        source_refs = [section.source_ref for section in sections]
        return ResearchDocument(
            paper_id=source.paper_id,
            source_hash=str(source.source_hash),
            sections=sections,
            lineage=SourceLineage(
                source_refs=source_refs,
                source_hash=source.source_hash,
            ),
            metadata={"parse_source": "latex"},
        )


class _PerPaperCandidateWorker:
    def generate_candidate(
        self,
        *,
        task: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        evidence_pack = payload.get("evidence_pack") or {}
        paper = payload.get("paper") or {}
        paper_id = str(paper.get("paper_id") or evidence_pack.get("paper_id"))
        evidence = {
            str(item["span_refs"][0]): item
            for item in evidence_pack.get("items", [])
        }
        method = evidence.get("sec-method") or next(iter(evidence.values()))
        experiment = evidence.get("sec-experiments") or method
        if task == "candidate_three_minute_read":
            return {
                "three_minute_read": {
                    "problem": f"Research isolation is required for {paper_id}.",
                    "core_idea": "Harness controls routing and verification.",
                    "key_contributions": ["Bounded RAG", "Actor isolation"],
                    "method_summary": "Each request uses a bounded actor scope.",
                    "experiment_summary": "Concurrent runs retain their identities.",
                    "limitations": ["Single-host test boundary"],
                    "why_it_matters": "Cross-tenant evidence must not leak.",
                    "read_next": ["Durable replay"],
                    "evidence_refs": [
                        {
                            "evidence_id": method["evidence_id"],
                            "source_ref": method["source_ref"],
                            "section_id": "sec-method",
                            "confidence": 0.95,
                        }
                    ],
                    "confidence": 0.95,
                }
            }
        if task == "candidate_taxonomy":
            return {
                "taxonomy_candidates": [
                    {
                        "level": "domain",
                        "term_id": "code",
                        "label": "Code",
                        "evidence_refs": [method["source_ref"]],
                        "confidence": 0.9,
                    },
                    {
                        "level": "area",
                        "term_id": "agent",
                        "label": "Agent",
                        "evidence_refs": [method["source_ref"]],
                        "confidence": 0.9,
                    },
                    {
                        "level": "task",
                        "term_id": "paper_reading",
                        "label": "paper reading",
                        "evidence_refs": [method["source_ref"]],
                        "confidence": 0.9,
                    },
                ]
            }
        if task == "candidate_experiment_claims":
            return {
                "claims": [
                    {
                        "claim_id": stable_research_id(
                            "claim", paper_id, "method"
                        ),
                        "text": f"Harness isolates actor scope for {paper_id}.",
                        "claim_type": "method",
                        "section_id": "sec-method",
                        "evidence_ids": [method["evidence_id"]],
                        "confidence": 0.9,
                    },
                    {
                        "claim_id": stable_research_id(
                            "claim", paper_id, "experiment"
                        ),
                        "text": f"Concurrent execution preserves {paper_id} evidence.",
                        "claim_type": "experiment",
                        "section_id": "sec-experiments",
                        "evidence_ids": [experiment["evidence_id"]],
                        "confidence": 0.9,
                    },
                ],
                "scores": [
                    {
                        "score_id": stable_research_id(
                            "score", paper_id, "isolation"
                        ),
                        "benchmark_id": "actor_isolation",
                        "dataset_id": "concurrent_runs",
                        "metric_id": "accuracy",
                        "value": 1.0,
                        "source_refs": [experiment["source_ref"]],
                    }
                ],
            }
        return {}


class _NoGithubRepository:
    def fetch_profile(self, _repo_url: str):
        raise AssertionError("GitHub must not be called without code_url")


class _ConcurrentRunBoundArtifactPort:
    def __init__(self) -> None:
        self._current_run: ContextVar[str | None] = ContextVar(
            f"actor_isolation_artifact_run_{id(self)}",
            default=None,
        )
        self._lock = Lock()
        self._storage: dict[str, dict[str, Any]] = {}

    @property
    def current_run_id(self) -> str | None:
        return self._current_run.get()

    @contextmanager
    def bind_run(self, run_id: str) -> Iterator[str]:
        token = self._current_run.set(run_id)
        try:
            yield run_id
        finally:
            self._current_run.reset(token)

    def write_artifact(self, request: ArtifactWriteRequest) -> ArtifactRef:
        run_id = self.current_run_id
        if run_id is None:
            raise RuntimeError("artifact run is not bound")
        ref = f"artifact://{run_id}/{request.artifact_type}"
        payload = request.to_dict()
        checksum = hashlib.sha256(
            stable_json_dumps(payload).encode("utf-8")
        ).hexdigest()
        with self._lock:
            existing = self._storage.get(ref)
            if existing is not None and existing != payload:
                raise RuntimeError("artifact content conflicts within one run")
            self._storage[ref] = payload
        return ArtifactRef(
            ref=ref,
            artifact_type=request.artifact_type,
            checksum=f"sha256:{checksum}",
            media_type=request.media_type,
            metadata=request.metadata,
        )

    def read_artifact(self, ref: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._storage[ref])


@dataclass(frozen=True)
class _RunRequest:
    index: int
    paper_id: str
    tenant_id: str
    user_id: str
    rag_max_queries: int

    @property
    def run_id(self) -> str:
        return f"actor-run-{self.index:02d}"

    @property
    def namespace(self) -> str:
        return f"research:tenant:{self.tenant_id}:user:{self.user_id}"


@dataclass(frozen=True)
class _RunObservation:
    request: _RunRequest
    response: dict[str, Any]
    result: Any
    context_pack: RAGContextPack | None


def _shared_production_service(
    barrier: Barrier,
) -> tuple[
    ResearchApplicationService,
    InMemoryResearchRunStore,
    BoundedDocumentRAGRuntime,
    _ConcurrentRunBoundArtifactPort,
    "_BarrierScopedSessionFactory",
    "_FilterIgnoringConcurrentChunkStore",
]:
    chunks = _FilterIgnoringConcurrentChunkStore()
    sessions = _BarrierScopedSessionFactory(barrier)
    rag_runtime = BoundedDocumentRAGRuntime(
        chunks,
        session_factory=sessions,
    )
    artifacts = _ConcurrentRunBoundArtifactPort()
    run_store = InMemoryResearchRunStore()
    runtime = ResearchSinglePaperRuntime(
        source_provider=_PerPaperSourceProvider(),
        document_compiler=_PerPaperDocumentCompiler(),
        llm_worker=_PerPaperCandidateWorker(),
        github_repository=_NoGithubRepository(),
        rag_runtime=rag_runtime,
        artifact_port=artifacts,
        event_port_factory=lambda _run_id: InMemoryHarnessEventPort(),
        context_assembler_factory=lambda _run_id, event_port: (
            build_research_context_assembler(
                artifact_port=artifacts,
                event_port=event_port,
                provider="test-provider",
                model="test-model",
                max_input_tokens=8_192,
                max_output_tokens=1_024,
            )
        ),
        context_max_input_tokens=8_192,
        node_output_resource_factory=in_memory_node_output_resource_factory,
    )
    return (
        ResearchApplicationService(
            analyze_use_case=AnalyzePaperUseCase(runtime),
            run_store=run_store,
        ),
        run_store,
        rag_runtime,
        artifacts,
        sessions,
        chunks,
    )


def _execute_concurrently(
    service: ResearchApplicationService,
    run_store: InMemoryResearchRunStore,
    rag_runtime: BoundedDocumentRAGRuntime,
    requests: list[_RunRequest],
) -> list[_RunObservation]:
    def execute(request: _RunRequest) -> _RunObservation:
        response = service.analyze_paper(
            ResearchAnalyzeInput(
                paper_id=request.paper_id,
                source_url=f"memory://{request.paper_id}",
                run_id=request.run_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                memory_namespace=request.namespace,
                options={"rag_max_queries": request.rag_max_queries},
            )
        )
        record = run_store.get_by_run_id(request.run_id)
        assert record is not None
        return _RunObservation(
            request=request,
            response=response,
            result=record.result,
            context_pack=rag_runtime.context_pack_for_run(request.run_id),
        )

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(execute, requests))


def _assert_isolated_observations(
    observations: list[_RunObservation],
    *,
    artifacts: _ConcurrentRunBoundArtifactPort,
    sessions: "_BarrierScopedSessionFactory",
) -> None:
    for observation in observations:
        request = observation.request
        result = observation.result
        actor = {
            "tenant_id": request.tenant_id,
            "user_id": request.user_id,
            "memory_namespace": request.namespace,
        }
        spec = sessions.specs_by_run[request.run_id]
        visible_chunk_ids = sessions.chunk_ids_by_run[request.run_id]

        assert observation.response["runId"] == request.run_id
        assert observation.response["paperId"] == request.paper_id
        assert result.run_id == request.run_id
        assert result.actor_scope.to_metadata() == actor
        assert result.reader_payload.document.paper_id == request.paper_id

        assert spec.run_id == request.run_id
        assert spec.goal.metadata | actor == spec.goal.metadata
        assert spec.source_policy | actor == spec.source_policy
        assert spec.metadata | actor == spec.metadata
        assert spec.allowed_memory_namespaces == (request.namespace,)
        assert spec.budget.max_queries == request.rag_max_queries
        assert visible_chunk_ids

        assert result.rag_context.paper_id == request.paper_id
        assert result.rag_context.goal.metadata | actor == result.rag_context.goal.metadata
        assert result.rag_context.goal.allowed_memory_namespaces == [request.namespace]
        assert result.rag_context.metadata["run_id"] == request.run_id
        assert result.rag_context.metadata["session_id"] == spec.session_id
        assert result.rag_context.metadata["budget"]["max_queries"] == request.rag_max_queries
        assert result.rag_context.memory_context == [
            {"namespace": request.namespace, **actor}
        ]
        assert result.rag_context.accepted_evidence
        assert all(
            item.metadata["run_id"] == request.run_id
            and item.metadata["tenant_id"] == request.tenant_id
            and item.metadata["user_id"] == request.user_id
            and item.metadata["retrieval_evidence_id"] in visible_chunk_ids
            for item in result.rag_context.accepted_evidence
        )

        context_pack = observation.context_pack
        assert context_pack is not None
        assert context_pack.pack_id == f"rag-context://{spec.session_id}"
        assert context_pack.goal == spec.goal
        assert context_pack.metadata | actor == context_pack.metadata
        assert all(
            candidate.evidence_id in visible_chunk_ids
            for candidate in context_pack.accepted_evidence
        )

        assert result.trace.metadata | actor == result.trace.metadata
        assert result.transcript.entries()
        assert all(
            entry.metadata | actor == entry.metadata
            for entry in result.transcript.entries()
        )
        assert result.context_envelope.metadata | actor == result.context_envelope.metadata
        assert result.context_envelope.stable_prefix["worker_contract"]["metadata"][
            "memory_namespace_policy"
        ] == [request.namespace]

        assert result.artifact_refs
        assert all(
            ref.startswith(f"artifact://{request.run_id}/")
            for ref in result.artifact_refs.values()
        )
        trace_artifact = artifacts.read_artifact(result.artifact_refs["harness-trace"])
        transcript_artifact = artifacts.read_artifact(
            result.artifact_refs["harness-transcript"]
        )
        assert trace_artifact["payload"]["metadata"] | actor == trace_artifact[
            "payload"
        ]["metadata"]
        assert all(
            entry["metadata"] | actor == entry["metadata"]
            for entry in transcript_artifact["payload"]["entries"]
        )

    assert artifacts.current_run_id is None


class _FilterIgnoringConcurrentChunkStore:
    """Shared backend that ignores filters so production scoping is the oracle."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._chunks: dict[str, PaperChunk] = {}
        self._indexed_batch_count = 0

    @property
    def indexed_batch_count(self) -> int:
        with self._lock:
            return self._indexed_batch_count

    def ensure_collection(self) -> None:
        return None

    def index_chunks(self, chunks: list[PaperChunk]) -> None:
        with self._lock:
            self._chunks.update((chunk.chunk_id, chunk) for chunk in chunks)
            self._indexed_batch_count += 1

    def delete_paper_chunks(self, paper_id: str) -> None:
        raise AssertionError(f"bounded runtime must not delete shared chunks: {paper_id}")

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        del query_text, filters, score_threshold
        return self.list_chunks(paper_id)[:limit]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        return [
            (chunk, 0.95)
            for chunk in self.search_chunks(
                paper_id,
                query_text,
                filters=filters,
                limit=limit,
            )
        ]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        with self._lock:
            return self._chunks.get(chunk_id)

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        return self.get_chunk(chunk.parent_chunk_id) if chunk.parent_chunk_id else None

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        with self._lock:
            chunks = [chunk for chunk in self._chunks.values() if chunk.paper_id == paper_id]
        return sorted(chunks, key=lambda chunk: chunk.chunk_id)


class _BarrierScopedSessionFactory:
    def __init__(self, barrier: Barrier) -> None:
        self._barrier = barrier
        self._lock = Lock()
        self.specs_by_run: dict[str, RAGSessionSpec] = {}
        self.chunk_ids_by_run: dict[str, set[str]] = {}

    def __call__(self, scoped_store: Any) -> Any:
        outer = self

        class _Session:
            def run_spec(
                self,
                spec: RAGSessionSpec,
                *,
                current_section_index: int = 0,
            ) -> RAGSessionResult:
                assert current_section_index == 0
                outer._barrier.wait(timeout=60)
                paper_id = str(spec.metadata["paper_id"])
                chunks = scoped_store.list_chunks(paper_id)
                if len(chunks) < len(spec.goal.required_evidence_types):
                    raise AssertionError("scoped store did not expose this run's chunks")
                with outer._lock:
                    outer.specs_by_run[spec.run_id] = spec
                    outer.chunk_ids_by_run[spec.run_id] = {
                        chunk.chunk_id for chunk in chunks
                    }
                return _rag_result_from_scoped_chunks(spec, chunks)

        return _Session()


def _rag_result_from_scoped_chunks(
    spec: RAGSessionSpec,
    chunks: list[PaperChunk],
) -> RAGSessionResult:
    actor = {
        key: str(spec.metadata[key])
        for key in ("tenant_id", "user_id", "memory_namespace")
    }
    candidates = tuple(
        _candidate_from_scoped_chunk(spec, chunks[index], evidence_type)
        for index, evidence_type in enumerate(spec.goal.required_evidence_types)
    )
    snapshot = RAGBudgetSnapshot(
        rounds_used=1,
        queries_used=1,
        context_items_used=len(candidates),
        context_tokens_used=sum(len(item.summary.split()) for item in candidates),
        worker_calls_used=1,
    )
    graph_identity = spec.graph_identity.to_dict()
    pack = RAGContextPack(
        pack_id=f"rag-context://{spec.session_id}",
        query=spec.goal.question,
        context_refs=spec.goal.known_context_refs,
        goal=spec.goal,
        accepted_evidence=candidates,
        memory_context=({"namespace": spec.allowed_memory_namespaces[0], **actor},),
        source_refs=tuple(item.source_ref for item in candidates),
        artifact_refs=(f"artifact://{spec.run_id}/rag-context-pack",),
        evidence_trace=(
            {
                **graph_identity,
                "graph_identity": graph_identity,
                "status": "accepted",
                "session_id": spec.session_id,
                "evidence_ids": [item.evidence_id for item in candidates],
            },
        ),
        gap_report={},
        budget_snapshot=snapshot,
        metadata={
            **graph_identity,
            "graph_identity": graph_identity,
            "session_id": spec.session_id,
            **actor,
        },
    )
    return RAGSessionResult(
        status=RAGSessionStatus.SUCCEEDED,
        context_pack=pack,
        transcript=RAGTranscript(
            transcript_id=f"rag-transcript://{spec.session_id}/isolation",
            session_id=spec.session_id,
            events=(
                {
                    "event_type": "rag_session_started",
                    "payload": {"session": spec.to_dict()},
                },
            ),
            status=RAGSessionStatus.SUCCEEDED,
            created_at=_NOW,
        ),
        decision=RAGDecision(
            RAGDecisionType.RETURN_CONTEXT_PACK,
            "scoped evidence satisfied the deterministic gate",
            budget_snapshot=snapshot,
            metadata={"run_id": spec.run_id},
        ),
        accepted_evidence=candidates,
        budget_snapshot=snapshot,
    )


def _candidate_from_scoped_chunk(
    spec: RAGSessionSpec,
    chunk: PaperChunk,
    evidence_type: str,
) -> EvidenceCandidate:
    source_ref = str(chunk.metadata["source_ref"])
    return EvidenceCandidate(
        evidence_id=chunk.chunk_id,
        title=chunk.section_title or evidence_type,
        summary=chunk.content,
        source_ref=source_ref,
        span_refs=(source_ref,),
        evidence_type=evidence_type,
        confidence=0.95,
        freshness="fresh",
        lineage=(chunk.paper_id,),
        artifact_refs=(f"artifact://{spec.run_id}/rag-evidence-{evidence_type}",),
        metadata={
            **dict(chunk.metadata),
            "paper_id": chunk.paper_id,
            "rag_document_id": chunk.paper_id,
            "rag_score": 0.95,
        },
    )


def _pairwise_disjoint(groups: Any) -> bool:
    values = [set(group) for group in groups]
    return all(
        left.isdisjoint(right)
        for index, left in enumerate(values)
        for right in values[index + 1 :]
    )
