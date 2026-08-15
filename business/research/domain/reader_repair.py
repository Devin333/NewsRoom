from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel
from business.research.domain.common import SourceLineage, bounded_float, require_text, stable_research_id, unique_texts


READER_REPAIR_NAMESPACE = "research.reader_repair"
FORBIDDEN_REPAIR_CANDIDATE_KEYS = frozenset(
    {"next_step", "quality_passed", "write_memory", "publish", "publish_artifact", "promote_skill"}
)
FORBIDDEN_REPAIR_VERIFICATION_KEYS = FORBIDDEN_REPAIR_CANDIDATE_KEYS | frozenset(
    {
        "accepted",
        "decision",
        "passed",
        "quality_verdict",
        "verdict",
    }
)

ReaderIssueType: TypeAlias = Literal[
    "pdf_text_extraction_error",
    "section_boundary_error",
    "missing_required_section",
    "formula_render_error",
    "table_parse_error",
    "figure_caption_mismatch",
    "citation_link_error",
    "reference_parse_error",
    "claim_evidence_alignment_error",
    "reader_payload_schema_error",
    "long_context_truncation_error",
    "language_mixing_error",
    "source_lineage_missing",
    "image_missing_or_broken",
    "latex_source_rendered",
    "formula_placeholder_missing",
]
ReaderRepairMemoryKind: TypeAlias = Literal["episodic", "procedural"]
ReaderRepairStrategyStatus: TypeAlias = Literal[
    "candidate",
    "validated",
    "promoted_memory",
    "skill_candidate_ready",
    "deprecated",
]


class ReaderIssueSignature(PrimitiveModel):
    issue_type: ReaderIssueType
    step_id: str | None = None
    source_format: str | None = None
    symptom_key: str

    @field_validator("symptom_key")
    @classmethod
    def _required_symptom_key(cls, value: str) -> str:
        return require_text(value, "reader issue symptom key")

    @property
    def value(self) -> str:
        parts = [self.issue_type, self.step_id or "unknown_step", self.source_format or "unknown_source", self.symptom_key]
        return ":".join(str(part).strip().casefold().replace(" ", "_") for part in parts)

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["value"] = self.value
        return payload


class ReaderIssue(PrimitiveModel):
    issue_id: str
    paper_id: str
    run_id: str | None = None
    step_id: str | None = None
    issue_type: ReaderIssueType
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    error_signature: str
    symptom: str
    source_refs: list[str] = Field(default_factory=list)
    payload_ref: str | None = None
    detector_evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("issue_id", "paper_id", "error_signature", "symptom")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "reader issue fields")

    @model_validator(mode="after")
    def _normalize_refs(self) -> "ReaderIssue":
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        object.__setattr__(self, "detector_evidence", unique_texts(self.detector_evidence))
        return self


class ReaderRepairCandidate(PrimitiveModel):
    candidate_id: str
    repair_summary: str
    target_region_refs: list[str]
    patch_operations: list[dict[str, Any]]
    expected_effect: str
    risks: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_id", "repair_summary", "expected_effect")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair candidate fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return bounded_float(value, "repair candidate confidence")

    @model_validator(mode="after")
    def _validate_candidate_boundary(self) -> "ReaderRepairCandidate":
        object.__setattr__(self, "target_region_refs", unique_texts(self.target_region_refs))
        object.__setattr__(self, "risks", unique_texts(self.risks))
        if not self.target_region_refs:
            raise ValueError("repair candidate requires target region refs")
        if not self.patch_operations:
            raise ValueError("repair candidate requires patch operations")
        forbidden = set(self.metadata).intersection(FORBIDDEN_REPAIR_CANDIDATE_KEYS)
        for operation in self.patch_operations:
            forbidden.update(str(key) for key in operation if key in FORBIDDEN_REPAIR_CANDIDATE_KEYS)
        if forbidden:
            raise ValueError(f"repair candidate contains forbidden flow-control fields: {sorted(forbidden)}")
        return self


