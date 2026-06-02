from __future__ import annotations

from business.boards.productized import ProductizedEvidenceService
from business.boards.productized.models import ProductizedRunState
from business.evaluation.fixtures import sample_signal
from business.foundation import AnalysisContext, BoardType
from business.layers.signal import SignalPipeline


def test_productized_evidence_service_updates_run_state() -> None:
    signal = SignalPipeline().coerce_signals(
        [sample_signal("ai_news")],
        context=AnalysisContext(board_type=BoardType.AI_NEWS),
        board_type=BoardType.AI_NEWS,
    ).signals[0]
    run_state = ProductizedRunState(
        board_type=BoardType.AI_NEWS,
        run_id="evidence-run",
        extracted_entities=[
            {
                "signal_id": signal.signal_id,
                "entities": [{"name": "Agent Memory", "type": "product"}],
            }
        ],
    )

    result = ProductizedEvidenceService().build_outputs(
        board_signals=[signal],
        productized_run=run_state,
    )

    assert result["evidence_refs"]
    assert result["evidence_items"][0]["entities"] == [{"name": "Agent Memory", "type": "product"}]
    assert result["productized_run"].evidence_refs == result["evidence_refs"]
    assert result["productized_run"].evidence_items == result["evidence_items"]
