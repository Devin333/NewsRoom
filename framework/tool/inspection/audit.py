from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from framework.tool.models.call import ToolCall
from framework.tool.models.result import ToolResult


@dataclass(frozen=True)
class ToolAuditRecord:
    call: ToolCall
    result: ToolResult
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call": self.call.to_dict(),
            "result": self.result.to_dict(),
            "recorded_at": self.recorded_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }


class ToolAuditRecorder:
    def __init__(self) -> None:
        self._records: list[ToolAuditRecord] = []

    def record(self, call: ToolCall, result: ToolResult) -> None:
        self._records.append(ToolAuditRecord(call=call, result=result))

    def list_records(self) -> list[ToolAuditRecord]:
        return list(self._records)
