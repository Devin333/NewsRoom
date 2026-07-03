from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.memory.ports import MemoryPort
from framework.harness.mcp.policy import MCPToolRequest
from framework.harness.rag.context_pack_assembler import RAGContextPackAssembler
from framework.harness.rag.gates import RAGGateSuite, RAGGateResult, failed_gate_dicts
from framework.harness.rag.models import (
    EvidenceCandidate,
    RAGBudget,
    RAGBudgetSnapshot,
    RAGContextPack,
    RAGSessionRequest,
    RAGSessionSpec,
    RAGSessionStatus,
    RAGTranscript,
    RetrievalGoal,
    RetrievalOperation,
    RetrievalPlanCandidate,
    RetrievalStepResult,
    RetrievalStepSpec,
)
from framework.harness.rag.planner import DeterministicRAGPlanner, RAGPlanner
from framework.harness.rag.policy import RAGDecision, RAGDecisionType, RAGExecutionPolicy, normalize_query
from framework.harness.rag.source_verifier import SourceVerifier
from framework.harness.retrieval.ports import RetrievalPort
from framework.harness.retrieval.request import RetrievalRequest
from framework.shared.json import to_jsonable


@runtime_checkable
class RAGSessionController(Protocol):
    def build_context_pack(self, request: RAGSessionRequest) -> RAGContextPack:
        ...


@dataclass(frozen=True)
class RAGSessionResult:
    status: RAGSessionStatus
    context_pack: RAGContextPack | None
    transcript: RAGTranscript
    decision: RAGDecision

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "context_pack": self.context_pack.to_dict() if self.context_pack else None,
            "transcript": self.transcript.to_dict(),
            "decision": self.decision.to_dict(),
        }


@dataclass
class RAGSessionState:
    spec: RAGSessionSpec
    budget_snapshot: RAGBudgetSnapshot = field(default_factory=RAGBudgetSnapshot)
    executed_queries: set[str] = field(default_factory=set)
    accepted_evidence: list[EvidenceCandidate] = field(default_factory=list)
    rejected_evidence: list[EvidenceCandidate] = field(default_factory=list)
    conflicting_evidence: list[EvidenceCandidate] = field(default_factory=list)
    memory_context: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    gap_report: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


