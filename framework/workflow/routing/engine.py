from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from typing import Any

from framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepStatus, WorkflowSpec
from framework.workflow.buffer import DataBuffer
from framework.workflow.runtime.result import StepOutcome


class ConditionalExpressionError(ValueError):
    """Raised when a conditional routing expression is invalid or unsafe."""


@dataclass(frozen=True)
class EdgeEvaluation:
    edge_id: str
    source_step_id: str
    target_step_id: str
    condition: EdgeCondition
    matched: bool
    condition_expr: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_step_id": self.source_step_id,
            "target_step_id": self.target_step_id,
            "condition": self.condition.value,
            "matched": self.matched,
            "condition_expr": self.condition_expr,
        }


@dataclass(frozen=True)
class RoutingDecision:
    target_step_id: str | None
    evaluations: list[EdgeEvaluation]
    target_step_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.target_step_ids and self.target_step_id is not None:
            object.__setattr__(self, "target_step_ids", [self.target_step_id])

    def traversed_edge(self) -> EdgeEvaluation | None:
        for evaluation in self.evaluations:
            if evaluation.matched:
                return evaluation
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_step_id": self.target_step_id,
            "target_step_ids": list(self.target_step_ids),
            "evaluations": [evaluation.to_dict() for evaluation in self.evaluations],
        }


class RoutingEngine:
    def decide(
        self,
        workflow: WorkflowSpec,
        current_step: StepSpec,
        outcome: StepOutcome,
        *,
        buffer: DataBuffer | None = None,
        fan_out: bool = False,
    ) -> RoutingDecision:
        return self._decide(
            workflow,
            current_step,
            outcome,
            buffer=buffer,
            fan_out=fan_out,
        )

    def next_steps(
        self,
        workflow: WorkflowSpec,
        current_step: StepSpec,
        outcome: StepOutcome,
        *,
        buffer: DataBuffer | None = None,
    ) -> list[str]:
        return self._decide(
            workflow,
            current_step,
            outcome,
            buffer=buffer,
            fan_out=True,
        ).target_step_ids

    def _decide(
        self,
        workflow: WorkflowSpec,
        current_step: StepSpec,
        outcome: StepOutcome,
        *,
        buffer: DataBuffer | None,
        fan_out: bool,
    ) -> RoutingDecision:
        if current_step.step_id in workflow.terminal_step_ids:
            return RoutingDecision(target_step_id=None, evaluations=[])

        edges = [
            edge for edge in workflow.edges if edge.source_step_id == current_step.step_id
        ]
        edges.sort(key=lambda edge: (edge.priority, edge.edge_id))

        evaluations: list[EdgeEvaluation] = []
        target_step_ids: list[str] = []
        for edge in edges:
            matched = _edge_matches(edge, outcome=outcome, buffer=buffer)
            evaluation = EdgeEvaluation(
                edge_id=edge.edge_id,
                source_step_id=edge.source_step_id,
                target_step_id=edge.target_step_id,
                condition=edge.condition,
                condition_expr=edge.condition_expr,
                matched=matched,
            )
            evaluations.append(evaluation)
            if matched:
                target_step_ids.append(edge.target_step_id)
                if not fan_out:
                    return RoutingDecision(
                        target_step_id=edge.target_step_id,
                        evaluations=evaluations,
                        target_step_ids=target_step_ids,
                    )
        return RoutingDecision(
            target_step_id=target_step_ids[0] if target_step_ids else None,
            evaluations=evaluations,
            target_step_ids=target_step_ids,
        )

    def next_step(
        self,
        workflow: WorkflowSpec,
        current_step: StepSpec,
        outcome: StepOutcome,
        *,
        buffer: DataBuffer | None = None,
    ) -> str | None:
        return self.decide(
            workflow,
            current_step,
            outcome,
            buffer=buffer,
        ).target_step_id


