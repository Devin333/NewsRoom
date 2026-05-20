from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class QualityErrorType(str, Enum):
    INVALID_EVIDENCE_LINEAGE = "invalid_evidence_lineage"
    REJECTED_CLAIM_USED = "rejected_claim_used"
    UNSUPPORTED_REPORT_URL = "unsupported_report_url"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    REWRITE_EXHAUSTED = "rewrite_exhausted"
    QUALITY_GATE_BLOCKED = "quality_gate_blocked"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


@dataclass(frozen=True)
class QualityError:
    error_type: QualityErrorType | str
    message: str
    workflow_blocking: bool
    retryable: bool = False
    rewrite_allowed: bool = False
    human_review_allowed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "error_type", QualityErrorType(self.error_type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": QualityErrorType(self.error_type).value,
            "message": self.message,
            "workflow_blocking": self.workflow_blocking,
            "retryable": self.retryable,
            "rewrite_allowed": self.rewrite_allowed,
            "human_review_allowed": self.human_review_allowed,
            "metadata": dict(self.metadata),
        }


def quality_error_policy(error_type: QualityErrorType | str) -> QualityError:
    normalized = QualityErrorType(error_type)
    if normalized in {
        QualityErrorType.UNSUPPORTED_CLAIM,
        QualityErrorType.REWRITE_EXHAUSTED,
    }:
        return QualityError(
            error_type=normalized,
            message=normalized.value,
            workflow_blocking=True,
            rewrite_allowed=normalized == QualityErrorType.UNSUPPORTED_CLAIM,
        )
    return QualityError(
        error_type=normalized,
        message=normalized.value,
        workflow_blocking=True,
        rewrite_allowed=False,
    )
