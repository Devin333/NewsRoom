from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.shared.json import to_jsonable


class QualityDecision(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass(frozen=True)
class QualityVerdict:
    decision: QualityDecision
    score: float | None = None
    reason: str | None = None
    findings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def passed(
        cls,
        *,
        score: float | None = None,
        reason: str | None = None,
        findings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> QualityVerdict:
        return cls(
            decision=QualityDecision.PASS,
            score=score,
            reason=reason,
            findings=list(findings or []),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failed(
        cls,
        *,
        score: float | None = None,
        reason: str | None = None,
        findings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> QualityVerdict:
        return cls(
            decision=QualityDecision.FAIL,
            score=score,
            reason=reason,
            findings=list(findings or []),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def warned(
        cls,
        *,
        score: float | None = None,
        reason: str | None = None,
        findings: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> QualityVerdict:
        return cls(
            decision=QualityDecision.WARN,
            score=score,
            reason=reason,
            findings=list(findings or []),
            metadata=dict(metadata or {}),
        )

    @property
    def is_passed(self) -> bool:
        return self.decision == QualityDecision.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "score": self.score,
            "reason": self.reason,
            "findings": list(self.findings),
            "metadata": to_jsonable(self.metadata),
        }
