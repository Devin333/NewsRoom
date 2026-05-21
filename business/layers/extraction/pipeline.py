from __future__ import annotations

from business.foundation import AnalysisContext, Claim, Entity, Signal, Technology, Topic
from business.layers.extraction.claim_extractor import ClaimExtractor
from business.layers.extraction.entity_extractor import EntityExtractor
from business.layers.extraction.models import ExtractionResult, ExtractionWarning, TaxonomyAssignment
from business.layers.extraction.taxonomy_classifier import TaxonomyClassifier
from business.layers.extraction.technology_extractor import TechnologyExtractor
from business.layers.extraction.topic_extractor import TopicExtractor


class ExtractionPipeline:
    def __init__(
        self,
        *,
        entity_extractor: EntityExtractor | None = None,
        topic_extractor: TopicExtractor | None = None,
        technology_extractor: TechnologyExtractor | None = None,
        claim_extractor: ClaimExtractor | None = None,
        taxonomy_classifier: TaxonomyClassifier | None = None,
    ) -> None:
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.topic_extractor = topic_extractor or TopicExtractor()
        self.technology_extractor = technology_extractor or TechnologyExtractor()
        self.claim_extractor = claim_extractor or ClaimExtractor()
        self.taxonomy_classifier = taxonomy_classifier or TaxonomyClassifier()

    def run(self, signals: list[Signal], context: AnalysisContext) -> list[ExtractionResult]:
        return [self.extract(signal, context) for signal in signals]

    def extract(self, signal: Signal, context: AnalysisContext) -> ExtractionResult:
        entities = self.entity_extractor.extract(signal, context)
        topics = self.topic_extractor.extract(signal, context)
        technologies = self.technology_extractor.extract(signal, context)
        claims = self.claim_extractor.extract(
            signal,
            context,
            entities=entities,
            topics=topics,
            technologies=technologies,
        )
        assignments = self.taxonomy_classifier.classify_signal(signal, topics, technologies)
        warnings = _warnings(signal, entities, topics, technologies, claims)
        return ExtractionResult(
            signal_id=signal.signal_id,
            entities=entities,
            topics=topics,
            technologies=technologies,
            claims=claims,
            taxonomy_assignments=assignments,
            warnings=warnings,
            metadata={
                "board_type": signal.board_type.value,
                "signal_type": signal.signal_type.value,
                "taxonomy_version": context.taxonomy_version,
                "extractors": {
                    "entities": self.entity_extractor.__class__.__name__,
                    "topics": self.topic_extractor.__class__.__name__,
                    "technologies": self.technology_extractor.__class__.__name__,
                    "claims": self.claim_extractor.__class__.__name__,
                    "taxonomy": self.taxonomy_classifier.__class__.__name__,
                },
            },
        )

    def _extract_entities(self, signal: Signal) -> list[Entity]:
        return self.entity_extractor.extract(signal, AnalysisContext(board_type=signal.board_type))

    def _extract_topics(self, signal: Signal) -> list[Topic]:
        return self.topic_extractor.extract(signal, AnalysisContext(board_type=signal.board_type))

    def _extract_technologies(self, signal: Signal) -> list[Technology]:
        return self.technology_extractor.extract(signal, AnalysisContext(board_type=signal.board_type))

    def _extract_claims(
        self,
        signal: Signal,
        entities: list[Entity],
        topics: list[Topic],
        technologies: list[Technology],
    ) -> list[Claim]:
        return self.claim_extractor.extract(
            signal,
            AnalysisContext(board_type=signal.board_type),
            entities=entities,
            topics=topics,
            technologies=technologies,
        )

    def _classify(
        self,
        signal: Signal,
        topics: list[Topic],
        technologies: list[Technology],
    ) -> list[TaxonomyAssignment]:
        return self.taxonomy_classifier.classify_signal(signal, topics, technologies)


def _warnings(
    signal: Signal,
    entities: list[Entity],
    topics: list[Topic],
    technologies: list[Technology],
    claims: list[Claim],
) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    if not technologies:
        warnings.append(
            ExtractionWarning(
                signal_id=signal.signal_id,
                warning_type="no_technology_detected",
                message="No technology keyword matched this signal.",
            )
        )
    if not claims:
        warnings.append(
            ExtractionWarning(
                signal_id=signal.signal_id,
                warning_type="no_claim_detected",
                message="No claim could be derived from extracted objects.",
            )
        )
    if topics and topics[0].normalized_key == "unknown_topic" and not entities:
        warnings.append(
            ExtractionWarning(
                signal_id=signal.signal_id,
                warning_type="fallback_topic_without_entity",
                message="Signal only produced a fallback topic and no entity.",
            )
        )
    return warnings
