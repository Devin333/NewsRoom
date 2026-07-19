from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from business.research.application import (
    AnalyzePaperRequest,
    AskPaperUseCase,
    ResearchActorScope,
)
from business.research.domain import stable_research_id
from business.research.ports.run_store import (
    ResearchRunRecord,
    ResearchRunStore,
    ResearchRunStoreConflictError,
    ResearchRunStoreError,
    ResearchRunStoreReason,
)
from business.research.rag import ResearchRetrievalGoal
from interfaces.models import ActorContext


@dataclass(frozen=True)
class ResearchAnalyzeInput:
    paper_id: str
    source_url: str | None = None
    pdf_url: str | None = None
    run_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    memory_namespace: str | None = None


@dataclass(frozen=True)
class ResearchAskInput:
    question: str
    locale: str | None = None
    selection: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    user_id: str | None = None
    memory_namespace: str | None = None
    mode: str = "summary"
    section_index: int = 0
    limit: int = 5
    generate: bool = False
    gated: bool = True


@dataclass(frozen=True)
class ResearchActorInput:
    tenant_id: str | None = None
    user_id: str | None = None
    memory_namespace: str | None = None


class ResearchServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        user_action_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable
        self.user_action_required = user_action_required


class ResearchActorAuthorizationError(ResearchServiceError):
    pass


class ResearchAnalyzeUseCase(Protocol):
    def analyze(self, request: AnalyzePaperRequest) -> Any:
        ...


class ResearchRagAskUseCase(Protocol):
    def rag_ask(
        self,
        paper_id: str,
        question: str,
        *,
        section_index: int,
        limit: int,
        generate: bool,
        gated: bool,
        tenant_id: str | None,
        user_id: str | None,
        memory_namespace: str,
    ) -> dict[str, Any]:
        ...


class InMemoryResearchRunStore:
    def __init__(self) -> None:
        self._records_by_run_id: dict[str, ResearchRunRecord] = {}
        self._run_ids_by_paper_id: dict[str, list[str]] = {}
        self._lock = RLock()

    def save(self, record: ResearchRunRecord) -> None:
        if not isinstance(record, ResearchRunRecord):
            raise TypeError("record must be ResearchRunRecord")
        with self._lock:
            existing = self._records_by_run_id.get(record.run_id)
            if existing is not None:
                if existing != record:
                    raise ResearchRunStoreConflictError(
                        reason=ResearchRunStoreReason.IDENTITY_CONFLICT,
                    )
                return
            self._records_by_run_id[record.run_id] = record
            run_ids = self._run_ids_by_paper_id.setdefault(record.paper_id, [])
            if record.run_id not in run_ids:
                run_ids.append(record.run_id)

    def get_by_run_id(self, run_id: str) -> ResearchRunRecord | None:
        with self._lock:
            return self._records_by_run_id.get(run_id)

    def get_latest_by_paper_id(self, paper_id: str) -> ResearchRunRecord | None:
        with self._lock:
            run_ids = self._run_ids_by_paper_id.get(paper_id) or []
            if not run_ids:
                return None
            return self._records_by_run_id.get(run_ids[-1])

    def list_by_paper_id(self, paper_id: str) -> list[ResearchRunRecord]:
        with self._lock:
            run_ids = reversed(self._run_ids_by_paper_id.get(paper_id) or [])
            return [
                self._records_by_run_id[run_id]
                for run_id in run_ids
                if run_id in self._records_by_run_id
            ]


