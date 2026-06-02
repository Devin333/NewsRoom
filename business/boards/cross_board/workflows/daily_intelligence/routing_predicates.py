from __future__ import annotations

from framework.workflow.routing import RoutingPredicateContext, RoutingPredicateRegistry
from framework.workflow.routing.predicates import lookup, lookup_buffer


def build_daily_intelligence_routing_predicate_registry() -> RoutingPredicateRegistry:
    registry = RoutingPredicateRegistry()
    registry.register("validation_pass", validation_pass)
    registry.register("validation_retry_required", validation_retry_required)
    registry.register("validation_blocked", validation_blocked)
    registry.register("source_unavailable", source_unavailable)
    return registry


def validation_pass(context: RoutingPredicateContext) -> bool:
    return _validation_decision(context) == "pass"


def validation_retry_required(context: RoutingPredicateContext) -> bool:
    return _validation_decision(context) in {"retry_required", "rewrite_required"}


def validation_blocked(context: RoutingPredicateContext) -> bool:
    return _validation_decision(context) == "blocked"


def source_unavailable(context: RoutingPredicateContext) -> bool:
    return bool(
        lookup(context.outcome.outputs, "source_unavailable")
        or lookup_buffer(context.buffer, "source_unavailable")
    )


def _validation_decision(context: RoutingPredicateContext) -> str | None:
    decisions = [
        decision
        for source in _validation_sources(context)
        if (decision := _validation_decision_from_source(source)) is not None
    ]
    if "blocked" in decisions:
        return "blocked"
    if any(decision in {"retry_required", "rewrite_required"} for decision in decisions):
        return "retry_required"
    if "pass" in decisions:
        return "pass"
    if decisions:
        return decisions[0]
    if context.outcome.next_hint in {"validation_pass", "validation_retry_required", "validation_blocked"}:
        return context.outcome.next_hint.removeprefix("validation_")
    legacy_quality_prefix = "qual" + "ity_"
    if context.outcome.next_hint in {
        f"{legacy_quality_prefix}pass",
        f"{legacy_quality_prefix}rewrite_required",
        f"{legacy_quality_prefix}blocked",
    }:
        return context.outcome.next_hint.removeprefix(legacy_quality_prefix)
    return None


def _validation_sources(context: RoutingPredicateContext) -> tuple[object, ...]:
    return (
        context.outcome.outputs.get("agent_feedback_route"),
        context.outcome.outputs.get("validation_metrics"),
        context.outcome.outputs.get("validation_result"),
        context.outcome.outputs.get("quality_gate_metrics"),
        context.outcome.outputs.get("verification_result"),
        context.outcome.outputs.get("citation_check_result"),
        context.outcome.outputs.get("editor_review"),
        context.outcome.outputs.get("report_quality_summary"),
        lookup_buffer(context.buffer, "agent_feedback_route"),
        lookup_buffer(context.buffer, "validation_metrics"),
        lookup_buffer(context.buffer, "validation_result"),
        lookup_buffer(context.buffer, "quality_gate_metrics"),
        lookup_buffer(context.buffer, "verification_result"),
        lookup_buffer(context.buffer, "citation_check_result"),
        lookup_buffer(context.buffer, "editor_review"),
        lookup_buffer(context.buffer, "report_quality_summary"),
    )


def _validation_decision_from_source(source: object) -> str | None:
    decision = _normalized_decision(lookup(source, "decision"))
    if decision is not None:
        return decision
    status = _normalized_decision(lookup(source, "status"))
    if status is not None:
        return status
    if lookup(source, "blocked") is True:
        return "blocked"
    if _has_validation_failures(source):
        return "retry_required"
    rewrite_attempted = lookup(source, "rewrite_attempted")
    rewrite_attempts = lookup(source, "rewrite_attempts")
    if rewrite_attempted is True or (isinstance(rewrite_attempts, int) and rewrite_attempts > 0):
        return "rewrite_required"
    retry_required = lookup(source, "retry_required")
    retry_attempts = lookup(source, "retry_attempts")
    if retry_required is True or (isinstance(retry_attempts, int) and retry_attempts > 0):
        return "retry_required"
    passed = lookup(source, "passed")
    if passed is True:
        return "pass"
    return None


def _normalized_decision(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"pass", "passed", "ok", "accepted"}:
        return "pass"
    if normalized in {"retry_required", "rewrite_required", "needs_rewrite"}:
        return "retry_required"
    if normalized in {"blocked", "block"}:
        return "blocked"
    return normalized or None


def _has_validation_failures(source: object) -> bool:
    if source is None:
        return False
    if lookup(source, "passed") is False:
        return True
    for key in (
        "missing_citations",
        "missing_section_sources",
        "unknown_urls",
        "unsupported_urls",
        "unsupported_claims",
        "unsupported_sections",
        "policy_violations",
    ):
        value = lookup(source, key)
        if isinstance(value, list) and value:
            return True
    return False
