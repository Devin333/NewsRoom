from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_LIVE_OFFLINE
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_step import quality_gate
from business.boards.cross_board.workflows.daily_intelligence.report_writer import ReportWriter
from business.foundation.models.source import Lineage, SourcePipelineMetrics
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings
from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import ClaimMemory, EventMemory
from framework.workflow import DataBuffer


def test_report_writer_attaches_memory_context_when_recall_available() -> None:
    writer = ReportWriter(recall_service=_RecallService())
    output = writer.draft_report(
        _writer_buffer().scope(
            read_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
            write_keys=[],
        ),
        PROFILE_LIVE_OFFLINE,
    )

    metadata = output["report_draft"]["metadata"]
    assert output["memory_context"]["topic"] == "AI policy"
    assert metadata["memory_context_used"] is True
    assert "Known claims:" in metadata["memory_prompt_context"]


def test_report_writer_without_recall_keeps_memory_metadata_absent() -> None:
    output = ReportWriter().draft_report(
        _writer_buffer().scope(
            read_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
            write_keys=[],
        ),
        PROFILE_LIVE_OFFLINE,
    )

    assert output["memory_context"] is None
    assert "metadata" not in output["report_draft"]


def test_quality_gate_records_memory_quality_metadata_without_blocking() -> None:
    buffer = DataBuffer(
        {
            "report_draft": _report_draft(),
            "evidence_bundle": _evidence_bundle(),
            "verified_findings": VerifiedFindings(),
            "quality_events": [],
            "memory_context": {
                "query": "AI policy",
                "topic": "AI policy",
                "claims": [],
                "events": [],
                "evidence": [],
                "entities": [],
                "decisions": [],
                "preferences": [],
                "conflicts": [{"issue_type": "claim_conflict", "message": "Historical claim conflict"}],
                "metadata": {"memory_available": True},
            },
        }
    )

    output = quality_gate(
        buffer.scope(
            read_keys=["report_draft", "evidence_bundle", "verified_findings", "quality_events"],
            optional_read_keys=["memory_context"],
            write_keys=[],
        )
    )

    assert output["quality_result"].decision == "pass"
    assert output["memory_quality_result"]["passed"] is False
    assert output["memory_quality_result"]["issues"][0]["issue_type"] == "claim_conflict"
    assert output["quality_result"].metadata["memory_quality_result"]["metadata"]["conflict_count"] == 1
    assert output["final_report"].metadata["memory_quality_result"]["memory_available"] is True
    assert any(event.event_type == "memory_quality_checked" for event in output["quality_events"])


class _RecallService:
    def recall_for_topic(self, topic: str, *, limit: int = 5) -> IntelligenceMemoryContext:
        return IntelligenceMemoryContext(
            query=topic,
            topic=topic,
            claims=[ClaimMemory(claim_id="claim-1", run_id="old-run", text="Known historical claim")],
            events=[
                EventMemory(
                    event_id="event-1",
                    event_type="general_news",
                    title="Historical event",
                    summary="Historical event summary.",
                    run_id="old-run",
                    topic=topic,
                )
            ],
            metadata={"memory_available": True},
        )


def _writer_buffer() -> DataBuffer:
    return DataBuffer(
        {
            "request": {"topic": "AI policy"},
            "evidence_bundle": _evidence_bundle(),
            "source_errors": [],
            "source_pipeline_metrics": SourcePipelineMetrics(sources_total=1, sources_fetched=1),
        }
    )


def _evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="daily",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/ai-policy",
                title="AI policy update",
                summary="Policy summary.",
                confidence=0.9,
                source_id="source-1",
                source_item_id="item-1",
                lineage=Lineage(source_id="source-1", source_item_id="item-1"),
            )
        ],
    )


def _report_draft() -> dict:
    return {
        "title": "Daily Intelligence: AI policy",
        "sections": [
            {
                "title": "Summary",
                "content": "AI policy update: Policy summary.",
                "sources": ["https://example.com/ai-policy"],
            }
        ],
    }
