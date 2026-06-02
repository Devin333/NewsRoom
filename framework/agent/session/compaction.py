"""Session compaction utilities for long-running agent collaboration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionSnapshot


class SessionCompactor:
    """Create compact snapshots from session items and events."""

    def __init__(self, *, max_items_before_compaction: int = 50) -> None:
        self.max_items_before_compaction = max_items_before_compaction

    def should_compact(self, *, items: Sequence[AgentSessionItem]) -> bool:
        """Return whether a snapshot should be created."""

        return len(items) >= self.max_items_before_compaction

    def compact(
        self,
        *,
        session_id: str,
        run_id: str,
        items: Sequence[AgentSessionItem],
        events: Sequence[AgentSessionEvent],
    ) -> AgentSessionSnapshot:
        """Build a role-oriented snapshot without copying raw content."""

        role_summaries: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "summaries": [], "evidenceRefs": []})
        final_items: list[str] = []
        for item in items:
            bucket = role_summaries[item.role]
            bucket["count"] += 1
            if item.summary:
                bucket["summaries"].append(item.summary)
            evidence_refs = item.metadata.get("evidenceRefs") if isinstance(item.metadata, dict) else None
            if isinstance(evidence_refs, list):
                bucket["evidenceRefs"].extend(evidence_refs[:10])
            if item.status == "final" or item.visibility.value == "final":
                final_items.append(item.item_id)
        summary = "; ".join(f"{role}: {payload['count']}" for role, payload in sorted(role_summaries.items()))
        return AgentSessionSnapshot(
            session_id=session_id,
            run_id=run_id,
            summary=summary or "Empty shared agent session.",
            role_summaries={role: dict(payload) for role, payload in role_summaries.items()},
            final_items=tuple(final_items),
            source_event_ids=tuple(event.event_id for event in events),
        )
