from __future__ import annotations

import re
from collections.abc import Sequence

DEFAULT_GROUNDED_SYSTEM_INSTRUCTION = (
    "You are a research assistant answering questions about an academic paper. "
    "Answer ONLY from the numbered context passages below. "
    "Cite the passages you use with bracketed numbers like [1], [2]. "
    "If the context does not contain the answer, say so explicitly. "
    "Be concise and precise."
)

_BRACKET_CITATION_RE = re.compile(r"\[(\d+)\]")


def build_numbered_context_prompt(
    *,
    question: str,
    contexts: Sequence[str],
    system_instruction: str = DEFAULT_GROUNDED_SYSTEM_INSTRUCTION,
) -> str:
    numbered = "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(contexts))
    return (
        f"{system_instruction}\n\n"
        f"Context passages:\n{numbered}\n\n"
        f"Question: {question}\n\n"
        "Answer (with citations):"
    )


def cited_context_indexes(answer: str, *, context_count: int) -> tuple[int, ...]:
    seen: set[int] = set()
    out: list[int] = []
    for match in _BRACKET_CITATION_RE.finditer(answer):
        index = int(match.group(1)) - 1
        if index < 0 or index >= context_count or index in seen:
            continue
        out.append(index)
        seen.add(index)
    return tuple(out)


__all__ = [
    "DEFAULT_GROUNDED_SYSTEM_INSTRUCTION",
    "build_numbered_context_prompt",
    "cited_context_indexes",
]
