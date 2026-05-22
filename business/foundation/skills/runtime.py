from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from framework.skills.core.context import SkillRunContext
from framework.skills.core.result import SkillFailureReason

from business.foundation.skills.fallbacks import (
    fallback_entity_extraction,
    fallback_event_deduplication,
    fallback_evidence_checking,
    fallback_report_writing,
    fallback_source_reliability,
    fallback_trend_analysis,
)


@dataclass(frozen=True)
class BusinessSkillResult:
    skill_name: str
    output: dict[str, Any]
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    used_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "output": self.output,
            "status": self.status,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "trace": dict(self.trace),
            "used_fallback": self.used_fallback,
        }


class BusinessSkillRuntime:
    def __init__(self, skill_runner: Any | None = None) -> None:
        self.skill_runner = skill_runner

    def run_entity_extraction(
        self,
        item: dict[str, Any],
        *,
        run_id: str | None = None,
        fail_on_skill_error: bool = False,
    ) -> BusinessSkillResult:
        return self._run(
            "entity-extraction",
            {"item": dict(item)},
            lambda: fallback_entity_extraction(dict(item)),
            run_id=run_id,
            fail_on_skill_error=fail_on_skill_error,
        )

    def run_source_reliability(
        self,
        source: dict[str, Any],
        content: dict[str, Any],
        *,
        historical_context: dict[str, Any] | None = None,
        run_id: str | None = None,
        fail_on_skill_error: bool = False,
    ) -> BusinessSkillResult:
        payload = {
            "source": dict(source),
            "content": dict(content),
            "historical_context": dict(historical_context or {}),
        }
        return self._run(
            "source-reliability",
            payload,
            lambda: fallback_source_reliability(dict(source), dict(content)),
            run_id=run_id,
            fail_on_skill_error=fail_on_skill_error,
        )

    def run_event_deduplication(
        self,
        items: list[dict[str, Any]],
        *,
        run_id: str | None = None,
        fail_on_skill_error: bool = False,
    ) -> BusinessSkillResult:
        normalized = [dict(item) for item in items]
        return self._run(
            "event-deduplication",
            {"items": normalized},
            lambda: fallback_event_deduplication(normalized),
            run_id=run_id,
            fail_on_skill_error=fail_on_skill_error,
        )

    def run_evidence_checking(
        self,
        claims: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        *,
        run_id: str | None = None,
        fail_on_skill_error: bool = False,
    ) -> BusinessSkillResult:
        normalized_claims = [dict(item) for item in claims] or [{"claim_id": "empty", "text": "No claims"}]
        normalized_sources = [dict(item) for item in sources] or [{"source_id": "empty", "text": "No sources"}]
        return self._run(
            "evidence-checking",
            {"claims": normalized_claims, "sources": normalized_sources},
            lambda: fallback_evidence_checking(normalized_claims, normalized_sources),
            run_id=run_id,
            fail_on_skill_error=fail_on_skill_error,
        )

    def run_report_writing(
        self,
        report: dict[str, Any],
        items: list[dict[str, Any]],
        *,
        trend_analyses: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
        fail_on_skill_error: bool = False,
    ) -> BusinessSkillResult:
        normalized_items = [dict(item) for item in items] or [
            {
                "item_id": "empty",
                "title": "No items",
                "summary": "No items available.",
                "url": "",
                "source_name": "system",
                "evidence_status": "unclear",
            }
        ]
        trends = [dict(item) for item in trend_analyses or []]
        return self._run(
            "report-writing",
            {"report": dict(report), "items": normalized_items, "trend_analyses": trends},
            lambda: fallback_report_writing(dict(report), normalized_items, trends),
            run_id=run_id,
            fail_on_skill_error=fail_on_skill_error,
        )

    def run_trend_analysis(
        self,
        events: list[dict[str, Any]],
        *,
        run_id: str | None = None,
        fail_on_skill_error: bool = False,
    ) -> BusinessSkillResult:
        normalized = [dict(item) for item in events] or [{"event_id": "empty", "title": "No events"}]
        return self._run(
            "trend-analysis",
            {"events": normalized},
            lambda: fallback_trend_analysis(normalized),
            run_id=run_id,
            fail_on_skill_error=fail_on_skill_error,
        )

    def _run(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        fallback: Callable[[], dict[str, Any]],
        *,
        run_id: str | None,
        fail_on_skill_error: bool,
    ) -> BusinessSkillResult:
        if self.skill_runner is None:
            output = fallback()
            return BusinessSkillResult(
                skill_name=skill_name,
                output=output,
                status="fallback",
                warnings=[f"{skill_name} used deterministic fallback"],
                trace=_fallback_trace(skill_name, run_id),
                used_fallback=True,
            )
        try:
            result = self.skill_runner.run(
                skill_name,
                input_data,
                context=SkillRunContext(run_id=run_id or "business-skill-run", skill_name=skill_name),
            )
        except Exception as exc:
            if fail_on_skill_error:
                raise
            output = fallback()
            return BusinessSkillResult(
                skill_name=skill_name,
                output=output,
                status="fallback",
                warnings=[f"{skill_name} failed and fallback was used: {type(exc).__name__}: {exc}"],
                errors=[{"code": "skill_exception", "message": str(exc), "type": type(exc).__name__}],
                trace=_fallback_trace(skill_name, run_id, exception_type=type(exc).__name__),
                used_fallback=True,
            )
        is_success = result.is_success() if hasattr(result, "is_success") else str(getattr(result, "status", "")) == "success"
        if is_success:
            return BusinessSkillResult(
                skill_name=skill_name,
                output=dict(getattr(result, "output", {}) or {}),
                status=str(getattr(getattr(result, "status", None), "value", getattr(result, "status", "success"))),
                warnings=_warnings(result),
                errors=[],
                trace=_result_trace(result, skill_name, run_id, used_fallback=False),
                used_fallback=False,
            )
        reason = getattr(result, "failure_reason", None)
        reason_value = str(getattr(reason, "value", reason or "unknown"))
        fatal_schema = reason in {
            SkillFailureReason.INPUT_SCHEMA_INVALID,
            SkillFailureReason.OUTPUT_SCHEMA_INVALID,
        } or reason_value in {"input_schema_invalid", "output_schema_invalid"}
        if fail_on_skill_error or fatal_schema:
            raise ValueError(f"{skill_name} failed: {reason_value}")
        output = fallback()
        return BusinessSkillResult(
            skill_name=skill_name,
            output=output,
            status="fallback",
            warnings=[*_warnings(result), f"{skill_name} failed with {reason_value}; fallback used"],
            errors=_errors(result),
            trace=_result_trace(result, skill_name, run_id, used_fallback=True),
            used_fallback=True,
        )


