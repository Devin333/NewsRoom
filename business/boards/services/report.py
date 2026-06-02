from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business.boards.application.result import BoardReportExtractionResult
from business.foundation import BoardDefinition, Report
from business.layers.output import BoardOutput


@dataclass(frozen=True)
class BoardReportDescriptor:
    title: str
    summary: str


class BoardReportDescriptorService:
    def build(self, board_definition: BoardDefinition) -> BoardReportDescriptor:
        description = board_definition.description or board_definition.name
        return BoardReportDescriptor(
            title=f"{board_definition.name} Report",
            summary=f"{description} generated from normalized signals.",
        )


class BoardReportExtractionService:
    def extract(self, output: BoardOutput) -> BoardReportExtractionResult:
        payload = self.report_payload(output)
        if payload is None:
            return BoardReportExtractionResult(reports=[], payloads=[])
        report = Report.model_validate(_report_payload_for_validation(payload))
        return BoardReportExtractionResult(reports=[report], payloads=[dict(payload)])

    def extract_reports(self, output: BoardOutput) -> list[Report]:
        return self.extract(output).reports

    def require_report(self, output: BoardOutput) -> Report:
        reports = self.extract_reports(output)
        if not reports:
            raise ValueError("board output does not include a report payload")
        return reports[0]

    def report_payload(self, output: BoardOutput) -> dict[str, Any] | None:
        payload = output.metadata.get("report")
        if not isinstance(payload, dict):
            return None
        return dict(payload)


def _report_payload_for_validation(payload: dict[str, object]) -> dict[str, object]:
    cleaned = _drop_serialized_computed_fields(payload)
    if isinstance(cleaned, dict):
        cleaned.pop("board_name", None)
        return cleaned
    return dict(payload)


def _drop_serialized_computed_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _drop_serialized_computed_fields(item)
            for key, item in value.items()
            if key != "level"
        }
    if isinstance(value, list):
        return [_drop_serialized_computed_fields(item) for item in value]
    return value


__all__ = ["BoardReportDescriptor", "BoardReportDescriptorService", "BoardReportExtractionService"]
