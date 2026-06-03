from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from interfaces.services.daily_interface_projection import project_run_output_for_interface


@dataclass(frozen=True)
class InterfaceRunReportProjection:
    output: Any
    report_status: str | None = None
    report_id: str | None = None


def project_run_report_for_interface(payload: dict[str, Any]) -> InterfaceRunReportProjection:
    output = project_run_output_for_interface(payload)
    report_status = report_status_from_interface_output(output)
    return InterfaceRunReportProjection(
        output=output,
        report_status=report_status,
        report_id=report_id_from_interface_output(
            output,
            run_id=_optional_text(payload.get("run_id")),
            report_status=report_status,
        ),
    )


def report_status_from_interface_output(output: Any) -> str | None:
    if not isinstance(output, Mapping):
        return None
    value = output.get("report_status")
    if value:
        return str(value)
    report = output.get("report")
    if isinstance(report, Mapping) and report.get("status"):
        return str(report["status"])
    if output.get("final_report") is not None:
        return "final"
    if output.get("blocked_report") is not None:
        return "blocked"
    return None


def report_id_from_interface_output(
    output: Any,
    *,
    run_id: str | None = None,
    report_status: str | None = None,
) -> str | None:
    if not isinstance(output, Mapping):
        return None
    for key in ("report_id", "final_report_id"):
        value = _optional_text(output.get(key))
        if value:
            return value
    resolved_status = report_status or report_status_from_interface_output(output)
    if run_id and resolved_status in {"final", "blocked"}:
        return f"{run_id}:{resolved_status}"
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


__all__ = [
    "InterfaceRunReportProjection",
    "project_run_report_for_interface",
    "report_id_from_interface_output",
    "report_status_from_interface_output",
]
