from __future__ import annotations

from framework.specs import StepStatus
from framework.workflow.routing.conditions import evaluate_condition
from framework.workflow.routing.predicates import (
    RoutingPredicateContext,
    RoutingPredicateRegistry,
    lookup,
    lookup_buffer,
)


def build_builtin_predicate_registry() -> RoutingPredicateRegistry:
    registry = RoutingPredicateRegistry()
    registry.register("always", always)
    registry.register("on_success", on_success)
    registry.register("on_failure", on_failure)
    registry.register("conditional", conditional)
    registry.register("llm_decide", llm_decide)
    registry.register("budget_exceeded", budget_exceeded)
    registry.register("human_approved", human_approved)
    registry.register("human_rejected", human_rejected)
    return registry


def always(_: RoutingPredicateContext) -> bool:
    return True


def on_success(context: RoutingPredicateContext) -> bool:
    return context.outcome.status == StepStatus.SUCCEEDED


def on_failure(context: RoutingPredicateContext) -> bool:
    return context.outcome.status == StepStatus.FAILED


def conditional(context: RoutingPredicateContext) -> bool:
    return evaluate_condition(
        context.edge.condition_expr,
        outcome=context.outcome,
        buffer=context.buffer,
    )


def budget_exceeded(context: RoutingPredicateContext) -> bool:
    return bool(
        lookup(context.outcome.outputs, "budget_exceeded")
        or lookup_buffer(context.buffer, "budget_exceeded")
    )


def human_approved(context: RoutingPredicateContext) -> bool:
    return _human_decision(context) == "approved"


def human_rejected(context: RoutingPredicateContext) -> bool:
    return _human_decision(context) in {"rejected", "needs_changes"}


def llm_decide(context: RoutingPredicateContext) -> bool:
    allowed_hint = context.edge.metadata.get("route_hint")
    if allowed_hint is None:
        allowed_hint = context.edge.target_step_id
    hints = [
        context.outcome.next_hint,
        lookup(context.outcome.outputs, "next_step_id"),
        lookup(context.outcome.outputs, "route"),
        lookup_buffer(context.buffer, "next_step_id"),
        lookup_buffer(context.buffer, "route"),
    ]
    return any(hint is not None and str(hint) == str(allowed_hint) for hint in hints)


def _human_decision(context: RoutingPredicateContext) -> str | None:
    decision_keys = list(context.edge.metadata.get("decision_keys") or [])
    if not decision_keys:
        decision_keys = ["human_review_decision", "human_decision"]
    for key in decision_keys:
        for source in (
            context.outcome.outputs.get(str(key)),
            lookup_buffer(context.buffer, str(key)),
        ):
            decision = lookup(source, "decision")
            if decision is not None:
                return str(decision)
            status = lookup(source, "status")
            if status is not None:
                return str(status)
    if context.outcome.next_hint in {"human_approved", "human_rejected"}:
        return context.outcome.next_hint.removeprefix("human_")
    if context.outcome.next_hint == "human_needs_changes":
        return "needs_changes"
    return None