class BoundedRAGSessionController(RAGSessionController):
    def __init__(
        self,
        *,
        retrieval: RetrievalPort,
        memory: MemoryPort | None = None,
        tool_port: Any | None = None,
        planner: RAGPlanner | None = None,
        source_verifier: SourceVerifier | None = None,
        context_pack_assembler: RAGContextPackAssembler | None = None,
        gates: RAGGateSuite | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.memory = memory
        self.tool_port = tool_port
        self.planner = planner or DeterministicRAGPlanner()
        self.source_verifier = source_verifier or SourceVerifier()
        self.context_pack_assembler = context_pack_assembler or RAGContextPackAssembler()
        self.gates = gates or RAGGateSuite()

    def build_context_pack(self, request: RAGSessionRequest) -> RAGContextPack:
        spec = _spec_from_legacy_request(request)
        return self.run(spec).context_pack or _empty_context_pack(spec)

    def run(self, spec: RAGSessionSpec) -> RAGSessionResult:
        policy = RAGExecutionPolicy.from_session_spec(spec)
        state = RAGSessionState(spec=spec, gap_report={"missing_evidence_types": list(spec.goal.required_evidence_types)})
        self._event(
            state,
            "rag_session_started",
            {
                "session": spec.to_dict(),
                "policy": policy.to_dict(),
            },
        )
        decision = RAGDecision(RAGDecisionType.CONTINUE_RETRIEVAL, "session started", budget_snapshot=state.budget_snapshot)
        status = RAGSessionStatus.INSUFFICIENT_EVIDENCE
        pack: RAGContextPack | None = None

        for round_index in range(spec.budget.max_rounds):
            state.budget_snapshot = state.budget_snapshot.with_usage(rounds=1)
            budget_gate = self.gates.budget.evaluate(state.budget_snapshot, policy)
            if not budget_gate.passed:
                decision = self._halt(state, "round budget exhausted", (budget_gate,))
                status = RAGSessionStatus.HALTED
                break

            plan = self.planner.plan(
                spec,
                round_index=round_index,
                gap_report=state.gap_report,
                executed_queries=tuple(sorted(state.executed_queries)),
            )
            self._event(state, "rag_plan_candidate_created", {"round_index": round_index, "plan": plan.to_dict()})
            projected = _add_snapshots(state.budget_snapshot, policy.projected_usage(plan))
            plan_results = self.gates.verify_plan(
                plan,
                spec=spec,
                policy=policy,
                executed_queries=state.executed_queries,
                projected_snapshot=projected,
            )
            self._event(state, "rag_plan_verified", {"round_index": round_index, "gate_results": _results(plan_results)})
            if any(result.passed is False for result in plan_results):
                decision = self._handle_plan_failure(state, plan_results)
                if decision.decision_type == RAGDecisionType.REPLAN_QUERIES:
                    continue
                status = RAGSessionStatus.HALTED
                break

            step_results = self._execute_plan(plan, state, policy)
            state.artifact_refs.extend(_dedupe_texts(ref for result in step_results for ref in result.artifact_refs))
            for step_result in step_results:
                self._event(state, "rag_step_executed", step_result.to_dict())
            verification = self.source_verifier.verify(
                tuple(_result_evidence(step_results)),
                policy=policy,
                question=spec.goal.question,
            )
            state.accepted_evidence.extend(_dedupe_evidence(verification.accepted, state.accepted_evidence))
            state.rejected_evidence.extend(_dedupe_evidence(verification.rejected, state.rejected_evidence))
            state.conflicting_evidence.extend(_dedupe_evidence(verification.conflicting, state.conflicting_evidence))
            self._event(state, "rag_source_verified", verification.to_dict())

            source_results = self.gates.verify_sources(
                tuple(state.accepted_evidence),
                spec=spec,
                policy=policy,
                memory_context=tuple(state.memory_context),
            )
            self._record_gate_failures(state, source_results)
            state.gap_report = _gap_report(
                spec,
                tuple(state.accepted_evidence),
                source_results,
                rejected=tuple(state.rejected_evidence),
            )
            if _coverage_passed(source_results):
                decision = RAGDecision(
                    RAGDecisionType.ASSEMBLE_CONTEXT,
                    "required evidence coverage satisfied",
                    gate_results=_results(source_results),
                    budget_snapshot=state.budget_snapshot,
                )
                break
            if self._can_replan(state, spec):
                state.budget_snapshot = state.budget_snapshot.with_usage(replans=1)
                decision = RAGDecision(
                    RAGDecisionType.REPLAN_QUERIES,
                    "evidence coverage is incomplete and replan budget remains",
                    gate_results=_results(source_results),
                    budget_snapshot=state.budget_snapshot,
                    metadata={"gap_report": to_jsonable(state.gap_report)},
                )
                self._event(state, "rag_replanned", decision.to_dict())
                continue
            decision = RAGDecision(
                RAGDecisionType.INSUFFICIENT_EVIDENCE,
                "evidence coverage is incomplete and no controlled replan remains",
                gate_results=_results(source_results),
                budget_snapshot=state.budget_snapshot,
                metadata={"gap_report": to_jsonable(state.gap_report)},
            )
            status = RAGSessionStatus.INSUFFICIENT_EVIDENCE
            break

        if decision.decision_type == RAGDecisionType.ASSEMBLE_CONTEXT:
            pack = self.context_pack_assembler.assemble(
                spec=spec,
                accepted_evidence=tuple(state.accepted_evidence[: spec.budget.max_context_items]),
                rejected_evidence=tuple(state.rejected_evidence),
                conflicting_evidence=tuple(state.conflicting_evidence),
                memory_context=tuple(state.memory_context[: spec.budget.max_memory_hits]),
                artifact_refs=_dedupe_texts(state.artifact_refs),
                gap_report=state.gap_report,
                budget_snapshot=state.budget_snapshot,
                policy=policy,
            )
            pack_results = self.gates.verify_context_pack(pack, policy=policy)
            self._event(state, "rag_context_pack_assembled", {"pack": pack.to_dict(), "gate_results": _results(pack_results)})
            self._record_gate_failures(state, pack_results)
            if all(result.passed for result in pack_results):
                decision = RAGDecision(
                    RAGDecisionType.RETURN_CONTEXT_PACK,
                    "context pack verified",
                    gate_results=_results(pack_results),
                    budget_snapshot=pack.budget_snapshot,
                    metadata={"context_pack_id": pack.pack_id},
                )
                status = RAGSessionStatus.SUCCEEDED
                self._event(state, "rag_context_pack_returned", decision.to_dict())
            else:
                decision = self._halt(state, "context pack gate failed", pack_results)
                status = RAGSessionStatus.HALTED
                pack = None
        elif decision.decision_type == RAGDecisionType.HALTED:
            status = RAGSessionStatus.HALTED
        else:
            self._event(state, "rag_halted", decision.to_dict())

        transcript = RAGTranscript(
            transcript_id=f"rag-transcript://{spec.session_id}/{uuid4().hex[:8]}",
            session_id=spec.session_id,
            events=tuple(state.events),
            status=status,
        )
        return RAGSessionResult(status=status, context_pack=pack, transcript=transcript, decision=decision)

    def _execute_plan(
        self,
        plan: RetrievalPlanCandidate,
        state: RAGSessionState,
        policy: RAGExecutionPolicy,
    ) -> tuple[RetrievalStepResult, ...]:
        results: list[RetrievalStepResult] = []
        for step in plan.steps:
            if step.operation == RetrievalOperation.SEARCH_CORPUS:
                result = self._execute_search(step, state)
                state.budget_snapshot = state.budget_snapshot.with_usage(queries=1, worker_calls=1)
            elif step.operation == RetrievalOperation.READ_SOURCE:
                result = self._execute_source_read(step, state)
                state.budget_snapshot = state.budget_snapshot.with_usage(
                    source_reads=max(len(step.source_refs), step.max_source_reads, 1),
                    worker_calls=1,
                )
            elif step.operation == RetrievalOperation.RECALL_MEMORY:
                result = self._execute_memory_recall(step, state)
                state.budget_snapshot = state.budget_snapshot.with_usage(
                    memory_hits=len(result.memory_refs),
                    worker_calls=1,
                )
            else:
                result = RetrievalStepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    errors=(f"operation {step.operation.value} is verified but not directly executed",),
                )
            budget_result = self.gates.budget.evaluate(state.budget_snapshot, policy)
            results.append(result)
            if not budget_result.passed:
                self._event(state, "rag_gate_failed", budget_result.to_dict())
                break
        return tuple(results)

    def _execute_search(self, step: RetrievalStepSpec, state: RAGSessionState) -> RetrievalStepResult:
        query = str(step.query or "")
        state.executed_queries.add(normalize_query(query))
        collection = self.retrieval.retrieve(
            RetrievalRequest(
                query=query,
                scope=step.corpus or "default",
                filters=dict(step.metadata.get("filters", {})),
                limit=max(step.max_results, 1),
                context_refs=state.spec.goal.known_context_refs,
                metadata={"rag_step_id": step.step_id, **dict(step.metadata)},
            )
        )
        evidence_type = str(step.metadata.get("evidence_type") or _default_evidence_type(state.spec))
        artifact_refs = (collection.request_ref,) if collection.request_ref else ()
        candidates = tuple(
            EvidenceCandidate.from_evidence_pack(
                pack,
                evidence_type=evidence_type,
                artifact_refs=artifact_refs,
            )
            for pack in collection.packs
        )
        return RetrievalStepResult(
            step_id=step.step_id,
            operation=step.operation,
            items=candidates,
            source_refs=tuple(ref for item in candidates for ref in (item.source_ref, *item.span_refs)),
            artifact_refs=artifact_refs,
            metadata=collection.metadata,
        )

    def _execute_source_read(self, step: RetrievalStepSpec, state: RAGSessionState) -> RetrievalStepResult:
        if self.tool_port is not None and step.metadata.get("tool_name"):
            request = MCPToolRequest(
                tool_name=str(step.metadata["tool_name"]),
                arguments={"source_refs": list(step.source_refs), "query": step.query},
                approved=bool(step.metadata.get("approved", False)),
                timeout_seconds=step.timeout_seconds,
                metadata={"rag_step_id": step.step_id},
            )
            result = self.tool_port.call_tool(request)
            errors = () if result.status.value == "succeeded" else (result.error or "tool call failed",)
            return RetrievalStepResult(
                step_id=step.step_id,
                operation=step.operation,
                source_refs=step.source_refs,
                artifact_refs=tuple(result.artifacts),
                errors=errors,
                metadata={"tool_result": result.to_dict()},
            )
        return RetrievalStepResult(
            step_id=step.step_id,
            operation=step.operation,
            source_refs=step.source_refs,
            metadata={"read_mode": "source_refs_only"},
        )

    def _execute_memory_recall(self, step: RetrievalStepSpec, state: RAGSessionState) -> RetrievalStepResult:
        if self.memory is None:
            return RetrievalStepResult(
                step_id=step.step_id,
                operation=step.operation,
                errors=("memory port is not configured",),
            )
        hits = self.memory.recall(
            {
                "query": step.query,
                "namespace": step.memory_namespace,
                "limit": step.max_results,
                "goal": state.spec.goal.to_dict(),
            }
        )
        accepted_hits = []
        memory_refs = []
        for hit in hits[: step.max_results]:
            if str(hit.get("namespace")) != step.memory_namespace:
                continue
            accepted_hits.append(dict(hit))
            memory_refs.append(str(hit.get("memory_ref", hit.get("ref", f"memory://{len(memory_refs) + 1}"))))
        state.memory_context.extend(accepted_hits)
        return RetrievalStepResult(
            step_id=step.step_id,
            operation=step.operation,
            items=tuple(accepted_hits),
            memory_refs=tuple(memory_refs),
            metadata={"namespace": step.memory_namespace, "returned": len(hits), "accepted": len(accepted_hits)},
        )

    def _handle_plan_failure(self, state: RAGSessionState, results: tuple[RAGGateResult, ...]) -> RAGDecision:
        self._record_gate_failures(state, results)
        if state.budget_snapshot.replans_used < state.spec.budget.max_replans:
            state.budget_snapshot = state.budget_snapshot.with_usage(replans=1)
            decision = RAGDecision(
                RAGDecisionType.REPLAN_QUERIES,
                "plan gate failed and replan budget remains",
                gate_results=failed_gate_dicts(results),
                budget_snapshot=state.budget_snapshot,
            )
            self._event(state, "rag_replanned", decision.to_dict())
            return decision
        return self._halt(state, "plan gate failed and no replan budget remains", results)

    def _can_replan(self, state: RAGSessionState, spec: RAGSessionSpec) -> bool:
        return (
            state.budget_snapshot.replans_used < spec.budget.max_replans
            and state.budget_snapshot.rounds_used < spec.budget.max_rounds
        )

    def _halt(self, state: RAGSessionState, reason: str, results: tuple[RAGGateResult, ...]) -> RAGDecision:
        decision = RAGDecision(
            RAGDecisionType.HALTED,
            reason,
            gate_results=failed_gate_dicts(results) or _results(results),
            budget_snapshot=state.budget_snapshot,
        )
        self._event(state, "rag_halted", decision.to_dict())
        return decision

    def _record_gate_failures(self, state: RAGSessionState, results: tuple[RAGGateResult, ...]) -> None:
        for result in results:
            if not result.passed:
                self._event(state, "rag_gate_failed", result.to_dict())

    def _event(self, state: RAGSessionState, event_type: str, payload: dict[str, Any]) -> None:
        state.events.append({"event_type": event_type, "payload": to_jsonable(payload)})


