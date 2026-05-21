from __future__ import annotations

from business.layers.analysis import pipeline as rules


class TrendAnalyzer:
    def analyze(self, signals, extraction_results, relations, context):
        windows = rules._time_window(context)
        signal_groups = rules._signals_by_technology(signals, extraction_results, relations)
        trends = []
        for _technology_key, payload in signal_groups.items():
            signal_count = len(payload["signals"])
            previous_count = max(0, signal_count - 1)
            growth_rate = None if previous_count == 0 else (signal_count - previous_count) / previous_count
            direction = rules._trend_direction(signal_count, previous_count, growth_rate)
            trend_score = rules._trend_score(signal_count, previous_count, growth_rate, len(payload["boards"]))
            trends.append(
                rules.Trend(
                    target_ref=payload["ref"],
                    time_window=windows,
                    score=rules.Score(value=trend_score, factors=rules._trend_factors(signal_count, previous_count, growth_rate, len(payload["boards"]))),
                    direction=direction,
                    signal_count=signal_count,
                    previous_signal_count=previous_count,
                    growth_rate=growth_rate,
                    explanation=f"{payload['name']} appears in {signal_count} signal(s) across {len(payload['boards'])} board(s).",
                )
            )
        return trends
