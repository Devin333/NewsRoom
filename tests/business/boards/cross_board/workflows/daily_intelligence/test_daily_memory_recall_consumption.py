from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_LIVE_OFFLINE
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_step import quality_gate
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_outputs import (
    DailyQualityGateOutputInput,
    build_quality_gate_outputs,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_context_projection import (
    DailyQualityContextProjectionInput,
    DailyQualityContextProjectionService,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_gate_usecase import (
    DailyQualityGateInput,
    evaluate_daily_quality_gate,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import evaluate_report_quality
from business.boards.cross_board.workflows.daily_intelligence.registry import build_daily_intelligence_registry
from business.boards.cross_board.workflows.daily_intelligence.report_writer import ReportWriter
from business.layers.analysis.quality import RewritePolicy
from business.foundation.models.source import Lineage, SourcePipelineMetrics
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings
from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_models import ClaimMemory, EventMemory, EvidenceMemory
from business.memory.historian_context_adapter import HistorianContextAdapter
from business.agents.historian_agent import HistorianAgent
from business.memory.historical_context import HistoricalContext
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
    assert metadata["daily_report_context"]["schema_version"] == "business.cross_board.daily_report.context_metadata.v1"
    assert metadata["memory_context_used"] is True
    assert "Known claims:" in metadata["memory_prompt_context"]


def test_report_writer_without_recall_keeps_memory_metadata_absent(caplog) -> None:
    caplog.set_level("WARNING")
    output = ReportWriter().draft_report(
        _writer_buffer().scope(
            read_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
            write_keys=[],
        ),
        PROFILE_LIVE_OFFLINE,
    )

    assert output["memory_context"] is None
    assert "metadata" not in output["report_draft"]
    assert "Memory recall service is not configured" in caplog.text


def test_report_writer_normalizes_source_errors_before_source_notes() -> None:
    output = ReportWriter().draft_report(
        _writer_buffer(
            source_errors=[
                {
                    "source_id": "feed-1",
                    "error_type": "fetch_timeout",
                    "error_message": "timeout",
                }
            ],
            source_pipeline_metrics=SourcePipelineMetrics(
                sources_total=2,
                sources_fetched=1,
                sources_failed=1,
            ),
        ).scope(
            read_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
            write_keys=[],
        ),
        PROFILE_LIVE_OFFLINE,
    )

    source_notes = next(
        section for section in output["report_draft"]["sections"] if section["title"] == "Source Notes"
    )
    assert "Observed source error types: fetch_timeout." in source_notes["content"]


def test_report_writer_reads_namespaced_source_and_evidence_keys() -> None:
    output = ReportWriter().draft_report(
        DataBuffer(
            {
                "request": {"topic": "AI policy"},
                "evidence.bundle": _evidence_bundle(),
                "sources.errors": [
                    {
                        "source_id": "feed-1",
                        "error_type": "fetch_timeout",
                        "error_message": "timeout",
                    }
                ],
                "sources.pipeline_metrics": SourcePipelineMetrics(
                    sources_total=2,
                    sources_fetched=1,
                    sources_failed=1,
                ),
            }
        ).scope(
            read_keys=[
                "request",
                "evidence.bundle",
                "sources.errors",
                "sources.pipeline_metrics",
            ],
            write_keys=[],
        ),
        PROFILE_LIVE_OFFLINE,
    )

    source_notes = next(
        section for section in output["report_draft"]["sections"] if section["title"] == "Source Notes"
    )
    assert "Observed source error types: fetch_timeout." in source_notes["content"]


def test_report_writer_attaches_historian_context_when_available() -> None:
    writer = ReportWriter(historian_context_adapter=HistorianContextAdapter(HistorianAgent(_HistorianContextService())))

    output = writer.draft_report(
        _writer_buffer().scope(
            read_keys=["request", "evidence_bundle", "source_errors", "source_pipeline_metrics"],
            write_keys=[],
        ),
        PROFILE_LIVE_OFFLINE,
    )

    metadata = output["report_draft"]["metadata"]
    assert output["historian_context"]["metadata"]["contradiction_count"] == 1
    assert metadata["daily_report_context"]["schema_version"] == "business.cross_board.daily_report.context_metadata.v1"
    assert metadata["historian_context_used"] is True
    assert "Historical analysis:" in metadata["historian_prompt_context"]


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
    assert output["quality_gate_metrics"].memory_conflict_count == 1
    assert output["quality_gate_metrics"].memory_conflict_rate == 1.0
    assert output["quality_gate_metrics"].block_rate == 0.0
    assert output["final_report"].metadata["memory_quality_result"]["memory_available"] is True
    assert any(event.event_type == "memory_quality_checked" for event in output["quality_events"])


def test_quality_gate_reads_namespaced_report_evidence_quality_and_memory_keys() -> None:
    buffer = DataBuffer(
        {
            "report.draft": _report_draft(),
            "evidence.bundle": _evidence_bundle(),
            "evidence.verified_findings": VerifiedFindings(),
            "quality.events": [],
            "memory.context": {
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
            read_keys=[
                "report.draft",
                "evidence.bundle",
                "evidence.verified_findings",
                "quality.events",
            ],
            optional_read_keys=["memory.context"],
            write_keys=[],
        )
    )

    assert output["quality_result"].decision == "pass"
    assert output["memory_quality_result"]["passed"] is False
    assert output["quality_result"].metadata["memory_quality_result"]["metadata"]["conflict_count"] == 1


def test_quality_gate_usecase_runs_without_workflow_buffer() -> None:
    quality_events = []

    output = evaluate_daily_quality_gate(
        DailyQualityGateInput(
            report_draft=_report_draft(),
            evidence_bundle=_evidence_bundle(),
            verified_findings=VerifiedFindings(),
            quality_events=quality_events,
        )
    )

    assert output["quality_result"].decision == "pass"
    assert output["final_report"].title == "Daily Intelligence: AI policy"
    assert output["quality.result"] == output["quality_result"]
    assert quality_events == []


def test_quality_gate_output_builder_publishes_without_usecase_or_workflow_buffer() -> None:
    evidence_bundle = _evidence_bundle()
    verified_findings = VerifiedFindings()
    rewrite_policy = RewritePolicy()
    evaluation = evaluate_report_quality(
        _report_draft(),
        evidence_bundle,
        verified_findings,
        quality_events=[],
        rewrite_policy=rewrite_policy,
        rewrite_attempts=0,
    )

    output = build_quality_gate_outputs(
        DailyQualityGateOutputInput(
            report_draft=_report_draft(),
            final_report_draft=_report_draft(),
            evidence_bundle=evidence_bundle,
            verified_findings=verified_findings,
            quality_events=[],
            memory_context={"metadata": {"memory_available": True}},
            historian_context={"output": {"repeated_claims": ["known claim"]}},
            memory_quality_result={
                "memory_available": True,
                "passed": True,
                "issues": [],
                "metadata": {"memory_repository_available": True},
            },
            citation_check=evaluation["citation_check"],
            support_matrix=evaluation["support_matrix"],
            quality_summary=evaluation["quality_summary"],
            review=evaluation["review"],
            rewrite_policy=rewrite_policy,
            rewritten_report_draft=None,
            rewrite_attempts=0,
            human_review_request=None,
            human_review_required=False,
        )
    )

    assert output["quality_result"].metadata["memory_quality_result"]["metadata"] == {
        "memory_repository_available": True
    }
    assert output["quality.result"] == output["quality_result"]
    assert output["report.final"] == output["final_report"]
    assert output["final_report"].metadata["historian"]["output"]["repeated_claims"] == ["known claim"]


def test_quality_context_projection_prefers_explicit_historian_context() -> None:
    report = _report_draft()
    report["metadata"] = {
        "historian": {
            "output": {"contradictions": ["report metadata contradiction"]},
        }
    }
    explicit_historian = {
        "output": {
            "contradictions": ["explicit contradiction"],
            "repeated_claims": ["explicit repeated claim"],
        }
    }

    projection = DailyQualityContextProjectionService().build(
        DailyQualityContextProjectionInput(
            report_draft=report,
            memory_context={
                "query": "AI policy",
                "topic": "AI policy",
                "claims": [],
                "events": [],
                "evidence": [],
                "entities": [],
                "decisions": [],
                "preferences": [],
                "conflicts": [],
                "metadata": {
                    "memory_available": True,
                    "historian": {
                        "output": {"contradictions": ["memory metadata contradiction"]},
                    },
                },
            },
            historian_context=explicit_historian,
        )
    )

    metadata = projection.memory_quality_result["metadata"]
    assert projection.historian_context == explicit_historian
    assert metadata["historian_contradictions"] == ["explicit contradiction"]
    assert metadata["historian_repeated_claims"] == ["explicit repeated claim"]


def test_quality_gate_uses_injected_memory_repository_for_claim_evidence() -> None:
    repository = _QualityMemoryRepository()
    registry = build_daily_intelligence_registry(
        profile=PROFILE_LIVE_OFFLINE,
        collect_sources=lambda buffer, profile: {},
        draft_report=lambda buffer, profile: {},
        memory_query_repository=repository,
    )
    buffer = DataBuffer(
        {
            "report_draft": _report_draft(),
            "evidence_bundle": _evidence_bundle(),
            "verified_findings": VerifiedFindings(),
            "quality_events": [],
            "memory_context": {
                "query": "AI policy",
                "topic": "AI policy",
                "claims": [
                    {
                        "claim_id": "claim-from-repository",
                        "run_id": "old-run",
                        "text": "Historical claim with repository evidence",
                        "status": "active",
                        "evidence_ids": [],
                    }
                ],
                "events": [],
                "conflicts": [],
                "metadata": {"memory_available": True},
            },
        }
    )

    output = registry.get("daily.quality_gate")(
        buffer.scope(
            read_keys=["report_draft", "evidence_bundle", "verified_findings", "quality_events"],
            optional_read_keys=["memory_context"],
            write_keys=[],
        )
    )

    metadata = output["memory_quality_result"]["metadata"]
    assert repository.evidence_lookup_count == 1
    assert output["memory_quality_result"]["passed"] is True
    assert output["memory_quality_result"]["issues"] == []
    assert metadata["memory_repository_available"] is True
    assert metadata["memory_repository_source"] == "injected"


def test_quality_gate_reads_explicit_historian_context_without_blocking() -> None:
    historian_context = {
        "output": {
            "repeated_claims": ["Known historical claim"],
            "contradictions": ["Contradicted historical claim"],
        },
        "metadata": {"contradiction_count": 1},
    }
    buffer = DataBuffer(
        {
            "report_draft": _report_draft(),
            "evidence_bundle": _evidence_bundle(),
            "verified_findings": VerifiedFindings(),
            "quality_events": [],
            "historian_context": historian_context,
        }
    )

    output = quality_gate(
        buffer.scope(
            read_keys=["report_draft", "evidence_bundle", "verified_findings", "quality_events"],
            optional_read_keys=["memory_context", "historian_context"],
            write_keys=[],
        )
    )

    assert output["quality_result"].decision == "pass"
    metadata = output["quality_result"].metadata["memory_quality_result"]["metadata"]
    assert metadata["historian_contradictions"] == ["Contradicted historical claim"]
    assert metadata["historian_repeated_claims"] == ["Known historical claim"]
    assert output["final_report"].metadata["historian"] == historian_context


def test_quality_gate_keeps_historian_report_metadata_fallback() -> None:
    report = _report_draft()
    report["metadata"] = {
        "historian": {
            "output": {"contradictions": ["Metadata fallback contradiction"]},
            "metadata": {"contradiction_count": 1},
        }
    }
    buffer = DataBuffer(
        {
            "report_draft": report,
            "evidence_bundle": _evidence_bundle(),
            "verified_findings": VerifiedFindings(),
            "quality_events": [],
        }
    )

    output = quality_gate(
        buffer.scope(
            read_keys=["report_draft", "evidence_bundle", "verified_findings", "quality_events"],
            optional_read_keys=["memory_context", "historian_context"],
            write_keys=[],
        )
    )

    metadata = output["quality_result"].metadata["memory_quality_result"]["metadata"]
    assert metadata["historian_contradictions"] == ["Metadata fallback contradiction"]


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


class _HistorianContextService:
    def build_context(self, request):
        return HistoricalContext(
            query=request.topic,
            topic=request.topic,
            contradictions=[
                ClaimMemory(
                    claim_id="claim-hist-1",
                    run_id="run-1",
                    text="Contradicted historical claim",
                    status="contradicted",
                )
            ],
            timeline_summary="AI policy timeline",
        )


class _QualityMemoryRepository:
    def __init__(self) -> None:
        self.evidence_lookup_count = 0

    def list_evidence_for_claim(self, claim_id):
        self.evidence_lookup_count += 1
        if claim_id != "claim-from-repository":
            return []
        return [
            EvidenceMemory(
                evidence_id="memory-ev-1",
                run_id="memory-run",
                title="Historical evidence",
                summary="Historical evidence summary.",
                source_urls=["https://example.com/memory-evidence"],
                source_item_ids=["memory-item-1"],
                confidence=0.9,
                topic="AI policy",
            )
        ]

    def find_similar_events(self, event, *, limit=3):
        return []

    def search_evidence(self, *, query, topic=None, limit=8):
        return []

    def search_claims(self, *, query, topic=None, limit=8):
        return []

    def search_entities(self, *, query, topic=None, limit=8):
        return []

    def search_events(self, *, query, topic=None, limit=8):
        return []

    def search_decisions(self, *, query, topic=None, limit=8):
        return []

    def search_preferences(self, *, query, topic=None, limit=8):
        return []

    def get_entity(self, entity_id):
        return None

    def find_entity_by_name(self, name):
        return None

    def list_entities_by_type(self, entity_type, *, limit=20):
        return []

    def get_claim(self, claim_id):
        return None

    def find_similar_claims(self, claim, *, limit=10):
        return []

    def list_claims_by_entity(self, entity_id, *, limit=20):
        return []

    def list_claims_by_topic(self, topic, *, limit=20):
        return []

    def get_event(self, event_id):
        return None

    def list_events_by_entity(self, entity_id, *, limit=20):
        return []

    def list_events_by_topic(self, topic, *, limit=20):
        return []

    def list_decisions_for_target(self, target_type, target_id, *, limit=20):
        return []

    def list_preferences(
        self,
        *,
        owner_type,
        owner_id,
        preference_type=None,
        limit=20,
    ):
        return []


def _writer_buffer(
    *,
    source_errors: list | None = None,
    source_pipeline_metrics: SourcePipelineMetrics | None = None,
) -> DataBuffer:
    return DataBuffer(
        {
            "request": {"topic": "AI policy"},
            "evidence_bundle": _evidence_bundle(),
            "source_errors": source_errors or [],
            "source_pipeline_metrics": source_pipeline_metrics
            or SourcePipelineMetrics(sources_total=1, sources_fetched=1),
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
