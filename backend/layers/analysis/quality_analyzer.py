from __future__ import annotations

from backend.layers.analysis import pipeline as rules


class QualityAnalyzer:
    def analyze(self, signals, extraction_results, relations, context=None):
        qualities = []
        for signal in signals:
            score_value, factors = rules._signal_quality(signal, extraction_results, relations)
            qualities.append(
                rules.Quality(
                    target_ref=rules.ObjectRef(object_type="signal", object_id=signal.signal_id, label=signal.title),
                    score=rules.Score(value=score_value, factors=factors),
                    dimensions={
                        "source_reliability": rules.Score(value=rules._factor_value(factors, "source_reliability"), factors=[]),
                        "freshness": rules.Score(value=rules._factor_value(factors, "freshness"), factors=[]),
                        "relevance": rules.Score(value=rules._factor_value(factors, "relevance"), factors=[]),
                        "impact": rules.Score(value=rules._factor_value(factors, "impact"), factors=[]),
                        "specificity": rules.Score(value=rules._factor_value(factors, "specificity"), factors=[]),
                    },
                    explanation=f"Quality for {signal.title}",
                )
            )
        for result in extraction_results:
            for technology in result.technologies:
                quality_score = rules._technology_quality(technology, relations)
                qualities.append(
                    rules.Quality(
                        target_ref=rules.ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                        score=rules.Score(value=quality_score, factors=rules._quality_factors_for_technology(technology, relations)),
                        dimensions={},
                        explanation=f"Quality for {technology.name}",
                    )
                )
        return qualities
