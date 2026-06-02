from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


REPORT_PAYLOAD_KEYS = ("report", "report_metadata", "blocked_report")


@dataclass(frozen=True)
class WorkerReportPayload:
    source_key: str | None
    payload: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False

    @classmethod
    def from_mapping(cls, output: Mapping[str, Any]) -> "WorkerReportPayload":
        for key in REPORT_PAYLOAD_KEYS:
            if key not in output:
                continue
            report = output.get(key)
            if isinstance(report, Mapping):
                return cls(source_key=key, payload=dict(report), blocked=key == "blocked_report")
            if key == "blocked_report":
                return cls(source_key=key, blocked=True)
        return cls(source_key=None)

    @property
    def status(self) -> str | None:
        value = self.payload.get("status") or self.payload.get("report_status")
        if value is not None:
            return str(value)
        if self.blocked:
            return "blocked"
        return None

    @property
    def summary(self) -> dict[str, Any]:
        return summary_fields(self.payload)


@dataclass(frozen=True)
class WorkerOutputEnvelope:
    payload: dict[str, Any]
    run_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, run_id: str | None = None) -> "WorkerOutputEnvelope":
        output = dict(payload)
        actual_run_id = output.get("run_id") or run_id
        if actual_run_id is not None:
            output.setdefault("run_id", actual_run_id)
        output.setdefault("artifact_dir", output.get("artifact_dir"))
        output.setdefault("summary", summary_from_output(output))
        return cls(payload=output, run_id=str(actual_run_id) if actual_run_id is not None else None)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def report_status_from_output(output: Any) -> str | None:
    if isinstance(output, Mapping):
        for key in ("report", "report_metadata"):
            report = output.get(key)
            if not isinstance(report, Mapping):
                continue
            status = WorkerReportPayload(source_key=key, payload=dict(report)).status
            if status is not None:
                return status
        if "blocked_report" in output:
            return WorkerReportPayload.from_mapping({"blocked_report": output.get("blocked_report")}).status
    return None


def summary_from_output(output: Mapping[str, Any]) -> dict[str, Any]:
    nested_output = output.get("output")
    if isinstance(nested_output, Mapping):
        summary = nested_output.get("summary")
        if isinstance(summary, Mapping):
            return dict(summary)
        if isinstance(summary, str):
            return {"text": summary}
        nested_summary = report_summary_from_mapping(nested_output)
        if nested_summary:
            return nested_summary
    return report_summary_from_mapping(output)


def report_summary_from_mapping(output: Mapping[str, Any]) -> dict[str, Any]:
    report_summary = WorkerReportPayload.from_mapping(output).summary
    if report_summary:
        return report_summary
    return summary_fields(output)


def summary_fields(output: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: output[key]
        for key in ("title", "status", "report_status")
        if key in output
    }
