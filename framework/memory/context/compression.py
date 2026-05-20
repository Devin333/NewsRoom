from __future__ import annotations


class MemoryContextCompressor:
    def compress(self, text: str, *, max_tokens: int) -> str:
        char_budget = max(16, int(max_tokens) * 4)
        if len(text) <= char_budget:
            return text
        return text[: char_budget - 3] + "..."
