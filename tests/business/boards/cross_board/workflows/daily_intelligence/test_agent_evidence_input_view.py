from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.agent_evidence_input_view import (
    DailyAgentEvidenceInputView,
    coerce_agent_evidence_bundle,
)


def test_agent_evidence_input_view_reads_request_embedded_bundle() -> None:
    view = DailyAgentEvidenceInputView.from_inputs(
        {
            "request": {
                "bundle": {
                    "bundle_id": "bundle-1",
                    "items": [
                        {
                            "evidence_id": "ev-1",
                            "source_url": "https://example.com/source",
                            "title": "Evidence",
                            "summary": "Evidence summary",
                            "confidence": "0.8",
                            "source_id": "source-1",
                            "source_item_id": "item-1",
                            "source_item_ids": ["item-1", "item-2"],
                            "source_urls": ["https://example.com/source-alt"],
                            "source_reliability": "high",
                            "publishable": True,
                            "evidence_type": "article",
                            "metadata": {"kind": "fixture"},
                        }
                    ],
                    "missing_information": ["none"],
                    "coverage_notes": ["covered"],
                }
            }
        }
    )

    assert view is not None
    assert view.evidence_bundle.bundle_id == "bundle-1"
    assert view.allowed_evidence_ids == {"ev-1"}
    item = view.evidence_bundle.items[0]
    assert item.confidence == 0.8
    assert item.source_item_id == "item-1"
    assert item.source_item_ids == ["item-1", "item-2"]
    assert item.source_urls == [
        "https://example.com/source",
        "https://example.com/source-alt",
    ]
    assert item.metadata["kind"] == "fixture"


def test_coerce_agent_evidence_bundle_rejects_non_bundle_payload() -> None:
    assert coerce_agent_evidence_bundle({"items": "not-a-list"}) is None
    assert coerce_agent_evidence_bundle("not-a-bundle") is None
