from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone as _tz
from typing import Any

from business.boards.paper_radar.visual_compiler.models import PaperCompileInfo, PaperSourceComparisonReport
from business.memory.intelligence_builder import stable_id
from business.memory.intelligence_models import DecisionMemory, EventMemory, EvidenceMemory
from business.memory.intelligence_repository import IntelligenceMemoryRepository


UTC = _tz.utc


@dataclass(frozen=True)
class SourceComparisonMemoryIngestionResult:
    attempted: bool
    saved: bool
    evidence_count: int = 0
    decision_count: int = 0
    event_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "saved": self.saved,
            "evidence_count": self.evidence_count,
            "decision_count": self.decision_count,
            "event_count": self.event_count,
            "error": self.error,
        }


class PaperSourceComparisonMemoryService:
    def __init__(self, repository: IntelligenceMemoryRepository | None = None) -> None:
        self.repository = repository

    def ingest_source_comparison(
        self,
        *,
        report: PaperSourceComparisonReport,
        compile_info: PaperCompileInfo,
        paper: Mapping[str, Any] | None = None,
        artifact_ref: str | None = None,
    ) -> SourceComparisonMemoryIngestionResult:
        lessons = [dict(item) for item in report.lessons]
        if not lessons:
            return SourceComparisonMemoryIngestionResult(attempted=False, saved=False)

        evidence = _evidence_from_report(report=report, compile_info=compile_info, lessons=lessons, artifact_ref=artifact_ref)
        decision = _decision_from_report(report=report, compile_info=compile_info, paper=paper, artifact_ref=artifact_ref)
        event = _event_from_report(report=report, compile_info=compile_info, evidence=evidence, artifact_ref=artifact_ref)
        if self.repository is None:
            return SourceComparisonMemoryIngestionResult(attempted=True, saved=False)
        try:
            self.repository.save_evidence(evidence)
            self.repository.save_decisions([decision])
            self.repository.save_events([event])
        except Exception as exc:
            return SourceComparisonMemoryIngestionResult(attempted=True, saved=False, error=str(exc))
        return SourceComparisonMemoryIngestionResult(
            attempted=True,
            saved=True,
            evidence_count=len(evidence),
            decision_count=1,
            event_count=1,
        )


def _evidence_from_report(
    *,
    report: PaperSourceComparisonReport,
    compile_info: PaperCompileInfo,
    lessons: list[dict[str, Any]],
    artifact_ref: str | None,
) -> list[EvidenceMemory]:
    fetched_at = _parse_time(report.createdAt)
    source_urls = [_text(compile_info.sourcePdfUrl)] if _text(compile_info.sourcePdfUrl) else []
    evidence: list[EvidenceMemory] = []
    for lesson in lessons:
        lesson_id = _text(lesson.get("lessonId")) or stable_id("source-comparison-lesson", report.paperId, _text(lesson.get("code")), prefix="lesson")
        code = _text(lesson.get("code")) or "source_comparison"
        evidence.append(
            EvidenceMemory(
                evidence_id=stable_id("paper-source-comparison-evidence", report.paperId, lesson_id, prefix="evidence"),
                run_id=_run_id(report, compile_info),
                title=f"Paper source comparison lesson: {code}",
                summary=_text(lesson.get("message")) or report.summary,
                source_urls=source_urls,
                source_item_ids=[report.paperId, compile_info.sourceHash, lesson_id],
                confidence=1.0 if report.passed else 0.95,
                category="paper_reader_source_comparison",
                fetched_at=fetched_at,
                topic="paper_reader",
                source_name="Research Reader source comparer",
                source_id=report.comparer,
                content_hash=compile_info.sourceHash,
                raw_artifact_ref=artifact_ref,
                metadata={
                    "paper_id": report.paperId,
                    "comparison_passed": report.passed,
                    "lesson": lesson,
                    "metrics": dict(report.metrics),
                    "artifact_ref": artifact_ref,
                },
            )
        )
    return evidence


def _decision_from_report(
    *,
    report: PaperSourceComparisonReport,
    compile_info: PaperCompileInfo,
    paper: Mapping[str, Any] | None,
    artifact_ref: str | None,
) -> DecisionMemory:
    decision = "allow" if report.passed else "block"
    return DecisionMemory(
        decision_id=stable_id("paper-source-comparison-decision", report.paperId, compile_info.sourceHash, str(report.passed), prefix="decision"),
        decision_type="paper_reader_source_comparison_publication",
        target_type="paper",
        target_id=report.paperId,
        decision=decision,
        run_id=_run_id(report, compile_info),
        reason=report.summary,
        agent_id=report.comparer,
        workflow_id="paper_reader_source_comparison",
        input_features={
            "paper": dict(paper or {}),
            "provider": compile_info.provider,
            "source_pdf_url": compile_info.sourcePdfUrl,
            "metrics": dict(report.metrics),
        },
        output_scores={
            "passed": report.passed,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "lesson_count": len(report.lessons),
        },
        created_at=_parse_time(report.createdAt),
        metadata={
            "artifact_ref": artifact_ref,
            "errors": [dict(item) for item in report.errors],
            "warnings": [dict(item) for item in report.warnings],
        },
    )


def _event_from_report(
    *,
    report: PaperSourceComparisonReport,
    compile_info: PaperCompileInfo,
    evidence: list[EvidenceMemory],
    artifact_ref: str | None,
) -> EventMemory:
    return EventMemory(
        event_id=stable_id("paper-source-comparison-event", report.paperId, compile_info.sourceHash, str(report.passed), prefix="event"),
        event_type="engineering_practice",
        title=f"Research Reader source comparison {'passed' if report.passed else 'blocked'} for {report.paperId}",
        summary=report.summary,
        run_id=_run_id(report, compile_info),
        event_time=_parse_time(report.createdAt),
        detected_at=_parse_time(report.createdAt),
        topic="paper_reader",
        evidence_ids=[item.evidence_id for item in evidence],
        impact_score=0.8 if not report.passed else 0.4,
        novelty_score=0.35,
        metadata={
            "paper_id": report.paperId,
            "comparison_passed": report.passed,
            "provider": compile_info.provider,
            "artifact_ref": artifact_ref,
            "metrics": dict(report.metrics),
            "error_codes": [_text(item.get("code")) for item in report.errors if _text(item.get("code"))],
            "warning_codes": [_text(item.get("code")) for item in report.warnings if _text(item.get("code"))],
        },
    )


def _run_id(report: PaperSourceComparisonReport, compile_info: PaperCompileInfo) -> str:
    return f"paper-source-comparison:{report.paperId}:{compile_info.sourceHash[:12]}"


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
