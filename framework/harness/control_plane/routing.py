from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.state import HarnessState
from framework.harness.quality.verdict import HarnessQualityVerdict
from framework.harness.workflow.spec import HarnessRouteKind, HarnessRoutingRule, HarnessWorkflowSpec
from framework.harness.workers.result import HarnessWorkerResult


ALLOWED_ROUTING_PATH_PREFIXES = (
    "state.inputs.",
    "state.outputs.",
    "state.step_status.",
    "worker_result.status",
    "quality_verdict.passed",
    "quality_verdict.score",
)


@dataclass(frozen=True)
class RoutingContext:
    state: HarnessState
    worker_result: HarnessWorkerResult | None = None
    quality_verdict: HarnessQualityVerdict | None = None

    @property
    def outputs(self) -> dict[str, Any]:
        outputs = self.state.metadata.get("outputs", {})
        if isinstance(outputs, dict):
            return outputs
        return {}

    @property
    def step_status(self) -> dict[str, str]:
        return {step.step_id: step.status.value for step in self.state.step_states}


class HarnessRoutingEvaluator:
    def select_next_step(
        self,
        workflow: HarnessWorkflowSpec,
        state: HarnessState,
        from_step_id: str,
        *,
        worker_result: HarnessWorkerResult | None = None,
        quality_verdict: HarnessQualityVerdict | None = None,
    ) -> str | None:
        context = RoutingContext(state=state, worker_result=worker_result, quality_verdict=quality_verdict)
        for rule in workflow.routing_rules:
            if rule.from_step != from_step_id:
                continue
            if self.rule_matches(rule, context):
                return rule.to_step
        return self.default_next_step(workflow, from_step_id)

    def default_next_step(self, workflow: HarnessWorkflowSpec, from_step_id: str) -> str | None:
        step_ids = workflow.step_ids
        try:
            index = step_ids.index(from_step_id)
        except ValueError as exc:
            raise HarnessValidationError("from_step_id must reference a workflow step") from exc
        next_index = index + 1
        if next_index >= len(step_ids):
            return None
        return step_ids[next_index]

    def rule_matches(self, rule: HarnessRoutingRule, context: RoutingContext) -> bool:
        if rule.kind == HarnessRouteKind.ALWAYS and not rule.condition:
            return True
        if rule.kind == HarnessRouteKind.ON_STATUS:
            expected = rule.condition.get("status", rule.condition.get("equals"))
            return expected is not None and self._resolve_path("worker_result.status", context) == expected
        if rule.kind == HarnessRouteKind.ON_VERDICT:
            if "passed" in rule.condition and self._resolve_path("quality_verdict.passed", context) != rule.condition["passed"]:
                return False
            if "min_score" in rule.condition:
                score = self._resolve_path("quality_verdict.score", context)
                if not isinstance(score, int | float) or score < rule.condition["min_score"]:
                    return False
            if "max_score" in rule.condition:
                score = self._resolve_path("quality_verdict.score", context)
                if not isinstance(score, int | float) or score > rule.condition["max_score"]:
                    return False
            return True
        return self._condition_matches(rule.condition, context)

    def _condition_matches(self, condition: dict[str, Any], context: RoutingContext) -> bool:
        if not condition:
            return True
        if "all" in condition:
            clauses = condition["all"]
            if not isinstance(clauses, list):
                raise HarnessValidationError("routing all condition must be a list")
            return all(self._condition_matches(dict(clause), context) for clause in clauses)
        if "any" in condition:
            clauses = condition["any"]
            if not isinstance(clauses, list):
                raise HarnessValidationError("routing any condition must be a list")
            return any(self._condition_matches(dict(clause), context) for clause in clauses)

        path = condition.get("path", condition.get("field"))
        if not isinstance(path, str) or not path.strip():
            raise HarnessValidationError("routing condition requires a structural path")
        value = self._resolve_path(path, context)
        if "exists" in condition:
            return (value is not None) is bool(condition["exists"])
        if "equals" in condition:
            return value == condition["equals"]
        if "not_equals" in condition:
            return value != condition["not_equals"]
        if "in" in condition:
            return value in condition["in"]
        if "not_in" in condition:
            return value not in condition["not_in"]
        if "gte" in condition and not self._compare(value, condition["gte"], lambda left, right: left >= right):
            return False
        if "gt" in condition and not self._compare(value, condition["gt"], lambda left, right: left > right):
            return False
        if "lte" in condition and not self._compare(value, condition["lte"], lambda left, right: left <= right):
            return False
        if "lt" in condition and not self._compare(value, condition["lt"], lambda left, right: left < right):
            return False
        return True

    def _resolve_path(self, path: str, context: RoutingContext) -> Any:
        if not self._is_allowed_path(path):
            raise HarnessValidationError("routing condition can only read structural Harness fields", details={"path": path})
        if path.startswith("state.inputs."):
            return _get_nested(context.state.run_spec.inputs, path.removeprefix("state.inputs."))
        if path.startswith("state.outputs."):
            return _get_nested(context.outputs, path.removeprefix("state.outputs."))
        if path.startswith("state.step_status."):
            return context.step_status.get(path.removeprefix("state.step_status."))
        if path == "worker_result.status":
            return context.worker_result.status.value if context.worker_result is not None else None
        if path == "quality_verdict.passed":
            return context.quality_verdict.passed if context.quality_verdict is not None else None
        if path == "quality_verdict.score":
            return context.quality_verdict.score if context.quality_verdict is not None else None
        raise HarnessValidationError("unsupported routing path", details={"path": path})

    def _is_allowed_path(self, path: str) -> bool:
        return any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_ROUTING_PATH_PREFIXES)

    def _compare(self, value: Any, expected: Any, predicate: Any) -> bool:
        if not isinstance(value, int | float) or not isinstance(expected, int | float):
            return False
        return bool(predicate(value, expected))


def _get_nested(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for segment in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


__all__ = ["ALLOWED_ROUTING_PATH_PREFIXES", "HarnessRoutingEvaluator", "RoutingContext"]
