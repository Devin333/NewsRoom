from __future__ import annotations

from dataclasses import dataclass, field

from business.boards.cross_board.workflows.daily_intelligence.quality_evaluation import (
    evaluate_report_quality,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_result_builder import (
    quality_gate_metrics,
)
from business.foundation.models.source import Lineage
from business.layers.analysis.quality import EditorDecision, RewritePolicy
from business.layers.relation.evidence.models import EvidenceItem, VerifiedFindings


def test_quality_evaluation_uses_source_gate_evidence_item_count() -> None:
    quality_events = []

    evaluate_report_quality(
        _report_draft(),
        _declared_count_bundle(item_count=3),
        VerifiedFindings(),
        quality_events=quality_events,
        rewrite_policy=RewritePolicy(),
        rewrite_attempts=0,
    )

    assert quality_events[0].event_type == "citation_check_started"
    assert quality_events[0].metadata["evidence_items_count"] == 3


def test_quality_gate_metrics_use_source_gate_evidence_item_count() -> None:
    metrics = quality_gate_metrics(
        evidence_bundle=_declared_count_bundle(item_count=4),
        verified_findings=VerifiedFindings(),
        citation_check=_CitationCheck(),
        support_matrix=_SupportMatrix(),
        quality_summary=_QualitySummary(),
        review=_Review(),
        rewrite_attempts=0,
        human_review_required=False,
    )

    assert metrics.evidence_items_count == 4


@dataclass(frozen=True)
class _DeclaredCountEvidenceBundle:
    bundle_id: str
    items: list[EvidenceItem]
    item_count: int

    @property
    def source_urls(self) -> set[str]:
        return {url for item in self.items for url in item.source_urls}

    @property
    def evidence_ids(self) -> set[str]:
        return {item.evidence_id for item in self.items}


@dataclass(frozen=True)
class _CitationCheck:
    unknown_urls: list[str] = field(default_factory=list)
    unsupported_urls: list[str] = field(default_factory=list)
    missing_section_sources: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    rejected_claim_usage: list[str] = field(default_factory=list)
    citation_coverage_score: float = 1.0
    claim_support_score: float = 1.0
    section_source_coverage_score: float = 1.0
    unsupported_evidence_ids: list[str] = field(default_factory=list)
    failure_categories: list = field(default_factory=list)


@dataclass(frozen=True)
class _SupportMatrix:
    unsupported_sections: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _QualitySummary:
    support_coverage: float = 1.0
    quality_score: float = 1.0


@dataclass(frozen=True)
class _Review:
    decision: EditorDecision = EditorDecision.PASS
    reasons: list[str] = field(default_factory=list)


def _declared_count_bundle(*, item_count: int) -> _DeclaredCountEvidenceBundle:
    return _DeclaredCountEvidenceBundle(
        bundle_id="bundle-1",
        item_count=item_count,
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/source",
                title="Evidence source",
                summary="Source-grounded summary.",
                confidence=1.0,
                source_id="source-1",
                source_item_id="item-1",
                lineage=Lineage(source_id="source-1", source_item_id="item-1"),
            )
        ],
    )


def _report_draft() -> dict:
    return {
        "title": "Daily Intelligence",
        "sections": [
            {
                "section_id": "summary",
                "title": "Summary",
                "content": "Source-grounded summary.",
                "sources": ["https://example.com/source"],
                "claim_grounding": [],
            }
        ],
    }
