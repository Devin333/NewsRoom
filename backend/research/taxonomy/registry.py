from __future__ import annotations

from dataclasses import dataclass

from backend.foundation import normalize_key
from backend.research.taxonomy.models import TaxonomyLevel, TaxonomyTerm


DEFAULT_DOMAINS = ("General", "Vision", "Video", "Language", "Audio", "Robotics", "Multimodal", "Code")
DEFAULT_AREAS = (
    "Agent",
    "Image Understanding",
    "Reasoning",
    "Question Answering",
    "Generation",
    "Retrieval",
    "Evaluation",
    "Planning",
    "Tool Use",
)
DEFAULT_TASKS = (
    "web agent",
    "code agent",
    "tool use",
    "visual question answering",
    "image captioning",
    "long-context QA",
    "math reasoning",
    "paper reading",
    "benchmark evaluation",
    "skill evolution",
)


@dataclass(frozen=True)
class TaxonomyRegistry:
    terms: tuple[TaxonomyTerm, ...]

    @classmethod
    def default(cls) -> "TaxonomyRegistry":
        terms: list[TaxonomyTerm] = []
        terms.extend(_terms("domain", DEFAULT_DOMAINS))
        terms.extend(_terms("area", DEFAULT_AREAS))
        terms.extend(_terms("task", DEFAULT_TASKS))
        return cls(terms=tuple(terms))

    def has_term(self, level: TaxonomyLevel, term_id: str) -> bool:
        return self.get(level, term_id) is not None

    def get(self, level: TaxonomyLevel, term_id: str) -> TaxonomyTerm | None:
        key = normalize_key(term_id)
        for term in self.terms:
            if term.level == level and term.term_id == key:
                return term
        return None

    def labels_for(self, level: TaxonomyLevel) -> tuple[str, ...]:
        return tuple(term.label for term in self.terms if term.level == level)


def _terms(level: TaxonomyLevel, labels: tuple[str, ...]) -> list[TaxonomyTerm]:
    return [TaxonomyTerm(term_id=normalize_key(label), level=level, label=label) for label in labels]


__all__ = ["DEFAULT_AREAS", "DEFAULT_DOMAINS", "DEFAULT_TASKS", "TaxonomyRegistry"]
