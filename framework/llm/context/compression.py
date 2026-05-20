from __future__ import annotations

from framework.llm.models.message import LLMMessage


class LLMContextCompressor:
    def compress(self, messages: list[dict | LLMMessage], target_tokens: int):
        return self.compress_messages(messages, target_tokens)

    def compress_messages(self, messages: list[dict | LLMMessage], target_tokens: int):
        if target_tokens < 1:
            raise ValueError("target_tokens must be positive")
        # Keep this deterministic and conservative for v1: drop oldest messages until
        # the rough content length falls under the target.
        remaining = list(messages)
        while len(_joined_content(remaining)) / 4 > target_tokens and len(remaining) > 1:
            remaining.pop(0)
        return remaining


def _joined_content(messages: list[dict | LLMMessage]) -> str:
    parts = []
    for message in messages:
        if isinstance(message, LLMMessage):
            parts.append(message.content)
        else:
            parts.append(str(message.get("content") or ""))
    return "\n".join(parts)

