from __future__ import annotations

from framework.rag.generation.contracts import GeneratedRAGAnswer, RAGGenerationContext
from framework.rag.generation.grounding import (
    DEFAULT_GROUNDED_SYSTEM_INSTRUCTION,
    build_numbered_context_prompt,
    cited_context_indexes,
)

__all__ = [
    "DEFAULT_GROUNDED_SYSTEM_INSTRUCTION",
    "GeneratedRAGAnswer",
    "RAGGenerationContext",
    "build_numbered_context_prompt",
    "cited_context_indexes",
]
