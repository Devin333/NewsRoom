from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from typing import Any

from infrastructure.storage.artifacts import ArtifactRef, FilesystemArtifactStore


_RAW_SOURCE_TYPES = {
    "raw_items",
    "source_artifacts",
    "source_errors",
    "source_item",
    "source_error",
    "skipped_sources",
    "failed_sources",
}
_REPORT_TYPES = {"report", "report_json", "report_markdown", "blocked_report"}
_EVIDENCE_TYPES = {"evidence", "evidence_bundle", "evidence_scores", "evidence_source_map"}
_MEMORY_TYPES = {"memory_document", "memory_documents", "report_sections", "evidence_items"}
_EVENT_TYPES = {"events", "workflow_events", "quality_events", "source_events"}
_CONVERSATION_TYPES = {
    "agent_conversation",
    "agent_conversations",
    "agent_conversation_messages",
    "agent_conversation_state",
}
_MANIFEST_TYPES = {"manifest", "workflow_spec", "request", "pause"}
_LLM_TYPE_PARTS = ("llm", "model", "prompt", "completion")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RetentionPolicy:
    raw_source_retention_days: int = 30
    llm_artifact_retention_days: int = 90
    run_artifact_retention_days: int = 180
    report_retention_days: int | None = None
    evidence_retention_days: int | None = None
    vector_retention_days: int | None = None
    event_retention_days: int | None = None
    conversation_retention_days: int | None = None

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if value is not None and int(value) < 0:
                raise ValueError(f"{name} must be greater than or equal to zero")

    def to_dict(self) -> dict[str, int | None]:
        return {
            "raw_source_retention_days": self.raw_source_retention_days,
            "llm_artifact_retention_days": self.llm_artifact_retention_days,
            "run_artifact_retention_days": self.run_artifact_retention_days,
            "report_retention_days": self.report_retention_days,
            "evidence_retention_days": self.evidence_retention_days,
            "vector_retention_days": self.vector_retention_days,
            "event_retention_days": self.event_retention_days,
            "conversation_retention_days": self.conversation_retention_days,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RetentionPolicy:
        return cls(
            raw_source_retention_days=int(payload.get("raw_source_retention_days", 30)),
            llm_artifact_retention_days=int(payload.get("llm_artifact_retention_days", 90)),
            run_artifact_retention_days=int(payload.get("run_artifact_retention_days", 180)),
            report_retention_days=_optional_int(payload.get("report_retention_days")),
            evidence_retention_days=_optional_int(payload.get("evidence_retention_days")),
            vector_retention_days=_optional_int(payload.get("vector_retention_days")),
            event_retention_days=_optional_int(payload.get("event_retention_days")),
            conversation_retention_days=_optional_int(payload.get("conversation_retention_days")),
        )

    def retention_days_for(self, artifact_type: str) -> int | None:
        normalized = artifact_type.casefold()
        if normalized in _RAW_SOURCE_TYPES or normalized.startswith("source_"):
            return self.raw_source_retention_days
        if normalized in _REPORT_TYPES:
            return self.report_retention_days
        if normalized in _EVIDENCE_TYPES:
            return self.evidence_retention_days
        if normalized in _MEMORY_TYPES or normalized.startswith("vector_"):
            return self.vector_retention_days
        if normalized in _EVENT_TYPES:
            return self.event_retention_days if self.event_retention_days is not None else self.run_artifact_retention_days
        if normalized in _CONVERSATION_TYPES:
            return self.conversation_retention_days if self.conversation_retention_days is not None else self.run_artifact_retention_days
        if normalized in _MANIFEST_TYPES:
            return None
        if any(part in normalized for part in _LLM_TYPE_PARTS):
            return self.llm_artifact_retention_days
        return self.run_artifact_retention_days


@dataclass(frozen=True)
class RetentionDecision:
    artifact_ref: ArtifactRef
    action: str
    reason: str
    expires_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_ref": self.artifact_ref.to_dict(),
            "action": self.action,
            "reason": self.reason,
            "expires_at": (
                self.expires_at.isoformat().replace("+00:00", "Z") if self.expires_at else None
            ),
        }


@dataclass(frozen=True)
class RetentionPlan:
    generated_at: datetime
    decisions: list[RetentionDecision] = field(default_factory=list)

    @property
    def delete_decisions(self) -> list[RetentionDecision]:
        return [decision for decision in self.decisions if decision.action == "delete"]

    @property
    def keep_decisions(self) -> list[RetentionDecision]:
        return [decision for decision in self.decisions if decision.action == "keep"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
            "delete_count": len(self.delete_decisions),
            "keep_count": len(self.keep_decisions),
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


class ArtifactRetentionPlanner:
    def __init__(self, policy: RetentionPolicy | None = None) -> None:
        self.policy = policy or RetentionPolicy()

    def plan(self, refs: list[ArtifactRef], *, now: datetime | None = None) -> RetentionPlan:
        actual_now = (now or _utc_now()).astimezone(UTC)
        decisions = [self._decision(ref, now=actual_now) for ref in refs]
        return RetentionPlan(generated_at=actual_now, decisions=decisions)

    def _decision(self, ref: ArtifactRef, *, now: datetime) -> RetentionDecision:
        retention_days = self.policy.retention_days_for(ref.artifact_type)
        if retention_days is None:
            return RetentionDecision(ref, "keep", "retention_indefinite")
        expires_at = ref.created_at.astimezone(UTC) + timedelta(days=retention_days)
        if expires_at <= now:
            return RetentionDecision(ref, "delete", "retention_expired", expires_at)
        return RetentionDecision(ref, "keep", "retention_active", expires_at)


class LocalArtifactRetentionExecutor:
    def __init__(self, artifact_root: str) -> None:
        self.artifact_store = FilesystemArtifactStore(artifact_root)

    def delete_expired(self, plan: RetentionPlan, *, dry_run: bool = False) -> list[ArtifactRef]:
        selected = []
        for decision in plan.delete_decisions:
            if not dry_run:
                self.artifact_store.delete(decision.artifact_ref)
            selected.append(decision.artifact_ref)
        return selected


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