class ReaderRepairVerificationObservation(PrimitiveModel):
    check_id: str
    finding: str
    evidence_refs: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("check_id", "finding")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair verification observation fields")

    @model_validator(mode="after")
    def _remain_observational(self) -> "ReaderRepairVerificationObservation":
        object.__setattr__(self, "evidence_refs", unique_texts(self.evidence_refs))
        if not self.evidence_refs:
            raise ValueError("repair verification observation requires evidence refs")
        forbidden = _forbidden_nested_keys(
            self.metadata,
            FORBIDDEN_REPAIR_VERIFICATION_KEYS,
        )
        if forbidden:
            raise ValueError(
                "repair verification observation contains decision fields: "
                f"{sorted(forbidden)}"
            )
        return self


class ReaderRepairVerificationCandidate(PrimitiveModel):
    candidate_id: str
    observations: list[ReaderRepairVerificationObservation]
    source_refs: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("candidate_id")
    @classmethod
    def _required_candidate_id(cls, value: str) -> str:
        return require_text(value, "repair verification candidate id")

    @model_validator(mode="after")
    def _remain_observational(self) -> "ReaderRepairVerificationCandidate":
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        if not self.observations:
            raise ValueError("repair verification candidate requires observations")
        if not self.source_refs:
            raise ValueError("repair verification candidate requires source refs")
        forbidden = _forbidden_nested_keys(
            self.metadata,
            FORBIDDEN_REPAIR_VERIFICATION_KEYS,
        )
        if forbidden:
            raise ValueError(
                "repair verification candidate contains decision fields: "
                f"{sorted(forbidden)}"
            )
        return self


class ReaderRepairAttempt(PrimitiveModel):
    attempt_id: str
    issue_id: str
    proposer_subagent_id: str
    verifier_subagent_id: str
    candidate: ReaderRepairCandidate
    context_snapshot_ref: str
    handoff_ref: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attempt_id", "issue_id", "proposer_subagent_id", "verifier_subagent_id", "context_snapshot_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair attempt fields")

    @model_validator(mode="after")
    def _require_isolated_roles(self) -> "ReaderRepairAttempt":
        if self.proposer_subagent_id == self.verifier_subagent_id:
            raise ValueError("repair proposer and verifier must be isolated subagents")
        if self.metadata.get("verifier_saw_proposer_private_notes"):
            raise ValueError("repair verifier must not see proposer private notes")
        return self


class ReaderRepairResult(PrimitiveModel):
    result_id: str
    attempt_id: str
    successful: bool
    verification_results: list[dict[str, Any]]
    payload_before_ref: str
    payload_after_ref: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("result_id", "attempt_id", "payload_before_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair result fields")

    @model_validator(mode="after")
    def _normalize_result(self) -> "ReaderRepairResult":
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        if self.successful and not self.payload_after_ref:
            raise ValueError("successful repair result requires payload_after_ref")
        if not self.verification_results:
            raise ValueError("repair result requires verification results")
        return self


class ReaderRepairCase(PrimitiveModel):
    repair_case_id: str
    issue: ReaderIssue
    memory_kind: ReaderRepairMemoryKind = "episodic"
    repair_strategy: str
    repair_prompt_ref: str | None = None
    repair_attempt_refs: list[str] = Field(default_factory=list)
    successful: bool
    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    payload_before_ref: str
    payload_after_ref: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repair_case_id", "repair_strategy", "payload_before_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair case fields")

    @model_validator(mode="after")
    def _normalize_refs(self) -> "ReaderRepairCase":
        object.__setattr__(self, "repair_attempt_refs", unique_texts(self.repair_attempt_refs))
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs or self.issue.source_refs))
        object.__setattr__(self, "constraints", unique_texts(self.constraints))
        object.__setattr__(self, "tags", unique_texts(self.tags))
        if self.successful and not self.payload_after_ref:
            raise ValueError("successful repair case requires payload_after_ref")
        if not self.verification_results:
            object.__setattr__(
                self,
                "verification_results",
                [{"gate_name": "ReaderRepairRecordedOutcomeGate", "passed": bool(self.successful)}],
            )
        return self


class ReaderRepairStrategy(PrimitiveModel):
    strategy_id: str
    issue_type: ReaderIssueType
    applicability: str
    steps: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    known_failures: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source_case_refs: list[str] = Field(default_factory=list)
    status: ReaderRepairStrategyStatus = "candidate"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("strategy_id", "applicability")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair strategy fields")

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: float) -> float:
        return bounded_float(value, "repair strategy confidence")

    @model_validator(mode="after")
    def _normalize_lists(self) -> "ReaderRepairStrategy":
        object.__setattr__(self, "steps", unique_texts(self.steps))
        object.__setattr__(self, "constraints", unique_texts(self.constraints))
        object.__setattr__(self, "known_failures", unique_texts(self.known_failures))
        object.__setattr__(self, "evidence_requirements", unique_texts(self.evidence_requirements))
        object.__setattr__(self, "source_case_refs", unique_texts(self.source_case_refs))
        if not self.steps:
            raise ValueError("repair strategy requires steps")
        return self


