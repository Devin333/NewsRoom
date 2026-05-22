from business.boards.cross_board.workflows.daily_intelligence.quality_gate_step import quality_gate
from business.foundation.models.source import Lineage
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings
from framework.workflow import DataBuffer


def test_daily_quality_gate_blocks_critical_memory_issue() -> None:
    buffer = DataBuffer(
        {
            "report_draft": {
                "title": "Daily Intelligence: AI policy",
                "sections": [
                    {
                        "title": "Summary",
                        "content": "AI policy update: Policy summary.",
                        "sources": ["https://example.com/ai-policy"],
                    }
                ],
            },
            "evidence_bundle": _evidence_bundle(),
            "verified_findings": VerifiedFindings(),
            "quality_events": [],
            "memory_context": {
                "query": "AI policy",
                "topic": "AI policy",
                "claims": [
                    {
                        "claim_id": "claim-1",
                        "run_id": "old-run",
                        "text": "Unsupported historical claim",
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

    output = quality_gate(
        buffer.scope(
            read_keys=["report_draft", "evidence_bundle", "verified_findings", "quality_events"],
            optional_read_keys=["memory_context"],
            write_keys=[],
        )
    )

    assert output["quality_result"].decision == "blocked"
    assert output["quality_result"].blocked is True
    assert output["memory_quality_result"]["issues"][0]["issue_type"] == "unsupported_claim"
    assert output["memory_quality_result"]["metadata"]["critical_issue_count"] == 1
    assert "blocked_report" in output
    assert "final_report" not in output


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