def _edge_matches(
    edge: EdgeSpec,
    *,
    outcome: StepOutcome,
    buffer: DataBuffer | None,
) -> bool:
    if edge.condition == EdgeCondition.ALWAYS:
        return True
    if edge.condition == EdgeCondition.ON_SUCCESS:
        return outcome.status == StepStatus.SUCCEEDED
    if edge.condition == EdgeCondition.ON_FAILURE:
        return outcome.status == StepStatus.FAILED
    if edge.condition == EdgeCondition.CONDITIONAL:
        return _evaluate_condition(
            edge.condition_expr,
            outcome=outcome,
            buffer=buffer,
        )
    if edge.condition == EdgeCondition.VALIDATION_PASS:
        return _validation_decision(outcome, buffer) == "pass"
    if edge.condition == EdgeCondition.VALIDATION_RETRY_REQUIRED:
        return _validation_decision(outcome, buffer) in {"retry_required", "rewrite_required"}
    if edge.condition == EdgeCondition.VALIDATION_BLOCKED:
        return _validation_decision(outcome, buffer) == "blocked"
    if edge.condition == EdgeCondition.HUMAN_APPROVED:
        return _human_decision(outcome, buffer) == "approved"
    if edge.condition == EdgeCondition.HUMAN_REJECTED:
        return _human_decision(outcome, buffer) in {"rejected", "needs_changes"}
    if edge.condition == EdgeCondition.BUDGET_EXCEEDED:
        return bool(_lookup(outcome.outputs, "budget_exceeded") or _lookup_buffer(buffer, "budget_exceeded"))
    if edge.condition == EdgeCondition.SOURCE_UNAVAILABLE:
        return bool(
            _lookup(outcome.outputs, "source_unavailable")
            or _lookup_buffer(buffer, "source_unavailable")
        )
    if edge.condition == EdgeCondition.LLM_DECIDE:
        return _llm_route_hint(edge, outcome, buffer)
    return False


def _evaluate_condition(
    expression: str | None,
    *,
    outcome: StepOutcome,
    buffer: DataBuffer | None,
) -> bool:
    if not expression:
        raise ConditionalExpressionError("conditional edge requires condition_expr")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ConditionalExpressionError(f"invalid conditional expression: {expression}") from exc
    context = {
        "outcome": {
            "status": outcome.status.value,
            "outputs": outcome.outputs,
            "error_type": outcome.error_type,
            "error_message": outcome.error_message,
        },
        "buffer": buffer.snapshot().to_dict() if buffer is not None else {},
        "true": True,
        "false": False,
        "null": None,
    }
    return bool(_eval_node(tree.body, context))


def _validation_decision(outcome: StepOutcome, buffer: DataBuffer | None) -> str | None:
    for source in (
        outcome.outputs.get("validation_metrics"),
        outcome.outputs.get("validation_result"),
        outcome.outputs.get("quality_gate_metrics"),
        outcome.outputs.get("editor_review"),
        outcome.outputs.get("report_quality_summary"),
        _lookup_buffer(buffer, "validation_metrics"),
        _lookup_buffer(buffer, "validation_result"),
        _lookup_buffer(buffer, "quality_gate_metrics"),
        _lookup_buffer(buffer, "editor_review"),
        _lookup_buffer(buffer, "report_quality_summary"),
    ):
        decision = _lookup(source, "decision")
        if decision is not None:
            return str(decision)
        if _lookup(source, "blocked") is True:
            return "blocked"
        rewrite_attempted = _lookup(source, "rewrite_attempted")
        rewrite_attempts = _lookup(source, "rewrite_attempts")
        if rewrite_attempted is True or (isinstance(rewrite_attempts, int) and rewrite_attempts > 0):
            return "rewrite_required"
        retry_required = _lookup(source, "retry_required")
        retry_attempts = _lookup(source, "retry_attempts")
        if retry_required is True or (isinstance(retry_attempts, int) and retry_attempts > 0):
            return "retry_required"
        passed = _lookup(source, "passed")
        if passed is True:
            return "pass"
    if outcome.next_hint in {"validation_pass", "validation_retry_required", "validation_blocked"}:
        return outcome.next_hint.removeprefix("validation_")
    legacy_quality_prefix = "qual" + "ity_"
    if outcome.next_hint in {
        f"{legacy_quality_prefix}pass",
        f"{legacy_quality_prefix}rewrite_required",
        f"{legacy_quality_prefix}blocked",
    }:
        return outcome.next_hint.removeprefix(legacy_quality_prefix)
    return None