class ReaderRepairMemoryQuery(PrimitiveModel):
    query_id: str
    namespace: str = READER_REPAIR_NAMESPACE
    issue_type: ReaderIssueType
    error_signature: str
    step_id: str | None = None
    paper_domain: str | None = None
    source_format: str | None = None
    symptom: str
    memory_kinds: list[ReaderRepairMemoryKind] = Field(default_factory=lambda: ["episodic", "procedural"])
    source_refs: list[str] = Field(default_factory=list)
    max_successful_cases: int = 4
    max_failed_cases: int = 4
    max_strategies: int = 3
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query_id", "namespace", "error_signature", "symptom")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair memory query fields")

    @model_validator(mode="after")
    def _validate_query(self) -> "ReaderRepairMemoryQuery":
        if self.namespace != READER_REPAIR_NAMESPACE:
            raise ValueError("reader repair memory query must use research.reader_repair namespace")
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        object.__setattr__(self, "memory_kinds", unique_texts(self.memory_kinds))
        for field_name in ("max_successful_cases", "max_failed_cases", "max_strategies"):
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        return self

    @classmethod
    def from_issue(cls, issue: ReaderIssue, *, source_format: str | None = None) -> "ReaderRepairMemoryQuery":
        return cls(
            query_id=stable_research_id("reader_repair_query", issue.paper_id, issue.error_signature),
            issue_type=issue.issue_type,
            error_signature=issue.error_signature,
            step_id=issue.step_id,
            source_format=source_format or issue.metadata.get("source_format"),
            symptom=issue.symptom,
            source_refs=issue.source_refs,
            metadata={"issue_id": issue.issue_id, "run_id": issue.run_id},
        )


class ReaderRepairRAGPolicy(PrimitiveModel):
    policy_id: str
    namespace: str = READER_REPAIR_NAMESPACE
    allowed_memory_namespaces: list[str] = Field(default_factory=lambda: [READER_REPAIR_NAMESPACE])
    allowed_corpora: list[str] = Field(default_factory=lambda: ["current_paper_source", "current_reader_payload_artifacts"])
    operations: list[str] = Field(
        default_factory=lambda: ["recall_memory", "read_source", "verify_source", "assemble_context"]
    )
    budget: dict[str, int] = Field(
        default_factory=lambda: {
            "max_rounds": 3,
            "max_queries": 6,
            "max_memory_hits": 8,
            "max_source_reads": 8,
            "max_context_items": 8,
        }
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("policy_id", "namespace")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair RAG policy fields")

    @model_validator(mode="after")
    def _validate_policy(self) -> "ReaderRepairRAGPolicy":
        if self.namespace != READER_REPAIR_NAMESPACE:
            raise ValueError("reader repair RAG policy must use research.reader_repair namespace")
        if set(self.allowed_memory_namespaces) - {READER_REPAIR_NAMESPACE}:
            raise ValueError("reader repair RAG policy cannot access unauthorized memory namespaces")
        object.__setattr__(self, "allowed_memory_namespaces", unique_texts(self.allowed_memory_namespaces))
        object.__setattr__(self, "allowed_corpora", unique_texts(self.allowed_corpora))
        object.__setattr__(self, "operations", unique_texts(self.operations))
        return self


class ReaderRepairContextPack(PrimitiveModel):
    context_id: str
    issue: ReaderIssue
    recalled_cases: list[ReaderRepairCase] = Field(default_factory=list)
    candidate_strategies: list[ReaderRepairStrategy] = Field(default_factory=list)
    similar_successful_cases: list[ReaderRepairCase] = Field(default_factory=list)
    similar_failed_cases: list[ReaderRepairCase] = Field(default_factory=list)
    promoted_strategies: list[ReaderRepairStrategy] = Field(default_factory=list)
    repair_constraints: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_lineage: SourceLineage
    rag_session_id: str | None = None
    accepted_memory_refs: list[str] = Field(default_factory=list)
    rejected_memory_refs: list[str] = Field(default_factory=list)
    failure_case_gap_report: dict[str, Any] = Field(default_factory=dict)
    budget_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("context_id")
    @classmethod
    def _required_context_id(cls, value: str) -> str:
        return require_text(value, "repair context id")

    @model_validator(mode="after")
    def _require_lineage(self) -> "ReaderRepairContextPack":
        self.source_lineage.require_refs("reader repair context requires source lineage")
        successful = [case for case in [*self.similar_successful_cases, *self.recalled_cases] if case.successful]
        failed = [case for case in [*self.similar_failed_cases, *self.recalled_cases] if not case.successful]
        strategies = [*self.promoted_strategies, *self.candidate_strategies]
        object.__setattr__(self, "similar_successful_cases", _unique_cases(successful))
        object.__setattr__(self, "similar_failed_cases", _unique_cases(failed))
        object.__setattr__(self, "promoted_strategies", _unique_strategies(strategies))
        object.__setattr__(self, "recalled_cases", _unique_cases([*successful, *failed]))
        object.__setattr__(self, "candidate_strategies", _unique_strategies(strategies))
        object.__setattr__(self, "repair_constraints", unique_texts(self.repair_constraints))
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs or self.source_lineage.source_refs))
        object.__setattr__(self, "accepted_memory_refs", unique_texts(self.accepted_memory_refs))
        object.__setattr__(self, "rejected_memory_refs", unique_texts(self.rejected_memory_refs))
        if not self.similar_failed_cases and "no_failed_cases_available" not in self.failure_case_gap_report:
            object.__setattr__(self, "failure_case_gap_report", {"no_failed_cases_available": True})
        return self


