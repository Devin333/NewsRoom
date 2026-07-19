from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast, get_args

from framework.harness.rag.models import (
    EvidenceCandidate,
    RAGContextPack,
    RAGSessionSpec,
    RAGSessionStatus,
)
from framework.harness.rag.session import RAGSessionResult

from business.research.application.paper_rag_session import PaperRAGSession
from business.research.document.chunker import PaperDocumentChunker
from business.research.document.models import PaperChunk, ParseSource
from business.research.domain.common import SourceLineage, stable_research_id, unique_texts
from business.research.domain.document import ResearchDocument
from business.research.domain.evidence import ResearchEvidenceItem
from business.research.ports.chunk_indexer import ChunkIndexerPort
from business.research.ports.chunk_store import ChunkStorePort
from business.research.rag.models import (
    ResearchRAGContext,
    ResearchRAGGapReport,
    ResearchRetrievalGoal,
)


class _RAGSessionPort(Protocol):
    def run_spec(self, spec: RAGSessionSpec, *, current_section_index: int = 0) -> RAGSessionResult: ...


RAGSessionFactory = Callable[[ChunkStorePort], _RAGSessionPort]


@dataclass(frozen=True)
class _RunChunkScope:
    paper_id: str
    run_id: str
    session_id: str
    workflow_id: str
    step_id: str
    tenant_id: str
    user_id: str

    @classmethod
    def from_spec(cls, spec: RAGSessionSpec, document: ResearchDocument) -> "_RunChunkScope":
        declared_paper_ids = _declared_scope_values(
            spec,
            keys=("paper_id",),
        )
        if any(paper_id != document.paper_id for paper_id in declared_paper_ids):
            raise ValueError("RAG session paper scope does not match the ResearchDocument")
        tenant_ids = _declared_scope_values(
            spec,
            keys=("tenant_id", "tenant", "workspace_id"),
        )
        if len(tenant_ids) > 1:
            raise ValueError("RAG session declares conflicting tenant scope")
        user_ids = _declared_scope_values(spec, keys=("user_id",))
        if len(user_ids) > 1:
            raise ValueError("RAG session declares conflicting user scope")
        return cls(
            paper_id=document.paper_id,
            run_id=spec.run_id,
            session_id=spec.session_id,
            workflow_id=spec.workflow_id,
            step_id=spec.step_id,
            tenant_id=tenant_ids[0] if tenant_ids else "",
            user_id=user_ids[0] if user_ids else "",
        )

    @property
    def tenant_namespace(self) -> str:
        return f"tenant:{self.tenant_id}" if self.tenant_id else "visibility:public"


class BoundedDocumentRAGRuntime:
    """Run one bounded Harness RAG child session over one accepted document."""

    def __init__(
        self,
        chunk_store: ChunkStorePort,
        *,
        chunk_indexer: ChunkIndexerPort | None = None,
        chunker: PaperDocumentChunker | None = None,
        session_factory: RAGSessionFactory | None = None,
    ) -> None:
        if not isinstance(chunk_store, ChunkStorePort):
            raise TypeError("chunk_store must implement ChunkStorePort")
        resolved_indexer = chunk_indexer
        if resolved_indexer is None and isinstance(chunk_store, ChunkIndexerPort):
            resolved_indexer = chunk_store
        if resolved_indexer is None or not isinstance(resolved_indexer, ChunkIndexerPort):
            raise TypeError("chunk_indexer must implement ChunkIndexerPort")
        if session_factory is not None and not callable(session_factory):
            raise TypeError("session_factory must be callable")

        self._chunk_store = chunk_store
        self._chunk_indexer = resolved_indexer
        self._chunker = chunker or PaperDocumentChunker()
        self._session_factory = session_factory or (lambda scoped_store: PaperRAGSession(scoped_store))
        self._last_context_pack: ContextVar[RAGContextPack | None] = ContextVar(
            f"bounded_document_rag_last_context_pack_{id(self)}",
            default=None,
        )

    @property
    def last_context_pack(self) -> RAGContextPack | None:
        return self._last_context_pack.get()

    def run(
        self,
        *,
        session_spec: RAGSessionSpec,
        document: ResearchDocument,
    ) -> ResearchRAGContext:
        if not isinstance(session_spec, RAGSessionSpec):
            raise TypeError("session_spec must be RAGSessionSpec")
        if not isinstance(document, ResearchDocument):
            raise TypeError("document must be ResearchDocument")

        # A failed invocation must never expose a context pack from an earlier run
        # in the same thread or async task.
        self._last_context_pack.set(None)
        scope = _RunChunkScope.from_spec(session_spec, document)
        source_refs = _validated_document_source_refs(session_spec, document)
        canonical_chunks = self._chunker.chunk(document, _parse_source(document))
        scoped_chunks = _scope_chunks(canonical_chunks, scope=scope, document=document)

        self._chunk_store.ensure_collection()
        self._chunk_indexer.index_chunks(scoped_chunks)
        scoped_store = _RunScopedChunkStore(self._chunk_store, scope)
        session = self._session_factory(scoped_store)
        if not callable(getattr(session, "run_spec", None)):
            raise TypeError("session_factory must return a run_spec-capable session")
        result = session.run_spec(session_spec)
        if not isinstance(result, RAGSessionResult):
            raise TypeError("RAG session must return RAGSessionResult")
        _validate_result_identity(result, spec=session_spec, document=document)

        context, context_pack = _project_result(
            result,
            spec=session_spec,
            document=document,
            scope=scope,
            source_refs=source_refs,
        )
        self._last_context_pack.set(context_pack)
        return context


