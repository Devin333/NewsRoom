"""Prompt context assembler for shared agent session items."""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape

from framework.agent.session.models import AgentSessionContext, AgentSessionItem
from framework.agent.session.sanitization import sanitize_session_content


TRUNCATED_CONTEXT_SUFFIX = "\n...[truncated]"


class SharedSessionContextAssembler:
    """Assemble readable XML-like context text from shared session items."""

    def assemble(
        self,
        *,
        session_id: str,
        items: Sequence[AgentSessionItem],
        max_context_chars: int | None = None,
    ) -> AgentSessionContext:
        """Return assembled context text and accurate character count."""

        context_text = _truncate_context(
            _render_context(session_id=session_id, items=items),
            max_context_chars=max_context_chars,
        )
        return AgentSessionContext(
            session_id=session_id,
            items=tuple(items),
            context_text=context_text,
            char_count=len(context_text),
        )


def _render_context(*, session_id: str, items: Sequence[AgentSessionItem]) -> str:
    lines = [f'<shared_agent_session session_id="{escape(session_id, quote=True)}">']
    for item in items:
        confidence = "" if item.confidence is None else f' confidence="{item.confidence:.3g}"'
        lines.append(
            f'  <item role="{escape(item.role, quote=True)}" '
            f'agent_id="{escape(item.agent_id, quote=True)}"{confidence}>'
        )
        if item.summary:
            lines.append(f"    <summary>{escape(item.summary)}</summary>")
        content = json.dumps(
            sanitize_session_content(item.content),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        lines.append(f"    <content>{escape(content)}</content>")
        lines.append("  </item>")
    lines.append("</shared_agent_session>")
    return "\n".join(lines)


def _truncate_context(value: str, *, max_context_chars: int | None) -> str:
    if max_context_chars is None or max_context_chars < 0 or len(value) <= max_context_chars:
        return value
    if max_context_chars <= len(TRUNCATED_CONTEXT_SUFFIX):
        return value[:max_context_chars]
    limit = max_context_chars - len(TRUNCATED_CONTEXT_SUFFIX)
    return f"{value[:limit]}{TRUNCATED_CONTEXT_SUFFIX}"
