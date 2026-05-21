from __future__ import annotations

from business.foundation import AnalysisContext, Entity, EntityType, Signal
from business.layers.extraction.rules import (
    COMPANY_HINTS,
    KNOWN_MODEL_HINTS,
    build_entity,
    dedupe_by_key,
    github_repo_from_signal,
    paper_id_from_signal,
    signal_text,
)


class EntityExtractor:
    def extract(self, signal: Signal, context: AnalysisContext | None = None) -> list[Entity]:
        text = signal_text(signal)
        entities: list[Entity] = []
        if signal.signal_type.value == "github_project":
            repo = github_repo_from_signal(signal)
            if repo:
                entities.append(
                    build_entity(
                        entity_type=EntityType.GITHUB_PROJECT,
                        canonical_name_value=repo,
                        source_signal_id=signal.signal_id,
                        url=signal.url,
                        aliases=[signal.source.source_name, signal.title],
                        confidence=0.95,
                        metadata={"extraction_method": "github_repo_rule", "context_board": (context.board_type.value if context else signal.board_type.value)},
                    )
                )
        if signal.signal_type.value == "paper":
            paper_id = paper_id_from_signal(signal)
            if paper_id:
                entities.append(
                    build_entity(
                        entity_type=EntityType.PAPER,
                        canonical_name_value=paper_id,
                        source_signal_id=signal.signal_id,
                        url=signal.url,
                        aliases=[signal.title],
                        confidence=0.95,
                        metadata={"extraction_method": "paper_id_rule", "context_board": (context.board_type.value if context else signal.board_type.value)},
                    )
                )
        if signal.signal_type.value == "ai_news":
            for hint in COMPANY_HINTS:
                if hint in text:
                    entities.append(
                        build_entity(
                            entity_type=EntityType.COMPANY,
                            canonical_name_value=hint,
                            source_signal_id=signal.signal_id,
                            confidence=0.75,
                            metadata={"extraction_method": "company_hint_rule", "matched_hint": hint},
                        )
                    )
        if signal.signal_type.value == "community_discussion":
            for hint in COMPANY_HINTS | KNOWN_MODEL_HINTS:
                if hint in text:
                    entities.append(
                        build_entity(
                            entity_type=EntityType.UNKNOWN,
                            canonical_name_value=hint,
                            source_signal_id=signal.signal_id,
                            confidence=0.55,
                            metadata={"extraction_method": "community_hint_rule", "matched_hint": hint},
                        )
                    )
        return dedupe_by_key(entities, key=lambda item: item.normalized_key)
