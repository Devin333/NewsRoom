"""Prompt context assembler for shared agent session items."""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape

from framework.agent.session.models import AgentSessionContext, AgentSessionItem, SessionVisibility
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
        include_content: bool = True,
    ) -> AgentSessionContext:
        """Return assembled context text and accurate character count."""

        ordered_items = _prioritized_items(items)
        context_text = _truncate_context(
            _render_context(session_id=session_id, items=ordered_items, include_content=include_content),
            max_context_chars=max_context_chars,
        )
        return AgentSessionContext(
            session_id=session_id,
            items=tuple(ordered_items),
            context_text=context_text,
            char_count=len(context_text),
        )


def _render_context(*, session_id: str, items: Sequence[AgentSessionItem], include_content: bool) -> str:
    lines = [f'<shared_agent_session session_id="{escape(session_id, quote=True)}">']
    for item in items:
        if item.visibility == SessionVisibility.PRIVATE:
            continue
        confidence = "" if item.confidence is None else f' confidence="{item.confidence:.3g}"'
        status = f' status="{escape(item.status, quote=True)}"'
        visibility = f' visibility="{escape(item.visibility.value, quote=True)}"'
        lines.append(
            f'  <item role="{escape(item.role, quote=True)}" '
            f'agent_id="{escape(item.agent_id, quote=True)}"{confidence}{status}{visibility}>'
        )
        if item.summary:
            lines.append(f"    <summary>{escape(item.summary)}</summary>")
        if include_content:
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


def _prioritized_items(items: Sequence[AgentSessionItem]) -> list[AgentSessionItem]:
    return sorted(
        items,
        key=lambda item: (
            0 if item.visibility == SessionVisibility.FINAL or item.status == "final" else 1,
            item.created_at or "",
        ),
        reverse=False,
    )


def _truncate_context(value: str, *, max_context_chars: int | None) -> str:
    if max_context_chars is None or max_context_chars < 0 or len(value) <= max_context_chars:
        return value
    if max_context_chars <= len(TRUNCATED_CONTEXT_SUFFIX):
        return value[:max_context_chars]
    limit = max_context_chars - len(TRUNCATED_CONTEXT_SUFFIX)
    return f"{value[:limit]}{TRUNCATED_CONTEXT_SUFFIX}"
