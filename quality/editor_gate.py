from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from quality.citation_checker import CitationCheckResult


class EditorDecision(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EditorReview:
    decision: EditorDecision
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
        }


class EditorGate:
    def review(self, citation_check: CitationCheckResult) -> EditorReview:
        if citation_check.passed:
            return EditorReview(decision=EditorDecision.PASS)
        return EditorReview(
            decision=EditorDecision.BLOCKED,
            reasons=[
                "report cites URLs outside the evidence bundle",
                *citation_check.unknown_urls,
            ],
        )