def _spec_from_legacy_request(request: RAGSessionRequest) -> RAGSessionSpec:
    budget = RAGBudget.safe_default()
    budget = RAGBudget(
        max_rounds=request.max_rounds,
        max_replans=max(request.max_rounds - 1, 0),
        max_queries=budget.max_queries,
        max_source_reads=budget.max_source_reads,
        max_memory_hits=budget.max_memory_hits,
        max_context_items=budget.max_context_items,
        max_context_tokens=budget.max_context_tokens,
        max_worker_calls=budget.max_worker_calls,
    )
    return RAGSessionSpec(
        session_id=str(request.metadata.get("session_id", "legacy-rag-session")),
        run_id=str(request.metadata.get("run_id", "legacy-run")),
        workflow_id=str(request.metadata.get("workflow_id", "legacy-workflow")),
        step_id=str(request.metadata.get("step_id", "legacy-step")),
        goal=RetrievalGoal(
            goal_id=str(request.metadata.get("goal_id", "legacy-goal")),
            question=request.query,
            required_evidence_types=tuple(request.metadata.get("required_evidence_types", ("research_evidence",))),
            known_context_refs=request.context_refs,
        ),
        allowed_corpora=tuple(request.metadata.get("allowed_corpora", ("research-corpus",))),
        allowed_memory_namespaces=tuple(request.metadata.get("allowed_memory_namespaces", ("research.public",))),
        allowed_tools=tuple(request.metadata.get("allowed_tools", ("retrieval.read_source",))),
        budget=budget,
        metadata={"legacy_request": request.to_dict()},
    )


