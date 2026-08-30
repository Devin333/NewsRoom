from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from backend.memory.intelligence_context import IntelligenceMemoryContext
from backend.memory.intelligence_models import ClaimMemory, EventMemory, EvidenceMemory
from backend.memory.intelligence_repository import IntelligenceMemoryQueryRepository


QualityMemorySeverity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class QualityMemoryIssue:
    issue_type: str
    severity: QualityMemorySeverity
    target_type: str
    target_id: str
    message: str
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "message": self.message,
            "evidence_ids": list(self.evidence_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class QualityMemoryCheckResult:
    passed: bool
    issues: list[QualityMemoryIssue]
    metadata: dict[str, Any] = field(default_factory=dict)

    def critical_issues(self) -> list[QualityMemoryIssue]:
        return [issue for issue in self.issues if issue.severity == "critical"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": dict(self.metadata),
        }


class QualityMemoryChecker:
    def __init__(self, repository: IntelligenceMemoryQueryRepository) -> None:
        self.repository = repository

    def check_claims(
        self,
        claims: list[ClaimMemory],
    ) -> QualityMemoryCheckResult:
        issues = _compact_issues(
            [
                issue
                for claim in claims
                for issue in (
                    self.check_claim_has_evidence(claim),
                    self.check_claim_not_contradicted(claim),
                )
                if issue is not None
            ]
        )
        return QualityMemoryCheckResult(
            passed=not any(issue.severity in {"critical", "high"} for issue in issues),
            issues=issues,
            metadata={"claims_checked": len(claims)},
        )

    def check_events(
        self,
        events: list[EventMemory],
    ) -> QualityMemoryCheckResult:
        issues = _compact_issues(
            [issue for event in events if (issue := self.check_event_not_duplicate(event)) is not None]
        )
        return QualityMemoryCheckResult(
            passed=not any(issue.severity in {"critical", "high"} for issue in issues),
            issues=issues,
            metadata={"events_checked": len(events)},
        )

    def check_report_context(
        self,
        context: IntelligenceMemoryContext,
    ) -> QualityMemoryCheckResult:
        issues: list[QualityMemoryIssue] = []
        issues.extend(self.check_claims(context.claims).issues)
        issues.extend(self.check_events(context.events).issues)
        for conflict in context.conflicts:
            issues.append(
                QualityMemoryIssue(
                    issue_type=str(conflict.get("issue_type") or "memory_conflict"),
                    severity="high",
                    target_type="context",
                    target_id=context.query,
                    message=str(conflict.get("message") or "Memory conflict detected"),
                    metadata=dict(conflict),
                )
            )
        compact = _compact_issues(issues)
        return QualityMemoryCheckResult(
            passed=not any(issue.severity in {"critical", "high"} for issue in compact),
            issues=compact,
            metadata={"query": context.query, "topic": context.topic},
        )

    def check_claim_has_evidence(
        self,
        claim: ClaimMemory,
    ) -> QualityMemoryIssue | None:
        evidence = list(claim.evidence_ids)
        if not evidence:
            evidence = [item.evidence_id for item in self.repository.list_evidence_for_claim(claim.claim_id)]
        if evidence:
            return None
        return QualityMemoryIssue(
            issue_type="unsupported_claim",
            severity="critical",
            target_type="claim",
            target_id=claim.claim_id,
            message=f"Claim has no supporting evidence: {claim.text}",
        )

    def check_claim_not_contradicted(
        self,
        claim: ClaimMemory,
    ) -> QualityMemoryIssue | None:
        if claim.status != "contradicted" and not claim.contradicted_by:
            return None
        return QualityMemoryIssue(
            issue_type="contradicted_claim",
            severity="high",
            target_type="claim",
            target_id=claim.claim_id,
            message=f"Claim is contradicted: {claim.text}",
            evidence_ids=list(claim.contradicted_by),
        )

    def check_event_not_duplicate(
        self,
        event: EventMemory,
    ) -> QualityMemoryIssue | None:
        similar = [item for item in self.repository.find_similar_events(event, limit=3) if item.event_id != event.event_id]
        if not similar:
            return None
        return QualityMemoryIssue(
            issue_type="duplicate_event",
            severity="medium",
            target_type="event",
            target_id=event.event_id,
            message=f"Event appears duplicate: {event.title}",
            evidence_ids=list(event.evidence_ids),
            metadata={"similar_event_ids": [item.event_id for item in similar]},
        )

    def check_source_not_noisy(
        self,
        evidence: EvidenceMemory,
    ) -> QualityMemoryIssue | None:
        if evidence.confidence >= 0.25:
            return None
        return QualityMemoryIssue(
            issue_type="noisy_source",
            severity="medium",
            target_type="evidence",
            target_id=evidence.evidence_id,
            message=f"Evidence has low confidence: {evidence.title}",
            evidence_ids=[evidence.evidence_id],
            metadata={"confidence": evidence.confidence, "source_id": evidence.source_id},
        )


def _compact_issues(issues: list[QualityMemoryIssue]) -> list[QualityMemoryIssue]:
    seen: set[tuple[str, str, str]] = set()
    result: list[QualityMemoryIssue] = []
    for issue in issues:
        key = (issue.issue_type, issue.target_type, issue.target_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


__all__ = [
    "QualityMemoryCheckResult",
    "QualityMemoryChecker",
    "QualityMemoryIssue",
    "QualityMemorySeverity",
]