class ResearchApplicationService:
    def __init__(
        self,
        *,
        analyze_use_case: ResearchAnalyzeUseCase | None = None,
        ask_use_case: AskPaperUseCase | None = None,
        rag_ask_use_case: ResearchRagAskUseCase | None = None,
        run_store: ResearchRunStore | None = None,
    ) -> None:
        self._analyze_use_case = analyze_use_case or _UnconfiguredAnalyzeUseCase()
        self._ask_use_case = ask_use_case or AskPaperUseCase()
        self._rag_ask_use_case = rag_ask_use_case or _UnconfiguredRagAskUseCase()
        self._run_store = run_store or _DEFAULT_RESEARCH_RUN_STORE

    def analyze_paper(self, command: ResearchAnalyzeInput) -> dict[str, Any]:
        paper_id = _require_text(command.paper_id, "paperId")
        source_ref = _source_ref(command)
        run_id = _optional_text(command.run_id) or f"research-run-{uuid4().hex}"
        options = _runtime_options(command)
        actor_scope = _resolve_actor_scope(
            self._ask_use_case,
            tenant_id=command.tenant_id,
            user_id=command.user_id,
            memory_namespace=command.memory_namespace,
        )
        request = AnalyzePaperRequest(
            run_id=run_id,
            paper_id=paper_id,
            source_ref=source_ref,
            user_id=actor_scope.user_id,
            options=options,
            tenant_id=actor_scope.tenant_id,
            memory_namespace=actor_scope.memory_namespace,
        )
        try:
            result = self._analyze_use_case.analyze(request)
        except ResearchServiceError:
            raise
        except ValueError as exc:
            raise ResearchServiceError("invalid_request", str(exc), status_code=400, user_action_required=True) from exc
        except Exception as exc:
            raise ResearchServiceError(
                "research_run_failed",
                "research run failed",
                status_code=500,
                details={"error_type": type(exc).__name__},
                retryable=True,
            ) from exc

        record = ResearchRunRecord(run_id=run_id, paper_id=paper_id, result=result)
        try:
            self._run_store.save(record)
        except ResearchRunStoreError as exc:
            raise _run_store_service_error(exc, operation="save") from None
        self._ensure_run_succeeded(record)
        self._ensure_quality_passed(record)
        return self._analyze_response(record)

    def get_analysis(
        self,
        paper_id: str,
        *,
        actor: ResearchActorInput | None = None,
    ) -> dict[str, Any]:
        actor_scope = _resolve_actor_input(self._ask_use_case, actor)
        record = self._record_for_paper(paper_id, actor_scope=actor_scope)
        self._ensure_run_succeeded(record)
        self._ensure_quality_passed(record)
        analysis = getattr(record.result, "analysis", None)
        if analysis is None:
            raise ResearchServiceError(
                "analysis_not_found",
                f"analysis not found for paper {record.paper_id}",
                status_code=404,
                user_action_required=True,
            )
        return {
            "runId": record.run_id,
            "paperId": record.paper_id,
            "status": _result_status(record.result),
            "analysis": _to_dict(analysis),
            "quality": _to_dict(getattr(record.result, "quality", None)),
            "analysisRef": _artifact_ref(record.result, "research-analysis"),
            "qualityRef": _artifact_ref(record.result, "research-quality-result"),
            "traceRef": _trace_ref(record.result, record.run_id),
            "metadata": {"artifactRefs": _artifact_refs(record.result)},
        }

    def get_reader(
        self,
        paper_id: str,
        *,
        actor: ResearchActorInput | None = None,
    ) -> dict[str, Any]:
        actor_scope = _resolve_actor_input(self._ask_use_case, actor)
        record = self._record_for_paper(paper_id, actor_scope=actor_scope)
        self._ensure_run_succeeded(record)
        self._ensure_quality_passed(record)
        reader_payload = getattr(record.result, "reader_payload", None)
        if reader_payload is None:
            raise ResearchServiceError(
                "analysis_not_found",
                f"reader payload not found for paper {record.paper_id}",
                status_code=404,
                user_action_required=True,
            )
        return {
            "paper": _to_dict(getattr(reader_payload, "paper", None)),
            "document": _to_dict(getattr(reader_payload, "document", None)),
            "analysis": _to_dict(getattr(reader_payload, "analysis", None)),
            "evidence": _to_dict(getattr(reader_payload, "evidence", None)),
            "navigation": [_to_dict(item) for item in getattr(reader_payload, "navigation", [])],
            "quality": [_to_dict(item) for item in getattr(reader_payload, "quality", [])],
            "metadata": {
                **_mapping(getattr(reader_payload, "metadata", {})),
                "runId": record.run_id,
                "paperId": record.paper_id,
                "status": _result_status(record.result),
                "readerPayloadRef": _artifact_ref(record.result, "research-reader-payload"),
                "traceRef": _trace_ref(record.result, record.run_id),
            },
        }

    def ask_paper(self, paper_id: str, request: ResearchAskInput) -> dict[str, Any]:
        question = _require_text(request.question, "question")
        mode = _ask_mode(request.mode)
        actor_scope = _resolve_actor_scope(
            self._ask_use_case,
            tenant_id=request.tenant_id,
            user_id=(
                request.user_id
                or _optional_text(request.options.get("userId"))
                or _optional_text(request.options.get("user_id"))
            ),
            memory_namespace=request.memory_namespace,
        )
        if mode == "chunk_rag":
            return self._ask_paper_chunks(
                paper_id,
                question,
                request=request,
                actor_scope=actor_scope,
            )

        record = self._record_for_paper(paper_id, actor_scope=actor_scope)
        _ensure_record_visible_to_actor(record, actor_scope)
        self._ensure_run_succeeded(record)
        self._ensure_quality_passed(record)
        reader_payload = getattr(record.result, "reader_payload", None)
        analysis = getattr(record.result, "analysis", None)
        if reader_payload is None or analysis is None:
            raise ResearchServiceError(
                "analysis_not_found",
                f"reader analysis not found for paper {record.paper_id}",
                status_code=404,
                user_action_required=True,
            )
        goal = self._ask_use_case.build_retrieval_goal(
            ResearchRetrievalGoal(
                goal_id=stable_research_id("research_ask", record.run_id, question),
                paper_id=record.paper_id,
                question=question,
                required_evidence_types=["claim_support"],
                target_sections=_selection_targets(request.selection),
                allowed_source_refs=_reader_source_refs(reader_payload),
                allowed_memory_namespaces=[actor_scope.memory_namespace],
                constraints={"locale": request.locale or "en", "paper_only": True},
                metadata={"run_id": record.run_id, **actor_scope.to_metadata()},
            )
        )
        evidence_refs = _answer_evidence_refs(analysis, reader_payload, request.selection)
        return {
            "answer": _answer_from_analysis(question, analysis),
            "evidenceRefs": evidence_refs,
            "confidence": _answer_confidence(analysis),
            "traceRef": _trace_ref(record.result, record.run_id),
            "metadata": {
                "runId": record.run_id,
                "paperId": record.paper_id,
                "retrievalGoalId": goal.goal_id,
                "sourceRefs": goal.allowed_source_refs,
            },
        }

    def _ask_paper_chunks(
        self,
        paper_id: str,
        question: str,
        *,
        request: ResearchAskInput,
        actor_scope: ResearchActorScope,
    ) -> dict[str, Any]:
        normalized_paper_id = _require_text(paper_id, "paperId")
        section_index = _bounded_int(
            request.section_index,
            "sectionIndex",
            minimum=0,
        )
        limit = _bounded_int(
            request.limit,
            "limit",
            minimum=1,
            maximum=20,
        )
        try:
            return self._rag_ask_use_case.rag_ask(
                normalized_paper_id,
                question,
                section_index=section_index,
                limit=limit,
                generate=bool(request.generate),
                gated=bool(request.gated),
                tenant_id=actor_scope.tenant_id,
                user_id=actor_scope.user_id,
                memory_namespace=actor_scope.memory_namespace,
            )
        except ResearchServiceError:
            raise
        except ValueError as exc:
            raise ResearchServiceError(
                "invalid_request",
                str(exc),
                status_code=400,
                user_action_required=True,
            ) from exc
        except Exception as exc:
            raise ResearchServiceError(
                "research_run_failed",
                "research RAG request failed",
                status_code=500,
                details={"error_type": type(exc).__name__},
                retryable=True,
            ) from exc

    def get_trace(
        self,
        run_id: str,
        *,
        actor: ResearchActorInput | None = None,
    ) -> dict[str, Any]:
        normalized_run_id = _require_text(run_id, "runId")
        actor_scope = _resolve_actor_input(self._ask_use_case, actor)
        try:
            record = self._run_store.get_by_run_id(normalized_run_id)
        except ResearchRunStoreError as exc:
            raise _run_store_service_error(exc, operation="read_by_run") from None
        if record is None:
            raise ResearchServiceError(
                "research_run_failed",
                f"research run not found: {normalized_run_id}",
                status_code=404,
                user_action_required=True,
            )
        _ensure_record_visible_to_actor(record, actor_scope)
        return {
            "runId": record.run_id,
            "paperId": record.paper_id,
            "status": _result_status(record.result),
            "traceRef": _trace_ref(record.result, record.run_id),
            "trace": _to_dict(getattr(record.result, "trace", None)),
            "transcript": _to_dict(getattr(record.result, "transcript", None)),
            "metadata": {
                "artifactRefs": _artifact_refs(record.result),
                "diagnostics": _to_dict(getattr(record.result, "diagnostics", {})),
            },
        }

    def _record_for_paper(
        self,
        paper_id: str,
        *,
        actor_scope: ResearchActorScope,
    ) -> ResearchRunRecord:
        normalized = _require_text(paper_id, "paperId")
        try:
            records = self._run_store.list_by_paper_id(normalized)
        except ResearchRunStoreError as exc:
            raise _run_store_service_error(
                exc,
                operation="list_by_paper",
            ) from None
        for record in records:
            if _record_visible_to_actor(record, actor_scope):
                return record
        raise ResearchServiceError(
            "paper_not_found",
            f"paper not found: {normalized}",
            status_code=404,
            user_action_required=True,
        )

    def _ensure_run_succeeded(self, record: ResearchRunRecord) -> None:
        status = _result_status(record.result)
        if status in {"failed", "halted", "cancelled"}:
            raise ResearchServiceError(
                "research_run_failed",
                f"research run {record.run_id} ended with status {status}",
                status_code=500,
                details={"runId": record.run_id, "status": status},
                retryable=status != "cancelled",
            )

    def _ensure_quality_passed(self, record: ResearchRunRecord) -> None:
        quality = getattr(record.result, "quality", None)
        if quality is None or bool(getattr(quality, "passed", True)):
            return
        raise ResearchServiceError(
            "quality_gate_failed",
            f"research quality gates failed for paper {record.paper_id}",
            status_code=422,
            details={
                "runId": record.run_id,
                "paperId": record.paper_id,
                "gateFailures": _quality_gate_failures(quality),
            },
            user_action_required=True,
        )

    def _analyze_response(self, record: ResearchRunRecord) -> dict[str, Any]:
        return {
            "runId": record.run_id,
            "paperId": record.paper_id,
            "status": _result_status(record.result),
            "analysisRef": _artifact_ref(record.result, "research-analysis"),
            "readerPayloadRef": _artifact_ref(record.result, "research-reader-payload"),
            "qualityRef": _artifact_ref(record.result, "research-quality-result"),
            "traceRef": _trace_ref(record.result, record.run_id),
            "paperCardRef": _artifact_ref(record.result, "research-paper-card"),
            "metadata": {"artifactRefs": _artifact_refs(record.result)},
        }