def _warnings(result: Any) -> list[str]:
    warnings = []
    for warning in getattr(result, "warnings", []) or []:
        warnings.append(str(getattr(warning, "message", warning)))
    return warnings


def _errors(result: Any) -> list[dict[str, Any]]:
    errors = []
    for error in getattr(result, "errors", []) or []:
        if hasattr(error, "model_dump"):
            errors.append(error.model_dump(mode="json"))
        else:
            errors.append({"message": str(error)})
    return errors


def _result_trace(result: Any, skill_name: str, run_id: str | None, *, used_fallback: bool) -> dict[str, Any]:
    status = getattr(result, "status", None)
    failure_reason = getattr(result, "failure_reason", None)
    return {
        "skill_name": skill_name,
        "run_id": run_id,
        "status": str(getattr(status, "value", status or "")),
        "failure_reason": str(getattr(failure_reason, "value", failure_reason or "none")),
        "used_fallback": used_fallback,
        "trace": dict(getattr(result, "trace", {}) or {}),
        "cost": getattr(getattr(result, "cost", None), "model_dump", lambda mode="json": {})(),
    }


def _fallback_trace(skill_name: str, run_id: str | None, *, exception_type: str | None = None) -> dict[str, Any]:
    payload = {
        "skill_name": skill_name,
        "run_id": run_id,
        "status": "fallback",
        "failure_reason": "none",
        "used_fallback": True,
    }
    if exception_type:
        payload["exception_type"] = exception_type
    return payload


__all__ = ["BusinessSkillResult", "BusinessSkillRuntime"]