def _add_snapshots(current: RAGBudgetSnapshot, projected: RAGBudgetSnapshot) -> RAGBudgetSnapshot:
    return current.with_usage(
        rounds=0,
        replans=0,
        queries=projected.queries_used,
        source_reads=projected.source_reads_used,
        memory_hits=projected.memory_hits_used,
        context_items=projected.context_items_used,
        context_tokens=projected.context_tokens_used,
        worker_calls=projected.worker_calls_used,
    )


def _result_evidence(results: tuple[RetrievalStepResult, ...]) -> tuple[EvidenceCandidate, ...]:
    evidence: list[EvidenceCandidate] = []
    for result in results:
        for item in result.items:
            if isinstance(item, EvidenceCandidate):
                evidence.append(item)
    return tuple(evidence)


def _dedupe_evidence(
    candidates: tuple[EvidenceCandidate, ...],
    existing: list[EvidenceCandidate],
) -> tuple[EvidenceCandidate, ...]:
    seen = {item.evidence_id for item in existing}
    deduped = []
    for candidate in candidates:
        if candidate.evidence_id in seen:
            continue
        seen.add(candidate.evidence_id)
        deduped.append(candidate)
    return tuple(deduped)


def _dedupe_texts(values: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _coverage_passed(results: tuple[RAGGateResult, ...]) -> bool:
    return all(result.passed for result in results if result.gate_name in {"rag_evidence_coverage", "rag_lineage", "rag_source_quality", "rag_memory_relevance"})


def _gap_report(
    spec: RAGSessionSpec,
    accepted: tuple[EvidenceCandidate, ...],
    results: tuple[RAGGateResult, ...],
    rejected: tuple[EvidenceCandidate, ...] = (),
) -> dict[str, Any]:
    present = {item.evidence_type for item in accepted}
    missing = [item for item in spec.goal.required_evidence_types if item not in present]
    return {
        "missing_evidence_types": missing,
        "accepted_evidence_ids": [item.evidence_id for item in accepted],
        "gate_results": _results(results),
        "rejection_summary": _rejection_summary(rejected),
    }


def _results(results: tuple[RAGGateResult, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(result.to_dict() for result in results)


def _rejection_summary(rejected: tuple[EvidenceCandidate, ...]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for candidate in rejected:
        reason = str(candidate.metadata.get("rejection_reason") or "source_verification_failed")
        entry = summary.setdefault(reason, {"count": 0, "evidence_types": {}})
        entry["count"] += 1
        evidence_types = entry["evidence_types"]
        evidence_types[candidate.evidence_type] = evidence_types.get(candidate.evidence_type, 0) + 1
    return summary


def _default_evidence_type(spec: RAGSessionSpec) -> str:
    return spec.goal.required_evidence_types[0]


def _empty_context_pack(spec: RAGSessionSpec) -> RAGContextPack:
    return RAGContextPack(
        pack_id=f"rag-context://{spec.session_id}/empty",
        query=spec.goal.question,
        goal=spec.goal,
        gap_report={"missing_evidence_types": list(spec.goal.required_evidence_types)},
        budget_snapshot=RAGBudgetSnapshot(),
        assembly_summary="No verified context pack was produced.",
        metadata={"status": RAGSessionStatus.INSUFFICIENT_EVIDENCE.value},
    )


__all__ = [
    "BoundedRAGSessionController",
    "RAGSessionController",
    "RAGSessionResult",
    "RAGSessionState",
]
