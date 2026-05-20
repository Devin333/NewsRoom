from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryContextBlock:
    content: str
    token_estimate: int
    memory_ids: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "MemoryContextBlock":
        return cls(content="", token_estimate=0, memory_ids=[])

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "token_estimate": self.token_estimate,
            "memory_ids": list(self.memory_ids),
            "citations": list(self.citations),
            "diagnostics": dict(self.diagnostics),
        }

    def is_empty(self) -> bool:
        return not self.content.strip()

    def append(self, content: str, *, memory_id: str | None = None) -> "MemoryContextBlock":
        text = str(content or "")
        separator = "\n" if self.content and text else ""
        memory_ids = list(self.memory_ids)
        if memory_id:
            memory_ids.append(str(memory_id))
        combined = f"{self.content}{separator}{text}"
        return MemoryContextBlock(
            content=combined,
            token_estimate=estimate_tokens(combined),
            memory_ids=memory_ids,
            citations=list(self.citations),
            diagnostics=dict(self.diagnostics),
        )


def estimate_tokens(text: str) -> int:
    normalized = str(text or "")
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)
