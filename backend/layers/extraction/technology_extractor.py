from __future__ import annotations

from backend.foundation import AnalysisContext, Confidence, Signal, Technology, build_stable_id, normalize_key
from backend.layers.extraction.rules import TECH_KEYWORD_MAP, dedupe_by_key, signal_text, titleize_technology


class TechnologyExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Technology]:
        text = signal_text(signal)
        candidates: list[Technology] = []
        for keyword, (category, normalized) in TECH_KEYWORD_MAP.items():
            if keyword in text:
                candidates.append(
                    Technology(
                        technology_id=build_stable_id("tech", normalized),
                        name=titleize_technology(normalized),
                        normalized_key=normalize_key(normalized),
                        category=category,
                        aliases=[keyword],
                        keywords=[keyword],
                        description=None,
                        first_seen_signal_id=signal.signal_id,
                        confidence=Confidence(value=0.84, factors=[], reason="technology keyword match", evidence_count=1),
                    )
                )
        if signal.signal_type.value == "paper" and not candidates:
            title_text = signal.title.casefold()
            for keyword, (category, normalized) in TECH_KEYWORD_MAP.items():
                if keyword in title_text:
                    candidates.append(
                        Technology(
                            technology_id=build_stable_id("tech", normalized, signal.signal_id),
                            name=titleize_technology(normalized),
                            normalized_key=normalize_key(normalized),
                            category=category,
                            aliases=[keyword],
                            keywords=[keyword],
                            description=None,
                            first_seen_signal_id=signal.signal_id,
                            confidence=Confidence(value=0.72, factors=[], reason="paper title technology match", evidence_count=1),
                        )
                    )
        return dedupe_by_key(candidates, key=lambda item: item.normalized_key)
