from __future__ import annotations

from backend.foundation import AnalysisContext, Confidence, Signal, Topic, build_stable_id, normalize_key
from backend.layers.extraction.rules import TOPIC_KEYWORDS, dedupe_by_key, signal_text


class TopicExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Topic]:
        text = signal_text(signal)
        candidates: list[Topic] = []
        for keyword, normalized in TOPIC_KEYWORDS.items():
            if keyword in text:
                candidates.append(
                    Topic(
                        topic_id=build_stable_id("topic", normalized),
                        name=normalized.title() if normalized != "llmops" else "LLMOps",
                        normalized_key=normalize_key(normalized),
                        aliases=[keyword],
                        keywords=[keyword],
                        description=None,
                        confidence=Confidence(value=0.82, factors=[], reason="topic keyword match", evidence_count=1),
                    )
                )
        if not candidates:
            candidates.append(
                Topic(
                    topic_id=build_stable_id("topic", "unknown topic", signal.signal_id),
                    name="Unknown Topic",
                    normalized_key="unknown_topic",
                    aliases=[],
                    keywords=[],
                    description="Fallback topic",
                    confidence=Confidence(value=0.35, factors=[], reason="fallback topic", evidence_count=0),
                )
            )
        return dedupe_by_key(candidates, key=lambda item: item.normalized_key)
