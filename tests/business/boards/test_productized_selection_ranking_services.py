from __future__ import annotations

from business.boards.ai_news.board_service import AINewsBoardService
from business.boards.productized import ProductizedRankingService, ProductizedSignalClassificationService
from business.evaluation.fixtures import sample_signal
from business.foundation import AnalysisContext, BoardType
from business.layers.signal import SignalPipeline


def test_productized_signal_classification_service_returns_step_outputs() -> None:
    context = AnalysisContext(board_type=BoardType.AI_NEWS)
    prepared = SignalPipeline().coerce_signals(
        [sample_signal("ai_news"), sample_signal("paper")],
        context=context,
        board_type=BoardType.AI_NEWS,
    ).signals

    result = ProductizedSignalClassificationService(board_service=AINewsBoardService()).classify(
        context=context,
        prepared_signals=prepared,
    )

    assert len(result["board_signals"]) == 1
    assert result["board_signals"][0].board_type == BoardType.AI_NEWS


def test_productized_ranking_service_returns_step_outputs() -> None:
    context = AnalysisContext(board_type=BoardType.AI_NEWS)
    signal = SignalPipeline().coerce_signals(
        [sample_signal("ai_news", index=1)],
        context=context,
        board_type=BoardType.AI_NEWS,
    ).signals[0]
    low = signal.model_copy(update={"signal_id": "low-score-signal", "metrics": {"final_score": 0.1}})
    high = signal.model_copy(update={"signal_id": "high-score-signal", "metrics": {"final_score": 0.9}})

    result = ProductizedRankingService().rank_outputs(deduplicated_signals=[low, high])

    assert [signal.signal_id for signal in result["ranked_signals"]] == [high.signal_id, low.signal_id]
