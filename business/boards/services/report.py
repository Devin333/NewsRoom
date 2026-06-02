from __future__ import annotations

from business.foundation import Report
from business.layers.output import BoardOutput


class BoardReportExtractionService:
    def extract_reports(self, output: BoardOutput) -> list[Report]:
        payload = self.report_payload(output)
        if payload is None:
            return []
        return [Report.model_validate(_report_payload_for_validation(payload))]

    def require_report(self, output: BoardOutput) -> Report:
        reports = self.extract_reports(output)
        if not reports:
            raise ValueError("board output does not include a report payload")
        return reports[0]

    def report_payload(self, output: BoardOutput) -> dict[str, object] | None:
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


__all__ = ["BoardReportExtractionService"]
