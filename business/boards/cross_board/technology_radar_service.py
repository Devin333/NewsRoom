from __future__ import annotations

from business.boards.cross_board.models import TechnologyRadarOutput, TechnologyRadarRequest
from business.layers.analysis import AnalysisResult


class TechnologyRadarService:
    def build_radar(self, request: TechnologyRadarRequest, analysis: AnalysisResult) -> TechnologyRadarOutput:
        items = [
            item
            for item in analysis.radar_items
            if item.trend_score.value >= request.min_trend_score
            and (not request.categories or item.category.value in request.categories)
        ][: request.limit]
        return TechnologyRadarOutput(radar_items=items)
