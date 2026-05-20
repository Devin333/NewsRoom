from __future__ import annotations

from typing import Any

from framework.memory.diagnostics.inspector import MemoryRuntimeInspection


class MemoryDiagnosticsReportBuilder:
    def build_markdown(self, inspection: MemoryRuntimeInspection) -> str:
        payload = inspection.to_dict()
        return "\n".join(
            [
                "# Memory Diagnostics",
                f"- Store: {payload['store_type']}",
                f"- Health: {payload['health']['status']}",
                f"- Records: {payload['metrics']['total_records']}",
            ]
        )

    def build_json(self, inspection: MemoryRuntimeInspection) -> dict[str, Any]:
        return inspection.to_dict()
