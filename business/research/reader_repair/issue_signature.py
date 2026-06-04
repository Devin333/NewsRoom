from __future__ import annotations

from business.foundation import normalize_key
from business.research.domain.reader_repair import ReaderIssueSignature, ReaderIssueType


def build_reader_issue_signature(
    *,
    issue_type: ReaderIssueType,
    symptom: str,
    step_id: str | None = None,
    source_format: str | None = None,
) -> ReaderIssueSignature:
    symptom_key = normalize_key(symptom)[:80] or "unknown_symptom"
    return ReaderIssueSignature(
        issue_type=issue_type,
        step_id=step_id,
        source_format=source_format,
        symptom_key=symptom_key,
    )


__all__ = ["build_reader_issue_signature"]
