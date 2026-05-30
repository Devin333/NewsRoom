from __future__ import annotations

import json
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any

from infrastructure.storage.conversation.models import (
    AgentMessageRecord,
    AgentIterationCheckpoint,
    ConversationCompactionRecord,
    ConversationCursor,
)
from infrastructure.storage.security import StorageRedactor


class ConversationNotFoundError(FileNotFoundError):
    pass


class LocalJsonConversationStore:
    def __init__(
        self,
        root: str | Path = ".newsroom/conversations",
        *,
        redactor: StorageRedactor | None = None,
    ) -> None:
        self.root = Path(root)
        self.redactor = redactor or StorageRedactor()

    def append_message(self, conversation_id: str, message: AgentMessageRecord) -> Path:
        _validate_id(conversation_id, "conversation_id")
        _validate_id(message.message_id, "message_id")
        if message.conversation_id != conversation_id:
            raise ValueError("message conversation_id does not match")
        message = self._redacted_message(message)
        path = self._messages_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path

    def read_messages(self, conversation_id: str, limit: int | None = None) -> list[AgentMessageRecord]:
        _validate_id(conversation_id, "conversation_id")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        path = self._messages_path(conversation_id)
        if not path.exists():
            return []
        messages = _read_messages(path)
        if limit is not None:
            return messages[-limit:]
        return messages

    def write_summary(self, conversation_id: str, summary: str) -> Path:
        _validate_id(conversation_id, "conversation_id")
        redaction = self.redactor.redact(
            summary,
            run_id=conversation_id,
            artifact_id="conversation_summary",
        )
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "summary": redaction.value,
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "redacted": True,
        }
        if redaction.redacted:
            payload["redaction_report"] = redaction.report.to_dict()
        path = self._summary_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def get_summary(self, conversation_id: str) -> str | None:
        _validate_id(conversation_id, "conversation_id")
        path = self._summary_path(conversation_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("summary") or "")

    def compact_messages(
        self,
        conversation_id: str,
        *,
        keep_last: int = 10,
        max_summary_chars: int = 2000,
    ) -> ConversationCompactionRecord | None:
        _validate_id(conversation_id, "conversation_id")
        if keep_last < 0:
            raise ValueError("keep_last must be non-negative")
        if max_summary_chars <= 0:
            raise ValueError("max_summary_chars must be greater than zero")

        messages = self.read_messages(conversation_id)
        if len(messages) <= keep_last:
            return None
        compacted = messages[:-keep_last] if keep_last else messages
        retained = messages[-keep_last:] if keep_last else []
        summary = _build_compaction_summary(
            compacted,
            retained_count=len(retained),
            max_summary_chars=max_summary_chars,
        )
        redaction = self.redactor.redact(
            summary,
            run_id=conversation_id,
            artifact_id="conversation_compaction",
        )
        metadata: dict[str, Any] = {
            "retained_message_ids": [message.message_id for message in retained],
            "role_counts": _role_counts(messages),
        }
        if redaction.redacted:
            metadata["redaction_report"] = redaction.report.to_dict()
        marker_message = AgentMessageRecord(
            message_id=_compaction_marker_message_id(compacted[-1].message_id if compacted else "none"),
            conversation_id=conversation_id,
            role="system",
            content={
                "summary": str(redaction.value),
                "compacted_message_count": len(compacted),
                "retained_message_count": len(retained),
                "compacted_until_message_id": compacted[-1].message_id if compacted else None,
            },
            created_at=datetime.now(UTC),
            redacted=True,
            metadata={
                "message_type": "conversation_compaction",
                "compacted_until_message_id": compacted[-1].message_id if compacted else None,
                "retained_message_ids": [message.message_id for message in retained],
            },
        )
        record = ConversationCompactionRecord(
            conversation_id=conversation_id,
            summary=str(redaction.value),
            original_message_count=len(messages),
            compacted_message_count=len(compacted),
            retained_message_count=len(retained),
            marker_message_id=marker_message.message_id,
            compacted_until_message_id=compacted[-1].message_id if compacted else None,
            metadata=metadata,
        )
        path = self._compaction_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        self._write_messages(conversation_id, [marker_message, *retained])
        self.write_summary(conversation_id, record.summary)
        return record

    def get_compaction(self, conversation_id: str) -> ConversationCompactionRecord | None:
        _validate_id(conversation_id, "conversation_id")
        path = self._compaction_path(conversation_id)
        if not path.exists():
            return None
        return ConversationCompactionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write_cursor(self, cursor: ConversationCursor) -> Path:
        _validate_id(cursor.conversation_id, "conversation_id")
        _validate_optional_id(cursor.message_id, "message_id")
        _validate_optional_id(cursor.run_id, "run_id")
        _validate_optional_id(cursor.step_id, "step_id")
        _validate_optional_id(cursor.workflow_checkpoint_id, "workflow_checkpoint_id")
        metadata_redaction = self.redactor.redact(
            cursor.metadata,
            run_id=cursor.conversation_id,
            artifact_id="conversation_cursor",
        )
        metadata = dict(metadata_redaction.value)
        if metadata_redaction.redacted:
            metadata["redaction_report"] = metadata_redaction.report.to_dict()
        safe_cursor = ConversationCursor(
            conversation_id=cursor.conversation_id,
            message_offset=cursor.message_offset,
            message_id=cursor.message_id,
            run_id=cursor.run_id,
            step_id=cursor.step_id,
            workflow_checkpoint_id=cursor.workflow_checkpoint_id,
            updated_at=cursor.updated_at,
            metadata=metadata,
        )
        path = self._cursor_path(cursor.conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(safe_cursor.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def read_cursor(self, conversation_id: str) -> ConversationCursor | None:
        _validate_id(conversation_id, "conversation_id")
        path = self._cursor_path(conversation_id)
        if not path.exists():
            return None
        return ConversationCursor.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write_iteration_checkpoint(self, checkpoint: AgentIterationCheckpoint) -> Path:
        _validate_id(checkpoint.conversation_id, "conversation_id")
        _validate_id(checkpoint.agent_id, "agent_id")
        _validate_optional_id(checkpoint.run_id, "run_id")
        _validate_optional_id(checkpoint.step_id, "step_id")
        _validate_optional_id(checkpoint.workflow_checkpoint_id, "workflow_checkpoint_id")
        _validate_optional_id(checkpoint.message_id, "message_id")
        metadata_redaction = self.redactor.redact(
            checkpoint.metadata,
            run_id=checkpoint.conversation_id,
            artifact_id="agent_iteration_checkpoint_metadata",
        )
        diagnostics_redaction = self.redactor.redact(
            checkpoint.diagnostics_summary,
            run_id=checkpoint.conversation_id,
            artifact_id="agent_iteration_checkpoint_diagnostics",
        )
        metadata = dict(metadata_redaction.value)
        diagnostics_summary = dict(diagnostics_redaction.value)
        reports = []
        if metadata_redaction.redacted:
            reports.append(metadata_redaction.report.to_dict())
        if diagnostics_redaction.redacted:
            reports.append(diagnostics_redaction.report.to_dict())
        if reports:
            metadata["redaction_reports"] = reports
        safe_checkpoint = AgentIterationCheckpoint(
            conversation_id=checkpoint.conversation_id,
            agent_id=checkpoint.agent_id,
            iteration=checkpoint.iteration,
            status=checkpoint.status,
            stop_reason=checkpoint.stop_reason,
            run_id=checkpoint.run_id,
            step_id=checkpoint.step_id,
            workflow_checkpoint_id=checkpoint.workflow_checkpoint_id,
            message_id=checkpoint.message_id,
            trace_summary=dict(checkpoint.trace_summary),
            diagnostics_summary=diagnostics_summary,
            last_tool_observation=(
                dict(checkpoint.last_tool_observation)
                if checkpoint.last_tool_observation is not None
                else None
            ),
            llm_call_artifact_ids=list(checkpoint.llm_call_artifact_ids),
            updated_at=checkpoint.updated_at,
            metadata=metadata,
        )
        path = self._iteration_checkpoint_path(checkpoint.conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(safe_checkpoint.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return path

    def read_iteration_checkpoint(self, conversation_id: str) -> AgentIterationCheckpoint | None:
        _validate_id(conversation_id, "conversation_id")
        path = self._iteration_checkpoint_path(conversation_id)
        if not path.exists():
            return None
        return AgentIterationCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _redacted_message(self, message: AgentMessageRecord) -> AgentMessageRecord:
        content_redaction = self.redactor.redact(
            message.content,
            run_id=message.conversation_id,
            artifact_id=message.message_id,
        )
        metadata_redaction = self.redactor.redact(
            message.metadata,
            run_id=message.conversation_id,
            artifact_id=message.message_id,
        )
        metadata = dict(metadata_redaction.value)
        reports = []
        if content_redaction.redacted:
            reports.append(content_redaction.report.to_dict())
        if metadata_redaction.redacted:
            reports.append(metadata_redaction.report.to_dict())
        if reports:
            metadata["redaction_reports"] = reports
        return AgentMessageRecord(
            message_id=message.message_id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=content_redaction.value,
            created_at=message.created_at,
            agent_id=message.agent_id,
            run_id=message.run_id,
            step_id=message.step_id,
            redacted=True,
            metadata=metadata,
        )

    def _messages_path(self, conversation_id: str) -> Path:
        _validate_id(conversation_id, "conversation_id")
        return self.root / conversation_id / "messages.jsonl"

    def _summary_path(self, conversation_id: str) -> Path:
        _validate_id(conversation_id, "conversation_id")
        return self.root / conversation_id / "summary.json"

    def _compaction_path(self, conversation_id: str) -> Path:
        _validate_id(conversation_id, "conversation_id")
        return self.root / conversation_id / "compaction.json"

    def _cursor_path(self, conversation_id: str) -> Path:
        _validate_id(conversation_id, "conversation_id")
        return self.root / conversation_id / "cursor.json"

    def _iteration_checkpoint_path(self, conversation_id: str) -> Path:
        _validate_id(conversation_id, "conversation_id")
        return self.root / conversation_id / "iteration_checkpoint.json"

    def _write_messages(self, conversation_id: str, messages: list[AgentMessageRecord]) -> Path:
        path = self._messages_path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for message in messages:
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        return path


def _read_messages(path: Path) -> list[AgentMessageRecord]:
    messages = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            messages.append(AgentMessageRecord.from_dict(json.loads(stripped)))
    return messages


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")


def _validate_optional_id(value: str | None, label: str) -> None:
    if value is None:
        return
    _validate_id(value, label)


def _build_compaction_summary(
    messages: list[AgentMessageRecord],
    *,
    retained_count: int,
    max_summary_chars: int,
) -> str:
    role_counts = _role_counts(messages)
    lines = [
        (
            "Compacted "
            f"{len(messages)} older conversation messages; "
            f"retained last {retained_count} messages."
        ),
        "Role counts: "
        + ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items())),
    ]
    important = [
        message
        for message in messages
        if message.role in {"user", "judge", "diagnostic", "assistant"}
    ][-8:]
    if important:
        lines.append("Recent compacted highlights:")
        for message in important:
            lines.append(f"- {message.role}: {_preview(message.content, max_chars=180)}")
    summary = "\n".join(lines)
    if len(summary) <= max_summary_chars:
        return summary
    return summary[: max_summary_chars - 3].rstrip() + "..."


def _role_counts(messages: list[AgentMessageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for message in messages:
        counts[message.role] = counts.get(message.role, 0) + 1
    return counts


def _preview(value: Any, *, max_chars: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _compaction_marker_message_id(compacted_until_message_id: str) -> str:
    safe_id = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in compacted_until_message_id
    ).strip("._-")
    return f"compaction-{safe_id or 'messages'}"
