from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from framework.tool.governance.redaction import redact_sensitive_values


def run_events_sse_frames(payload: dict[str, Any]) -> Iterable[str]:
    run_id = str(payload.get("run_id") or "")
    durable_source = (
        payload.get("source") == "durable_store"
        and payload.get("availability") == "available"
    )
    for event in payload.get("events") or []:
        event_payload = event if isinstance(event, dict) else {}
        event_type = str(event_payload.get("event_type") or "run.event")
        sequence = event_payload.get("stream_sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            sequence = None
        event_id = event_payload.get("sse_resume_cursor") if durable_source else None
        yield sse_frame(
            event_type,
            {
                "run_id": run_id,
                "sequence": sequence,
                "event": redact_sensitive_values(event_payload),
            },
            event_id=(event_id if isinstance(event_id, str) else None),
        )
    yield sse_frame(
        "run.events.done",
        {
            "run_id": run_id,
            "event_count": int(payload.get("event_count") or 0),
            "events_path": payload.get("events_path"),
            "availability": payload.get("availability"),
            "source": payload.get("source"),
            "high_watermark": payload.get("high_watermark"),
            "next_sequence_cursor": payload.get("next_sequence_cursor"),
            "projection_status": payload.get("projection_status"),
            "projection_checksum": payload.get("projection_checksum"),
            "projection_high_watermark": payload.get("projection_high_watermark"),
            "unavailable_reason_class": payload.get("unavailable_reason_class"),
            "sse_resume_cursor": payload.get("sse_resume_cursor"),
        },
    )


def sse_frame(
    event_name: str,
    data: dict[str, Any],
    *,
    event_id: str | None = None,
) -> str:
    id_line = "" if event_id is None else f"id: {event_id}\n"
    return (
        f"{id_line}event: {event_name}\n"
        f"data: {json.dumps(redact_sensitive_values(data), ensure_ascii=False, sort_keys=True)}\n\n"
    )


__all__ = ["run_events_sse_frames"]
