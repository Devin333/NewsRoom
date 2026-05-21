from __future__ import annotations

from business.layers.analysis.pipeline import AnalysisPipeline


class ImpactAnalyzer:
    def analyze(self, signals, extraction_results, relations, context):
        return AnalysisPipeline().run(signals, extraction_results, relations, context).impacts