class _UnconfiguredAnalyzeUseCase:
    def analyze(self, request: AnalyzePaperRequest) -> Any:
        raise ResearchServiceError(
            "research_run_failed",
            "Research analyze runtime is not configured",
            status_code=503,
            retryable=False,
            user_action_required=True,
        )


class _UnconfiguredRagAskUseCase:
    def rag_ask(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ResearchServiceError(
            "research_run_failed",
            "Research chunk RAG runtime is not configured",
            status_code=503,
            retryable=False,
            user_action_required=True,
        )


def _source_ref(command: ResearchAnalyzeInput) -> str:
    source_ref = _optional_text(command.source_url) or _optional_text(command.pdf_url)
    if source_ref is None:
        raise ResearchServiceError(
            "invalid_request",
            "sourceUrl or pdfUrl is required",
            status_code=400,
            user_action_required=True,
        )
    return source_ref


def _runtime_options(command: ResearchAnalyzeInput) -> dict[str, Any]:
    options = dict(command.options)
    if command.source_url is not None:
        options["source_url"] = command.source_url
    if command.pdf_url is not None:
        options["pdf_url"] = command.pdf_url
    if command.metadata:
        options["metadata"] = dict(command.metadata)
    return options


def _resolve_actor_scope(
    use_case: AskPaperUseCase,
    *,
    tenant_id: str | None,
    user_id: str | None,
    memory_namespace: str | None,
) -> ResearchActorScope:
    try:
        return use_case.resolve_actor_scope(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_namespace=memory_namespace,
        )
    except ValueError as exc:
        raise ResearchServiceError(
            "invalid_request",
            str(exc),
            status_code=400,
            user_action_required=True,
        ) from exc


def _resolve_actor_input(
    use_case: AskPaperUseCase,
    actor: ResearchActorInput | None,
) -> ResearchActorScope:
    actual = actor or ResearchActorInput()
    if not isinstance(actual, ResearchActorInput):
        raise ResearchServiceError(
            "invalid_request",
            "actor must be ResearchActorInput",
            status_code=400,
            user_action_required=True,
        )
    return _resolve_actor_scope(
        use_case,
        tenant_id=actual.tenant_id,
        user_id=actual.user_id,
        memory_namespace=actual.memory_namespace,
    )


def bind_research_actor_input(
    requested: ResearchActorInput,
    actor: ActorContext | None,
) -> ResearchActorInput:
    if not isinstance(requested, ResearchActorInput):
        raise TypeError("requested must be ResearchActorInput")
    if actor is None:
        return requested
    if not isinstance(actor, ActorContext):
        raise TypeError("actor must be ActorContext or None")

    metadata = actor.metadata if isinstance(actor.metadata, dict) else {}
    trusted_user_id = _optional_text(metadata.get("user_id"))
    if trusted_user_id is None and actor.actor_type == "user":
        trusted_user_id = _trusted_actor_scope_id(actor.actor_id)
    trusted = ResearchActorInput(
        tenant_id=_optional_text(metadata.get("tenant_id")),
        user_id=trusted_user_id,
        memory_namespace=_optional_text(metadata.get("memory_namespace")),
    )
    try:
        trusted_scope = AskPaperUseCase().resolve_actor_scope(
            tenant_id=trusted.tenant_id,
            user_id=trusted.user_id,
            memory_namespace=trusted.memory_namespace,
        )
        merged_scope = AskPaperUseCase().resolve_actor_scope(
            tenant_id=requested.tenant_id or trusted_scope.tenant_id,
            user_id=requested.user_id or trusted_scope.user_id,
            memory_namespace=(
                requested.memory_namespace or trusted_scope.memory_namespace
            ),
        )
    except ValueError:
        raise _research_actor_forbidden() from None
    if merged_scope != trusted_scope:
        raise _research_actor_forbidden()
    return ResearchActorInput(
        tenant_id=trusted_scope.tenant_id,
        user_id=trusted_scope.user_id,
        memory_namespace=trusted_scope.memory_namespace,
    )


def _trusted_actor_scope_id(actor_id: str) -> str:
    text = str(actor_id or "").strip()
    try:
        return AskPaperUseCase().resolve_actor_scope(user_id=text).user_id or ""
    except ValueError:
        return stable_research_id("research_actor", text)


def _research_actor_forbidden() -> ResearchActorAuthorizationError:
    return ResearchActorAuthorizationError(
        "forbidden",
        "Research actor scope does not match the authenticated principal",
        status_code=403,
        user_action_required=True,
    )


def _ensure_record_visible_to_actor(
    record: ResearchRunRecord,
    actor_scope: ResearchActorScope,
) -> None:
    if _record_visible_to_actor(record, actor_scope):
        return
    raise ResearchServiceError(
        "paper_not_found",
        f"paper not found: {record.paper_id}",
        status_code=404,
        user_action_required=True,
    )


def _record_visible_to_actor(
    record: ResearchRunRecord,
    actor_scope: ResearchActorScope,
) -> bool:
    persisted_scope = getattr(record.result, "actor_scope", None)
    if isinstance(persisted_scope, ResearchActorScope):
        record_tenant = persisted_scope.tenant_id
        record_user = persisted_scope.user_id
        record_namespace = persisted_scope.memory_namespace
    else:
        trace = getattr(record.result, "trace", None)
        trace_metadata = getattr(trace, "metadata", None)
        if not isinstance(trace_metadata, dict) and isinstance(trace, dict):
            trace_metadata = trace.get("metadata")
        metadata = trace_metadata if isinstance(trace_metadata, dict) else {}
        record_tenant = _optional_text(metadata.get("tenant_id"))
        record_user = _optional_text(metadata.get("user_id"))
        record_namespace = _optional_text(metadata.get("memory_namespace"))
    if record_tenant is not None:
        if actor_scope.tenant_id != record_tenant:
            return False
        if record_namespace == f"research:tenant:{record_tenant}:public":
            return True
    elif record_namespace in {None, "research.public"} and record_user is None:
        return True
    if record_user is not None and actor_scope.user_id != record_user:
        return False
    if record_namespace is not None:
        return actor_scope.memory_namespace == record_namespace
    return record_user is None or actor_scope.user_id == record_user


def _require_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ResearchServiceError(
            "invalid_request",
            f"{field_name} is required",
            status_code=400,
            user_action_required=True,
        )
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ask_mode(value: Any) -> str:
    mode = str(value or "summary").strip().lower()
    if mode not in {"summary", "chunk_rag"}:
        raise ResearchServiceError(
            "invalid_request",
            "mode must be summary or chunk_rag",
            status_code=400,
            user_action_required=True,
        )
    return mode


def _bounded_int(
    value: Any,
    field_name: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        parsed = -1
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = -1
    if parsed < minimum or maximum is not None and parsed > maximum:
        suffix = f" and at most {maximum}" if maximum is not None else ""
        raise ResearchServiceError(
            "invalid_request",
            f"{field_name} must be at least {minimum}{suffix}",
            status_code=400,
            user_action_required=True,
        )
    return parsed


def _result_status(result: Any) -> str:
    return str(getattr(result, "status", None) or "unknown")


def _artifact_refs(result: Any) -> dict[str, str]:
    refs = getattr(result, "artifact_refs", {}) or {}
    if not isinstance(refs, dict):
        return {}
    return {str(key): str(value) for key, value in refs.items() if value is not None}


def _artifact_ref(result: Any, key: str) -> str | None:
    return _artifact_refs(result).get(key)


def _trace_ref(result: Any, run_id: str) -> str:
    return str(getattr(result, "trace_ref", None) or f"harness-trace://{run_id}")


def _to_dict(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_dict(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _selection_targets(selection: dict[str, Any]) -> list[str]:
    raw = selection.get("sectionIds") or selection.get("section_ids") or selection.get("targetRefs") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip() for item in raw if str(item).strip()]


def _reader_source_refs(reader_payload: Any) -> list[str]:
    lineage = getattr(reader_payload, "source_lineage", None)
    refs = list(getattr(lineage, "source_refs", []) or [])
    if refs:
        return [str(ref) for ref in refs]
    document = getattr(reader_payload, "document", None)
    lineage = getattr(document, "lineage", None)
    refs = list(getattr(lineage, "source_refs", []) or [])
    return [str(ref) for ref in refs] or ["paper://unknown/source"]


def _answer_from_analysis(question: str, analysis: Any) -> str:
    summary = getattr(analysis, "summary", None)
    lowered = question.casefold()
    if summary is None:
        return "No grounded research summary is available for this paper."
    if any(token in lowered for token in ("method", "方法", "approach")):
        return str(getattr(summary, "method_summary", None) or getattr(summary, "core_idea", ""))
    if any(token in lowered for token in ("experiment", "实验", "benchmark")):
        return str(getattr(summary, "experiment_summary", None) or "No experiment summary is available.")
    if any(token in lowered for token in ("limitation", "局限", "risk")):
        limitations = list(getattr(summary, "limitations", []) or [])
        return "; ".join(str(item) for item in limitations) or "No limitations were recorded."
    return str(getattr(summary, "core_idea", None) or getattr(summary, "problem", ""))


def _answer_evidence_refs(analysis: Any, reader_payload: Any, selection: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    summary = getattr(analysis, "summary", None)
    for item in getattr(summary, "evidence_refs", []) or []:
        evidence_id = getattr(item, "evidence_id", None)
        source_ref = getattr(item, "source_ref", None)
        refs.append(str(evidence_id or source_ref))
    evidence = getattr(reader_payload, "evidence", None)
    for item in getattr(evidence, "items", []) or []:
        refs.append(str(getattr(item, "evidence_id", "") or getattr(item, "source_ref", "")))
    selected_refs = selection.get("sourceRefs") or selection.get("source_refs")
    if isinstance(selected_refs, str):
        selected_refs = [selected_refs]
    if selected_refs:
        refs.extend(str(item) for item in selected_refs)
    return _unique_texts(refs)


def _answer_confidence(analysis: Any) -> float:
    summary = getattr(analysis, "summary", None)
    confidence = getattr(summary, "confidence", None)
    try:
        return max(0.0, min(float(confidence), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _quality_gate_failures(quality: Any) -> list[dict[str, Any]]:
    failures = []
    for result in getattr(quality, "gate_results", []) or []:
        if bool(getattr(result, "passed", False)):
            continue
        failures.append(_to_dict(result))
    return failures


def _run_store_service_error(
    error: ResearchRunStoreError,
    *,
    operation: str,
) -> ResearchServiceError:
    return ResearchServiceError(
        "research_run_failed",
        "research run storage operation failed",
        status_code=500,
        details={
            "operation": operation,
            "reason": error.reason_code,
        },
        retryable=error.retryable,
    )


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


_DEFAULT_RESEARCH_RUN_STORE = InMemoryResearchRunStore()


__all__ = [
    "InMemoryResearchRunStore",
    "ResearchAnalyzeInput",
    "ResearchActorInput",
    "ResearchActorAuthorizationError",
    "ResearchApplicationService",
    "ResearchAskInput",
    "ResearchRagAskUseCase",
    "ResearchRunRecord",
    "ResearchRunStore",
    "ResearchServiceError",
    "bind_research_actor_input",
]
