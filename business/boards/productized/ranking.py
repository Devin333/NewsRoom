from __future__ import annotations

from business.boards.domain import BoardSignalRankingService
from business.foundation import Signal


class ProductizedRankingService:
    def __init__(self, *, ranking_service: BoardSignalRankingService | None = None) -> None:
        self.ranking_service = ranking_service or BoardSignalRankingService()

    def rank(self, signals: list[Signal]) -> list[Signal]:
        return self.ranking_service.rank(signals)

    def rank_outputs(self, *, deduplicated_signals: list[Signal]) -> dict[str, list[Signal]]:
        return {"ranked_signals": self.rank(deduplicated_signals)}


__all__ = ["ProductizedRankingService"]
