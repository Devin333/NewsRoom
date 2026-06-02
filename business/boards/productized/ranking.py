from __future__ import annotations

from business.foundation import Signal


class ProductizedRankingService:
    def rank(self, signals: list[Signal]) -> list[Signal]:
        return sorted(signals, key=_signal_rank_key, reverse=True)

    def rank_outputs(self, *, deduplicated_signals: list[Signal]) -> dict[str, list[Signal]]:
        return {"ranked_signals": self.rank(deduplicated_signals)}


def _signal_rank_key(signal: Signal) -> tuple[float, float, str]:
    final_score = float(signal.metrics.get("final_score", 0.5)) if isinstance(signal.metrics, dict) else 0.5
    confidence = signal.confidence.value if signal.confidence is not None else 0.5
    return final_score, confidence, signal.signal_id


__all__ = ["ProductizedRankingService"]
