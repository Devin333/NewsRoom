from __future__ import annotations

from backend.foundation import AnalysisContext, Entity, EntityType, Signal
from backend.layers.extraction.rules import (
    COMPANY_HINTS,
    KNOWN_MODEL_HINTS,
    build_entity,
    dedupe_by_key,
    github_repo_from_signal,
    paper_id_from_signal,
    signal_text,
)


def _context_board_value(signal: Signal, context: AnalysisContext | None) -> str:
    board_type = context.board_type if context and context.board_type is not None else signal.board_type
    return board_type.value


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
                        metadata={"extraction_method": "github_repo_rule", "context_board": _context_board_value(signal, context)},
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
                        metadata={"extraction_method": "paper_id_rule", "context_board": _context_board_value(signal, context)},
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