class ReaderRepairSkillCandidateSeed(PrimitiveModel):
    seed_id: str
    strategy: ReaderRepairStrategy
    skill_name: str = "research-reader-repair"
    experience_refs: list[str] = Field(default_factory=list)
    patch_objective: str
    publishes_skill: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("seed_id", "skill_name", "patch_objective")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "repair skill candidate seed fields")

    @model_validator(mode="after")
    def _must_not_publish(self) -> "ReaderRepairSkillCandidateSeed":
        if self.publishes_skill:
            raise ValueError("reader repair strategy seed must not publish an active skill")
        object.__setattr__(self, "experience_refs", unique_texts(self.experience_refs))
        return self


def _unique_cases(cases: list[ReaderRepairCase]) -> list[ReaderRepairCase]:
    seen: set[str] = set()
    result: list[ReaderRepairCase] = []
    for case in cases:
        if case.repair_case_id not in seen:
            seen.add(case.repair_case_id)
            result.append(case)
    return result


def _unique_strategies(strategies: list[ReaderRepairStrategy]) -> list[ReaderRepairStrategy]:
    seen: set[str] = set()
    result: list[ReaderRepairStrategy] = []
    for strategy in strategies:
        if strategy.strategy_id not in seen:
            seen.add(strategy.strategy_id)
            result.append(strategy)
    return result


def _forbidden_nested_keys(value: Any, forbidden_keys: frozenset[str]) -> set[str]:
    matches: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                normalized = str(key).casefold()
                if normalized in forbidden_keys:
                    matches.add(normalized)
                pending.append(item)
        elif isinstance(current, list | tuple):
            pending.extend(current)
    return matches


__all__ = [
    "FORBIDDEN_REPAIR_CANDIDATE_KEYS",
    "FORBIDDEN_REPAIR_VERIFICATION_KEYS",
    "READER_REPAIR_NAMESPACE",
    "ReaderIssue",
    "ReaderIssueSignature",
    "ReaderIssueType",
    "ReaderRepairAttempt",
    "ReaderRepairCandidate",
    "ReaderRepairCase",
    "ReaderRepairContextPack",
    "ReaderRepairMemoryKind",
    "ReaderRepairMemoryQuery",
    "ReaderRepairRAGPolicy",
    "ReaderRepairResult",
    "ReaderRepairSkillCandidateSeed",
    "ReaderRepairStrategy",
    "ReaderRepairStrategyStatus",
    "ReaderRepairVerificationCandidate",
    "ReaderRepairVerificationObservation",
]