def _human_decision(outcome: StepOutcome, buffer: DataBuffer | None) -> str | None:
    for source in (
        outcome.outputs.get("human_review_decision"),
        outcome.outputs.get("human_decision"),
        _lookup_buffer(buffer, "human_review_decision"),
        _lookup_buffer(buffer, "human_decision"),
    ):
        decision = _lookup(source, "decision")
        if decision is not None:
            return str(decision)
        status = _lookup(source, "status")
        if status is not None:
            return str(status)
    if outcome.next_hint in {"human_approved", "human_rejected"}:
        return outcome.next_hint.removeprefix("human_")
    if outcome.next_hint == "human_needs_changes":
        return "needs_changes"
    return None


def _llm_route_hint(edge: EdgeSpec, outcome: StepOutcome, buffer: DataBuffer | None) -> bool:
    allowed_hint = edge.metadata.get("route_hint")
    if allowed_hint is None:
        allowed_hint = edge.target_step_id
    hints = [
        outcome.next_hint,
        _lookup(outcome.outputs, "next_step_id"),
        _lookup(outcome.outputs, "route"),
        _lookup_buffer(buffer, "next_step_id"),
        _lookup_buffer(buffer, "route"),
    ]
    return any(hint is not None and str(hint) == str(allowed_hint) for hint in hints)


def _lookup_buffer(buffer: DataBuffer | None, key: str) -> Any:
    if buffer is None or not buffer.exists(key):
        return None
    return buffer.read(key)


def _lookup(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, key):
        return getattr(value, key)
    return None


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        try:
            return context[node.id]
        except KeyError as exc:
            raise ConditionalExpressionError(f"unknown name in condition: {node.id}") from exc
    if isinstance(node, ast.Attribute):
        return _resolve_attr(_eval_node(node.value, context), node.attr)
    if isinstance(node, ast.Subscript):
        return _resolve_item(_eval_node(node.value, context), _eval_slice(node.slice, context))
    if isinstance(node, ast.BoolOp):
        return _eval_bool_op(node, context)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_eval_node(node.operand, context))
    if isinstance(node, ast.Compare):
        return _eval_compare(node, context)
    raise ConditionalExpressionError(f"unsupported conditional expression node: {type(node).__name__}")


def _eval_slice(node: ast.AST, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    return _eval_node(node, context)


def _eval_bool_op(node: ast.BoolOp, context: dict[str, Any]) -> bool:
    if isinstance(node.op, ast.And):
        for value in node.values:
            if not bool(_eval_node(value, context)):
                return False
        return True
    if isinstance(node.op, ast.Or):
        for value in node.values:
            if bool(_eval_node(value, context)):
                return True
        return False
    raise ConditionalExpressionError(f"unsupported boolean operator: {type(node.op).__name__}")


def _eval_compare(node: ast.Compare, context: dict[str, Any]) -> bool:
    operators = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Is: operator.is_,
        ast.IsNot: operator.is_not,
    }
    left = _eval_node(node.left, context)
    for op, comparator in zip(node.ops, node.comparators, strict=True):
        right = _eval_node(comparator, context)
        op_fn = operators.get(type(op))
        if op_fn is None:
            raise ConditionalExpressionError(f"unsupported comparison operator: {type(op).__name__}")
        if not op_fn(left, right):
            return False
        left = right
    return True


def _resolve_attr(value: Any, attr: str) -> Any:
    if attr.startswith("_"):
        raise ConditionalExpressionError(f"attribute is not allowed: {attr}")
    if isinstance(value, dict):
        try:
            return value[attr]
        except KeyError as exc:
            raise ConditionalExpressionError(f"missing condition attribute: {attr}") from exc
    raise ConditionalExpressionError(f"attribute access is not allowed on {type(value).__name__}")


def _resolve_item(value: Any, key: Any) -> Any:
    if not isinstance(value, dict):
        raise ConditionalExpressionError(f"subscript access is not allowed on {type(value).__name__}")
    try:
        return value[key]
    except KeyError as exc:
        raise ConditionalExpressionError(f"missing condition key: {key}") from exc