class _RunScopedChunkStore:
    """Fail-closed view over a shared store for one paper/run/tenant scope."""

    def __init__(self, store: ChunkStorePort, scope: _RunChunkScope) -> None:
        self._store = store
        self._scope = scope

    def ensure_collection(self) -> None:
        self._store.ensure_collection()

    def search_chunks(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[PaperChunk]:
        scoped_filters = self._scoped_filters(paper_id, filters)
        if scoped_filters is None:
            return []
        chunks = self._store.search_chunks(
            paper_id,
            query_text,
            filters=scoped_filters,
            limit=limit,
            score_threshold=score_threshold,
        )
        return [chunk for chunk in chunks if self._contains(chunk)][:limit]

    def search_with_scores(
        self,
        paper_id: str,
        query_text: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[tuple[PaperChunk, float]]:
        scoped_filters = self._scoped_filters(paper_id, filters)
        if scoped_filters is None:
            return []
        scored = self._store.search_with_scores(
            paper_id,
            query_text,
            filters=scoped_filters,
            limit=limit,
        )
        return [
            (chunk, score)
            for chunk, score in scored
            if self._contains(chunk)
        ][:limit]

    def get_chunk(self, chunk_id: str) -> PaperChunk | None:
        chunk = self._store.get_chunk(chunk_id)
        return chunk if chunk is not None and self._contains(chunk) else None

    def get_parent_chunk(self, chunk: PaperChunk) -> PaperChunk | None:
        if not self._contains(chunk) or not chunk.parent_chunk_id:
            return None
        return self.get_chunk(chunk.parent_chunk_id)

    def list_chunks(self, paper_id: str) -> list[PaperChunk]:
        if paper_id != self._scope.paper_id:
            return []
        return [chunk for chunk in self._store.list_chunks(paper_id) if self._contains(chunk)]

    def _scoped_filters(
        self,
        paper_id: str,
        filters: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if paper_id != self._scope.paper_id:
            return None
        scoped = dict(filters or {})
        if _filter_conflicts(scoped.get("paper_id"), self._scope.paper_id):
            return None
        if _filter_conflicts(scoped.get("run_id"), self._scope.run_id):
            return None
        scoped["paper_id"] = self._scope.paper_id
        scoped["run_id"] = self._scope.run_id

        tenant_filters = _metadata_values(
            scoped,
            ("tenant_id", "tenant", "workspace_id"),
        )
        if len(tenant_filters) > 1:
            return None
        tenant_filter = next(iter(tenant_filters), None)
        for key in ("tenant_id", "tenant", "workspace_id"):
            scoped.pop(key, None)
        if self._scope.tenant_id:
            if tenant_filter is not None and tenant_filter != self._scope.tenant_id:
                return None
            scoped["tenant_id"] = self._scope.tenant_id
        elif tenant_filter:
            return None

        user_filters = _metadata_values(scoped, ("user_id",))
        if len(user_filters) > 1:
            return None
        user_filter = next(iter(user_filters), None)
        scoped.pop("user_id", None)
        if self._scope.user_id:
            if user_filter is not None and user_filter != self._scope.user_id:
                return None
            scoped["user_id"] = self._scope.user_id
        elif user_filter:
            return None
        return scoped

    def _contains(self, chunk: PaperChunk) -> bool:
        if chunk.paper_id != self._scope.paper_id:
            return False
        metadata = chunk.metadata
        if str(metadata.get("run_id") or "").strip() != self._scope.run_id:
            return False
        chunk_tenants = _metadata_values(metadata, ("tenant_id", "tenant", "workspace_id"))
        if self._scope.tenant_id:
            if chunk_tenants != {self._scope.tenant_id}:
                return False
        elif chunk_tenants:
            return False
        chunk_users = _metadata_values(metadata, ("user_id",))
        if self._scope.user_id:
            if chunk_users != {self._scope.user_id}:
                return False
        elif chunk_users:
            return False
        canonical_id = str(metadata.get("canonical_chunk_id") or "").strip()
        if not canonical_id:
            return False
        return chunk.chunk_id == _physical_chunk_id(self._scope, canonical_id)


def _scope_chunks(
    chunks: list[PaperChunk],
    *,
    scope: _RunChunkScope,
    document: ResearchDocument,
) -> list[PaperChunk]:
    canonical_ids = [chunk.chunk_id for chunk in chunks]
    if len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("document chunker returned duplicate canonical chunk ids")
    id_map = {
        canonical_id: _physical_chunk_id(scope, canonical_id)
        for canonical_id in canonical_ids
    }
    document_lineage = document.lineage.model_dump(mode="json", exclude_none=True)
    scoped_chunks: list[PaperChunk] = []
    for chunk in chunks:
        canonical_id = chunk.chunk_id
        metadata = _remap_chunk_references(dict(chunk.metadata), id_map)
        metadata.update(
            {
                "canonical_chunk_id": canonical_id,
                "physical_chunk_id": id_map[canonical_id],
                "run_id": scope.run_id,
                "session_id": scope.session_id,
                "workflow_id": scope.workflow_id,
                "step_id": scope.step_id,
                "source_hash": document.source_hash,
                "document_source_refs": list(document.lineage.source_refs),
                "document_lineage": document_lineage,
            }
        )
        for key in ("tenant_id", "tenant", "workspace_id"):
            metadata.pop(key, None)
        if scope.tenant_id:
            metadata["tenant_id"] = scope.tenant_id
        metadata.pop("user_id", None)
        if scope.user_id:
            metadata["user_id"] = scope.user_id
        scoped_chunks.append(
            chunk.model_copy(
                update={
                    "chunk_id": id_map[canonical_id],
                    "parent_chunk_id": id_map.get(chunk.parent_chunk_id, chunk.parent_chunk_id),
                    "references": [id_map.get(ref, ref) for ref in chunk.references],
                    "metadata": metadata,
                }
            )
        )
    return scoped_chunks


def _physical_chunk_id(scope: _RunChunkScope, canonical_id: str) -> str:
    return stable_research_id(
        "rag_chunk",
        scope.tenant_namespace,
        scope.run_id,
        canonical_id,
    )


def _remap_chunk_references(value: Any, id_map: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, dict):
        return {
            id_map.get(key, key) if isinstance(key, str) else key: _remap_chunk_references(item, id_map)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_remap_chunk_references(item, id_map) for item in value]
    if isinstance(value, tuple):
        return tuple(_remap_chunk_references(item, id_map) for item in value)
    if isinstance(value, set):
        return {_remap_chunk_references(item, id_map) for item in value}
    return value


def _project_result(
    result: RAGSessionResult,
    *,
    spec: RAGSessionSpec,
    document: ResearchDocument,
    scope: _RunChunkScope,
    source_refs: list[str],
) -> tuple[ResearchRAGContext, RAGContextPack | None]:
    raw_pack = result.context_pack
    accepted_candidates = _candidate_group(result.accepted_evidence, raw_pack, "accepted_evidence")
    rejected_candidates = list(
        _candidate_group(result.rejected_evidence, raw_pack, "rejected_evidence")
    )
    conflicting_candidates = _candidate_group(
        result.conflicting_evidence,
        raw_pack,
        "conflicting_evidence",
    )

    accepted_in_scope: list[EvidenceCandidate] = []
    conflicting_in_scope: list[EvidenceCandidate] = []
    for candidate in accepted_candidates:
        if _candidate_in_scope(candidate, spec=spec, document=document, scope=scope):
            accepted_in_scope.append(candidate)
        else:
            rejected_candidates.append(_with_rejection_reason(candidate, "source_scope_violation"))
    for candidate in conflicting_candidates:
        if _candidate_in_scope(candidate, spec=spec, document=document, scope=scope):
            conflicting_in_scope.append(candidate)
        else:
            rejected_candidates.append(_with_rejection_reason(candidate, "source_scope_violation"))

    accepted = _project_candidates(accepted_in_scope, document=document, status="accepted")
    rejected = _project_candidates(
        _dedupe_candidates(rejected_candidates),
        document=document,
        status="rejected",
    )
    conflicting = _project_candidates(
        _dedupe_candidates(conflicting_in_scope),
        document=document,
        status="conflicting",
    )
    rejected_candidates = _dedupe_candidates(rejected_candidates)
    scoped_rejected_candidates = [
        candidate
        for candidate in rejected_candidates
        if _candidate_in_scope(candidate, spec=spec, document=document, scope=scope)
    ]
    pack = _sanitize_context_pack(
        raw_pack,
        accepted=accepted_in_scope,
        rejected=rejected_candidates,
        conflicting=conflicting_in_scope,
        scoped_rejected=scoped_rejected_candidates,
        spec=spec,
        document=document,
    )
    gap_report = _project_gap_report(
        replace(result, context_pack=pack),
        spec=spec,
        accepted=accepted,
        rejected=rejected,
        conflicting=conflicting,
    )
    goal = _project_goal(spec, document=document, allowed_source_refs=source_refs)
    transcript = result.transcript.to_dict()
    budget_snapshot = result.budget_snapshot.to_dict()
    artifact_refs = unique_texts(
        [
            *document.lineage.artifact_refs,
            *(pack.artifact_refs if pack is not None else ()),
        ]
    )
    context = ResearchRAGContext(
        context_id=stable_research_id(
            "research_rag_context",
            document.paper_id,
            spec.session_id,
        ),
        paper_id=document.paper_id,
        goal=goal,
        accepted_evidence=accepted,
        rejected_evidence=rejected,
        conflicting_evidence=conflicting,
        memory_context=list(pack.memory_context) if pack is not None else [],
        gap_report=gap_report,
        source_refs=source_refs,
        lineage=SourceLineage(
            source_refs=source_refs,
            source_hash=document.source_hash,
            artifact_refs=artifact_refs,
            collected_at=document.lineage.collected_at,
            metadata={"run_id": spec.run_id, "session_id": spec.session_id},
        ),
        metadata={
            "run_id": spec.run_id,
            "session_id": spec.session_id,
            "workflow_id": spec.workflow_id,
            "step_id": spec.step_id,
            "tenant_id": scope.tenant_id,
            "user_id": scope.user_id,
            "session_status": result.status.value,
            "context_pack_id": pack.pack_id if pack is not None else None,
            "budget": spec.budget.to_dict(),
            "budget_snapshot": budget_snapshot,
            "decision": result.decision.to_dict(),
            "transcript": transcript,
            "transcript_ref": result.transcript.ref,
            "evidence_trace": list(pack.evidence_trace) if pack is not None else [],
            "context_pack_metadata": dict(pack.metadata) if pack is not None else {},
        },
    )
    return context, pack


def _candidate_group(
    result_candidates: tuple[EvidenceCandidate, ...],
    pack: RAGContextPack | None,
    field_name: str,
) -> tuple[EvidenceCandidate, ...]:
    if result_candidates:
        return result_candidates
    if pack is None:
        return ()
    return tuple(getattr(pack, field_name))


def _sanitize_context_pack(
    pack: RAGContextPack | None,
    *,
    accepted: list[EvidenceCandidate],
    rejected: list[EvidenceCandidate],
    conflicting: list[EvidenceCandidate],
    scoped_rejected: list[EvidenceCandidate],
    spec: RAGSessionSpec,
    document: ResearchDocument,
) -> RAGContextPack | None:
    if pack is None:
        return None
    scoped_candidates = [*accepted, *scoped_rejected, *conflicting]
    source_refs = unique_texts(
        [
            *spec.goal.known_context_refs,
            *(
                ref
                for candidate in scoped_candidates
                for ref in (candidate.source_ref, *candidate.span_refs)
            ),
        ]
    )
    artifact_refs = _scoped_artifact_refs(
        pack,
        candidates=scoped_candidates,
        spec=spec,
        document=document,
    )
    evidence_trace = _scoped_evidence_trace(
        accepted=accepted,
        rejected=rejected,
        conflicting=conflicting,
        spec=spec,
        document=document,
    )
    gap_report = dict(pack.gap_report)
    rejected_reasons = unique_texts(
        [
            *_text_values(gap_report.get("rejected_reasons")),
            *(
                str(candidate.metadata.get("rejection_reason") or "").strip()
                for candidate in rejected
                if str(candidate.metadata.get("rejection_reason") or "").strip()
            ),
        ]
    )
    if rejected_reasons:
        gap_report["rejected_reasons"] = rejected_reasons
    return replace(
        pack,
        evidence=tuple(candidate.to_evidence_pack() for candidate in accepted),
        accepted_evidence=tuple(accepted),
        rejected_evidence=tuple(rejected),
        conflicting_evidence=tuple(conflicting),
        source_refs=tuple(source_refs),
        artifact_refs=tuple(artifact_refs),
        evidence_trace=tuple(evidence_trace),
        gap_report=gap_report,
        assembly_summary=(
            f"Accepted {len(accepted)} evidence candidates, rejected {len(rejected)}, "
            f"flagged {len(conflicting)} conflicts, retained {len(pack.memory_context)} memory hits."
        ),
        metadata={
            **dict(pack.metadata),
            "artifact_refs": artifact_refs,
            "evidence_trace": evidence_trace,
        },
    )


def _scoped_artifact_refs(
    pack: RAGContextPack,
    *,
    candidates: list[EvidenceCandidate],
    spec: RAGSessionSpec,
    document: ResearchDocument,
) -> list[str]:
    return unique_texts(
        [
            *(
                artifact_ref
                for artifact_ref in pack.artifact_refs
                if _artifact_ref_belongs_to_scope(
                    artifact_ref,
                    spec=spec,
                    document=document,
                )
            ),
            *(
                artifact_ref
                for candidate in candidates
                for artifact_ref in candidate.artifact_refs
                if _artifact_ref_belongs_to_scope(
                    artifact_ref,
                    spec=spec,
                    document=document,
                )
            ),
        ]
    )


def _scoped_evidence_trace(
    *,
    accepted: list[EvidenceCandidate],
    rejected: list[EvidenceCandidate],
    conflicting: list[EvidenceCandidate],
    spec: RAGSessionSpec,
    document: ResearchDocument,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status, candidates in (
        ("accepted", accepted),
        ("rejected", rejected),
        ("conflicting", conflicting),
    ):
        for candidate in candidates:
            artifact_refs = [
                ref
                for ref in candidate.artifact_refs
                if _artifact_ref_belongs_to_scope(
                    ref,
                    spec=spec,
                    document=document,
                )
            ]
            rows.append(
                {
                    "status": status,
                    "evidence_id": candidate.evidence_id,
                    "evidence_type": candidate.evidence_type,
                    "source_ref": candidate.source_ref,
                    "span_refs": list(candidate.span_refs),
                    "artifact_refs": artifact_refs,
                    "lineage": list(candidate.lineage),
                    "confidence": candidate.confidence,
                    "score_breakdown": dict(
                        candidate.metadata.get("rag_score_breakdown") or {}
                    ),
                }
            )
    return rows


def _project_candidates(
    candidates: list[EvidenceCandidate] | tuple[EvidenceCandidate, ...],
    *,
    document: ResearchDocument,
    status: str,
) -> list[ResearchEvidenceItem]:
    items: list[ResearchEvidenceItem] = []
    seen: set[str] = set()
    for candidate in candidates:
        evidence_id = str(candidate.metadata.get("canonical_chunk_id") or candidate.evidence_id).strip()
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        score = _candidate_score(candidate)
        span_refs = unique_texts(
            [
                *candidate.span_refs,
                *_stable_candidate_span_refs(candidate, document=document),
            ]
        )
        lineage_source_refs = unique_texts(
            [*document.lineage.source_refs, candidate.source_ref]
        )
        items.append(
            ResearchEvidenceItem(
                evidence_id=evidence_id,
                paper_id=document.paper_id,
                title=candidate.title,
                summary=candidate.summary,
                evidence_type=candidate.evidence_type,
                source_ref=candidate.source_ref,
                span_refs=span_refs,
                claim_refs=list(candidate.claim_refs),
                confidence=candidate.confidence,
                lineage=SourceLineage(
                    source_refs=lineage_source_refs,
                    source_hash=document.source_hash,
                    artifact_refs=unique_texts(
                        [*document.lineage.artifact_refs, *candidate.artifact_refs]
                    ),
                    collected_at=document.lineage.collected_at,
                    metadata={"candidate_lineage": list(candidate.lineage)},
                ),
                metadata={
                    **dict(candidate.metadata),
                    "projection_status": status,
                    "retrieval_evidence_id": candidate.evidence_id,
                    "canonical_chunk_id": evidence_id,
                    "score": score,
                    "score_breakdown": dict(candidate.metadata.get("rag_score_breakdown") or {}),
                    "freshness": candidate.freshness,
                    "artifact_refs": list(candidate.artifact_refs),
                },
            )
        )
    return items


def _stable_candidate_span_refs(
    candidate: EvidenceCandidate,
    *,
    document: ResearchDocument,
) -> list[str]:
    canonical_id = str(candidate.metadata.get("canonical_chunk_id") or "").strip()
    if not canonical_id:
        return []
    base = f"paper://{document.paper_id}/chunks/{canonical_id}"
    main_span = candidate.metadata.get("main_span")
    if not isinstance(main_span, Mapping):
        return [base]
    try:
        start = int(main_span["start"])
        end = int(main_span["end"])
    except (KeyError, TypeError, ValueError):
        return [base]
    unit = str(candidate.metadata.get("content_span_unit") or "char_offset").strip()
    return [f"{base}#span={unit}:{start}-{end}"]


def _project_gap_report(
    result: RAGSessionResult,
    *,
    spec: RAGSessionSpec,
    accepted: list[ResearchEvidenceItem],
    rejected: list[ResearchEvidenceItem],
    conflicting: list[ResearchEvidenceItem],
) -> ResearchRAGGapReport:
    raw_gap: dict[str, Any] = {}
    if result.context_pack is not None:
        raw_gap.update(result.context_pack.gap_report)
    raw_gap.update(result.gap_report)
    missing = [
        *_text_values(raw_gap.get("missing_information")),
        *_text_values(raw_gap.get("missing_evidence_types")),
    ]
    present_types = {item.evidence_type for item in accepted}
    missing.extend(
        evidence_type
        for evidence_type in spec.goal.required_evidence_types
        if evidence_type not in present_types
    )
    rejected_reasons = [*_text_values(raw_gap.get("rejected_reasons"))]
    rejection_summary = raw_gap.get("rejection_summary")
    if isinstance(rejection_summary, Mapping):
        rejected_reasons.extend(str(reason) for reason in rejection_summary)
    rejected_reasons.extend(
        str(item.metadata.get("rejection_reason") or "").strip()
        for item in rejected
        if str(item.metadata.get("rejection_reason") or "").strip()
    )
    conflict_ids = [
        *_text_values(raw_gap.get("conflicting_evidence")),
        *(item.evidence_id for item in conflicting),
    ]
    return ResearchRAGGapReport(
        missing_information=unique_texts(missing),
        conflicting_evidence=unique_texts(conflict_ids),
        rejected_reasons=unique_texts(rejected_reasons),
        metadata={
            "raw_gap_report": raw_gap,
            "session_status": result.status.value,
            "decision": result.decision.to_dict(),
            "budget_snapshot": result.budget_snapshot.to_dict(),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "conflicting_count": len(conflicting),
        },
    )


def _project_goal(
    spec: RAGSessionSpec,
    *,
    document: ResearchDocument,
    allowed_source_refs: list[str],
) -> ResearchRetrievalGoal:
    target_sections = _text_values(spec.goal.metadata.get("target_sections"))
    target_claims = _text_values(spec.goal.metadata.get("target_claims"))
    if not target_sections and not target_claims:
        target_sections = list(spec.goal.target_entities)
    return ResearchRetrievalGoal(
        goal_id=spec.goal.goal_id,
        paper_id=document.paper_id,
        question=spec.goal.question,
        required_evidence_types=list(spec.goal.required_evidence_types),
        target_sections=target_sections,
        target_claims=target_claims,
        allowed_source_refs=allowed_source_refs,
        allowed_memory_namespaces=list(spec.allowed_memory_namespaces),
        constraints=dict(spec.goal.constraints),
        metadata={
            **dict(spec.goal.metadata),
            "run_id": spec.run_id,
            "session_id": spec.session_id,
        },
    )


def _validated_document_source_refs(
    spec: RAGSessionSpec,
    document: ResearchDocument,
) -> list[str]:
    raw_allowed = spec.source_policy.get("allowed_source_refs")
    if raw_allowed is None:
        raw_allowed = spec.goal.known_context_refs
    if isinstance(raw_allowed, str) or not isinstance(raw_allowed, (list, tuple, set, frozenset)):
        raise ValueError("RAG session allowed_source_refs must be a collection")
    allowed = unique_texts([str(ref) for ref in raw_allowed])
    if not allowed:
        raise ValueError("RAG session must declare a non-empty allowed source scope")
    known_context_refs = unique_texts(list(spec.goal.known_context_refs))
    foreign = [
        ref
        for ref in (*allowed, *known_context_refs)
        if not _source_ref_belongs_to_document(ref, document)
    ]
    if foreign:
        raise ValueError("RAG session allowed source scope contains refs outside the ResearchDocument")
    return allowed


def _validate_result_identity(
    result: RAGSessionResult,
    *,
    spec: RAGSessionSpec,
    document: ResearchDocument,
) -> None:
    if result.status != result.transcript.status:
        _raise_result_identity_error("transcript status")
    expected_decisions = {
        RAGSessionStatus.SUCCEEDED: "return_context_pack",
        RAGSessionStatus.ANSWERED: "return_answer",
        RAGSessionStatus.ABSTAINED: "abstain",
        RAGSessionStatus.INSUFFICIENT_EVIDENCE: "insufficient_evidence",
        RAGSessionStatus.HALTED: "halted",
        RAGSessionStatus.FAILED: "failed",
    }
    if result.decision.decision_type.value != expected_decisions[result.status]:
        _raise_result_identity_error("terminal decision")
    if result.decision.budget_snapshot != result.budget_snapshot:
        _raise_result_identity_error("decision budget")
    if result.transcript.session_id != spec.session_id:
        _raise_result_identity_error("transcript session")
    expected_transcript_ref = f"rag-transcript://{spec.session_id}"
    if (
        result.transcript.ref != expected_transcript_ref
        and not result.transcript.ref.startswith(f"{expected_transcript_ref}/")
    ):
        _raise_result_identity_error("transcript ref")

    started_events = [
        event
        for event in result.transcript.events
        if event.get("event_type") == "rag_session_started"
    ]
    if len(started_events) != 1:
        _raise_result_identity_error("started event")
    payload = started_events[0].get("payload")
    session_payload = payload.get("session") if isinstance(payload, Mapping) else None
    if not isinstance(session_payload, Mapping) or dict(session_payload) != spec.to_dict():
        _raise_result_identity_error("started event session")

    pack = result.context_pack
    if result.status in {
        RAGSessionStatus.SUCCEEDED,
        RAGSessionStatus.ANSWERED,
        RAGSessionStatus.ABSTAINED,
    } and pack is None:
        _raise_result_identity_error("terminal context pack")
    if pack is None:
        return
    expected_pack_id = f"rag-context://{spec.session_id}"
    if pack.pack_id != expected_pack_id and not pack.pack_id.startswith(f"{expected_pack_id}/"):
        _raise_result_identity_error("context pack session")
    if pack.query != spec.goal.question:
        _raise_result_identity_error("context pack query")
    if pack.goal is None or pack.goal.to_dict() != spec.goal.to_dict():
        _raise_result_identity_error("context pack goal")
    if tuple(pack.context_refs) != tuple(spec.goal.known_context_refs):
        _raise_result_identity_error("context pack refs")
    if pack.budget_snapshot != result.budget_snapshot:
        _raise_result_identity_error("context pack budget")
    context_envelope_id = str(
        pack.metadata.get("context_envelope_id") or ""
    ).strip()
    if (
        context_envelope_id
        and context_envelope_id != f"context://rag/{spec.session_id}"
    ):
        _raise_result_identity_error("context envelope")
    if (
        "context_policy" in pack.metadata
        and pack.metadata["context_policy"] != spec.context_policy
    ):
        _raise_result_identity_error("context policy")
    identity_mappings = [pack.metadata, *pack.evidence_trace]
    if any(_mapping_identity_conflicts(item, spec) for item in identity_mappings):
        _raise_result_identity_error("context pack trace")

    allowed_namespaces = set(spec.allowed_memory_namespaces)
    if any(
        str(item.get("namespace") or "").strip() not in allowed_namespaces
        for item in pack.memory_context
    ):
        _raise_result_identity_error("memory namespace")

    candidate_artifact_refs = {
        artifact_ref
        for candidate in (
            *result.accepted_evidence,
            *result.rejected_evidence,
            *result.conflicting_evidence,
            *pack.accepted_evidence,
            *pack.rejected_evidence,
            *pack.conflicting_evidence,
        )
        for artifact_ref in candidate.artifact_refs
    }
    for artifact_ref in pack.artifact_refs:
        if _artifact_ref_belongs_to_scope(
            artifact_ref,
            spec=spec,
            document=document,
        ):
            continue
        if artifact_ref in candidate_artifact_refs:
            continue
        _raise_result_identity_error("context pack artifact")


def _raise_result_identity_error(field: str) -> None:
    raise ValueError(
        f"RAG session result {field} does not match supplied RAGSessionSpec"
    )


def _mapping_identity_conflicts(
    value: Mapping[str, Any],
    spec: RAGSessionSpec,
) -> bool:
    expected = {
        "session_id": spec.session_id,
        "run_id": spec.run_id,
        "workflow_id": spec.workflow_id,
        "step_id": spec.step_id,
    }
    return any(
        str(value.get(field) or "").strip()
        and str(value[field]).strip() != expected_value
        for field, expected_value in expected.items()
    )


def _candidate_in_scope(
    candidate: EvidenceCandidate,
    *,
    spec: RAGSessionSpec,
    document: ResearchDocument,
    scope: _RunChunkScope,
) -> bool:
    metadata = candidate.metadata
    for key in ("paper_id", "rag_document_id", "document_id"):
        value = str(metadata.get(key) or "").strip()
        if value and value != document.paper_id:
            return False
    run_id = str(metadata.get("run_id") or "").strip()
    if run_id != spec.run_id:
        return False
    tenant_ids = _metadata_values(metadata, ("tenant_id", "tenant", "workspace_id"))
    if scope.tenant_id:
        if tenant_ids != {scope.tenant_id}:
            return False
    elif tenant_ids:
        return False
    user_ids = _metadata_values(metadata, ("user_id",))
    if scope.user_id:
        if user_ids != {scope.user_id}:
            return False
    elif user_ids:
        return False
    if not _source_ref_belongs_to_document(candidate.source_ref, document):
        return False
    if any(
        not _source_ref_belongs_to_document(span_ref, document)
        for span_ref in candidate.span_refs
    ):
        return False
    if any(
        not _lineage_ref_belongs_to_document(lineage_ref, document)
        for lineage_ref in candidate.lineage
    ):
        return False
    return all(
        _artifact_ref_belongs_to_scope(
            artifact_ref,
            spec=spec,
            document=document,
        )
        for artifact_ref in candidate.artifact_refs
    )


def _lineage_ref_belongs_to_document(
    lineage_ref: str,
    document: ResearchDocument,
) -> bool:
    ref = str(lineage_ref or "").strip()
    if ref == document.paper_id:
        return True
    return _source_ref_belongs_to_document(ref, document)


def _artifact_ref_belongs_to_scope(
    artifact_ref: str,
    *,
    spec: RAGSessionSpec,
    document: ResearchDocument,
) -> bool:
    ref = str(artifact_ref or "").strip()
    if not ref.startswith("artifact://"):
        return True
    roots = unique_texts(
        [
            f"artifact://{spec.run_id}",
            *document.lineage.artifact_refs,
        ]
    )
    return any(ref == root or ref.startswith(f"{root}/") for root in roots)


def _source_ref_belongs_to_document(source_ref: str, document: ResearchDocument) -> bool:
    ref = str(source_ref or "").strip()
    if not ref:
        return False
    document_refs = unique_texts(
        [
            *document.lineage.source_refs,
            *(section.source_ref for section in document.sections),
            *(figure.source_ref for figure in document.figures),
            *(table.source_ref for table in document.tables),
            *(equation.source_ref for equation in document.equations),
        ]
    )
    if any(_ref_is_same_or_descendant(ref, root) for root in document_refs):
        return True
    return any(
        _ref_is_same_or_descendant(ref, f"{scheme}{document.paper_id}")
        for scheme in ("paper://", "arxiv://")
    )


def _ref_is_same_or_descendant(ref: str, root: str) -> bool:
    if ref == root:
        return True
    return any(ref.startswith(f"{root}{separator}") for separator in ("#", "?", "/"))


def _with_rejection_reason(candidate: EvidenceCandidate, reason: str) -> EvidenceCandidate:
    return replace(
        candidate,
        metadata={**dict(candidate.metadata), "rejection_reason": reason},
    )


def _dedupe_candidates(candidates: list[EvidenceCandidate] | tuple[EvidenceCandidate, ...]) -> list[EvidenceCandidate]:
    seen: set[str] = set()
    result: list[EvidenceCandidate] = []
    for candidate in candidates:
        if candidate.evidence_id in seen:
            continue
        seen.add(candidate.evidence_id)
        result.append(candidate)
    return result


def _candidate_score(candidate: EvidenceCandidate) -> float:
    raw = candidate.metadata.get("rag_score")
    if raw is None:
        return candidate.confidence
    try:
        return float(raw)
    except (TypeError, ValueError):
        return candidate.confidence


def _parse_source(document: ResearchDocument) -> ParseSource:
    value = str(document.metadata.get("parse_source") or "latex")
    allowed = set(get_args(ParseSource))
    if value not in allowed:
        raise ValueError(f"unsupported ResearchDocument parse_source: {value}")
    return cast(ParseSource, value)


def _declared_scope_values(
    spec: RAGSessionSpec,
    *,
    keys: tuple[str, ...],
) -> list[str]:
    values: list[str] = []
    for source in (spec.source_policy, spec.metadata, spec.goal.metadata):
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value and value not in values:
                values.append(value)
    return values


def _filter_conflicts(raw: Any, expected: str) -> bool:
    if raw is None or str(raw).strip() == "":
        return False
    return str(raw).strip() != expected


def _metadata_values(metadata: Mapping[str, Any], keys: tuple[str, ...]) -> set[str]:
    return {
        value
        for key in keys
        if (value := str(metadata.get(key) or "").strip())
    }


def _text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if str(item).strip()]
    return []


__all__ = ["BoundedDocumentRAGRuntime", "RAGSessionFactory"]
