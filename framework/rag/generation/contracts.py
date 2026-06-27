from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RAGGenerationContext:
    context_id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "text": self.text,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GeneratedRAGAnswer:
    question: str
    answer: str
    context_ids: tuple[str, ...] = ()
    contexts: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "context_ids": list(self.context_ids),
            "contexts": list(self.contexts),
            "metadata": dict(self.metadata),
        }


__all__ = ["GeneratedRAGAnswer", "RAGGenerationContext"]
