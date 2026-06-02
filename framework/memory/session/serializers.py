"""Serializers between agent session records and MemoryRuntime records."""

from __future__ import annotations

import json

from framework.agent.session.models import AgentSessionEvent, AgentSessionItem, AgentSessionSnapshot
from framework.agent.session.sanitization import sanitize_session_content
from framework.memory.models import MemoryKind, MemoryRecord, MemoryScope


def item_to_memory_record(item: AgentSessionItem) -> MemoryRecord:
    """Convert a session item into a sanitized memory record."""

    content = {
        "role": item.role,
        "agentId": item.agent_id,
        "summary": item.summary,
        "content": sanitize_session_content(item.content),
    }
    return MemoryRecord(
        memory_id=f"agent-session-item:{item.item_id}",
        content=json.dumps(content, ensure_ascii=False, sort_keys=True, default=str),
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.SESSION,
        summary=item.summary or f"Session item {item.role}",
        metadata={
            "session_id": item.session_id,
            "run_id": item.run_id,
            "role": item.role,
            "agent_id": item.agent_id,
            "visibility": item.visibility.value,
            "status": item.status,
            "trace_kind": "agent_session_item",
        },
        refs=dict(sanitize_session_content(item.refs)),
        tags=["agent_session", item.role],
        confidence=item.confidence,
        namespace=f"agent_session:{item.session_id}",
    )


def event_to_memory_record(event: AgentSessionEvent) -> MemoryRecord:
    """Convert a session event into a trace memory record."""

    payload = sanitize_session_content(event.payload)
    content = {
        "eventType": event.event_type,
        "agentId": event.agent_id,
        "role": event.role,
        "itemId": event.item_id,
        "payload": payload,
    }
    summary_parts = [event.event_type]
    if event.role:
        summary_parts.append(event.role)
    if event.agent_id:
        summary_parts.append(event.agent_id)
    return MemoryRecord(
        memory_id=f"agent-session-event:{event.event_id}",
        content=json.dumps(content, ensure_ascii=False, sort_keys=True, default=str),
        kind=MemoryKind.OBSERVATION,
        scope=MemoryScope.SESSION,
        summary=" ".join(summary_parts),
        metadata={
            "session_id": event.session_id,
            "run_id": event.run_id,
            "event_type": event.event_type,
            "agent_id": event.agent_id,
            "role": event.role,
            "item_id": event.item_id,
            "created_at": event.created_at,
            "trace_kind": "agent_session_event",
        },
        refs={
            key: value
            for key, value in {
                "session_id": event.session_id,
                "run_id": event.run_id,
                "event_id": event.event_id,
                "item_id": event.item_id,
            }.items()
            if value
        },
        tags=["agent_session", "agent_session_event", event.event_type],
        namespace=f"agent_session:{event.session_id}",
    )


def snapshot_to_memory_record(snapshot: AgentSessionSnapshot) -> MemoryRecord:
    """Convert a session snapshot into a memory record."""

    return MemoryRecord(
        memory_id=f"agent-session-snapshot:{snapshot.snapshot_id}",
        content=snapshot.summary,
        kind=MemoryKind.SEMANTIC,
        scope=MemoryScope.SESSION,
        summary=snapshot.summary,
        metadata={
            "session_id": snapshot.session_id,
            "run_id": snapshot.run_id,
            "role_summaries": sanitize_session_content(snapshot.role_summaries),
            "final_items": list(snapshot.final_items),
            "trace_kind": "agent_session_snapshot",
        },
        refs={"session_id": snapshot.session_id, "snapshot_id": snapshot.snapshot_id},
        tags=["agent_session_snapshot"],
        namespace=f"agent_session_snapshot:{snapshot.session_id}",
    )
