from __future__ import annotations

from pydantic import Field

from business.foundation import AnalysisContext, Confidence, ObjectRef, PrimitiveModel, Signal, TaxonomyType, Technology, Topic
from business.layers.extraction.models import TaxonomyAssignment


class TaxonomyClassifyInput(PrimitiveModel):
    object_ref: ObjectRef
    text: str
    candidate_labels: list[str] = Field(default_factory=list)
    context: AnalysisContext


class TaxonomyClassifyOutput(PrimitiveModel):
    assignments: list[TaxonomyAssignment] = Field(default_factory=list)


class TaxonomyClassifier:
    def classify(self, input: TaxonomyClassifyInput) -> TaxonomyClassifyOutput:
        labels = [label for label in input.candidate_labels if label and label.casefold() in input.text.casefold()]
        assignments = [
            TaxonomyAssignment(
                object_ref=input.object_ref,
                taxonomy_type=TaxonomyType.TOPIC,
                category=label,
                confidence=Confidence(value=0.6, factors=[], reason="candidate label matched text", evidence_count=1),
                evidence_text=input.text,
            )
            for label in labels
        ]
        return TaxonomyClassifyOutput(assignments=assignments)

    def classify_signal(
        self,
        signal: Signal,
        topics: list[Topic],
        technologies: list[Technology],
    ) -> list[TaxonomyAssignment]:
        assignments: list[TaxonomyAssignment] = []
        for topic in topics:
            assignments.append(
                TaxonomyAssignment(
                    object_ref=ObjectRef(object_type="topic", object_id=topic.topic_id, label=topic.name),
                    taxonomy_type=TaxonomyType.TOPIC,
                    category=topic.normalized_key,
                    confidence=Confidence(value=topic.confidence.value, factors=list(topic.confidence.factors), reason=topic.confidence.reason, evidence_count=topic.confidence.evidence_count),
                    evidence_text=signal.title,
                )
            )
        for technology in technologies:
            assignments.append(
                TaxonomyAssignment(
                    object_ref=ObjectRef(object_type="technology", object_id=technology.technology_id, label=technology.name),
                    taxonomy_type=TaxonomyType.TECHNOLOGY,
                    category=technology.category.value,
                    subcategory=technology.subcategory,
                    confidence=Confidence(
                        value=technology.confidence.value,
                        factors=list(technology.confidence.factors),
                        reason=technology.confidence.reason,
                        evidence_count=technology.confidence.evidence_count,
                    ),
                    evidence_text=signal.summary or signal.title,
                )
            )
        return assignments
