from __future__ import annotations

from business.evaluation.models import clamp_metric


def quality_pass_rate(quality_summary: object | None) -> float:
    if quality_summary is None:
        return 0.0
    checks = list(getattr(quality_summary, "checks", []) or [])
    if not checks:
        score = getattr(quality_summary, "score", None)
        return clamp_metric(score or 0.0)
    passed = sum(1 for check in checks if getattr(check, "passed", False))
    return clamp_metric(passed / len(checks))


def feedback_resolution_signal(feedback_events: list[object]) -> float:
    if not feedback_events:
        return 1.0
    severe = [
        event
        for event in feedback_events
        if str(getattr(event, "severity", "")).casefold() in {"error", "block", "critical"}
    ]
    return clamp_metric(1.0 - (len(severe) / len(feedback_events)))


def quality_metrics(quality_summary: object | None, feedback_events: list[object] | None = None) -> dict[str, float]:
    return {
        "quality_pass_rate": quality_pass_rate(quality_summary),
        "feedback_health": feedback_resolution_signal(list(feedback_events or [])),
    }
