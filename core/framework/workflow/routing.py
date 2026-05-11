from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from typing import Any

from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepStatus, WorkflowSpec
from core.framework.workflow.buffer import DataBuffer
from core.framework.workflow.result import StepOutcome


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

    def traversed_edge(self) -> EdgeEvaluation | None:
        for evaluation in self.evaluations:
            if evaluation.matched:
                return evaluation
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_step_id": self.target_step_id,
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
    ) -> RoutingDecision:
        if current_step.step_id in workflow.terminal_step_ids:
            return RoutingDecision(target_step_id=None, evaluations=[])

        edges = [
            edge for edge in workflow.edges if edge.source_step_id == current_step.step_id
        ]
        edges.sort(key=lambda edge: (edge.priority, edge.edge_id))

        evaluations: list[EdgeEvaluation] = []
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
                return RoutingDecision(
                    target_step_id=edge.target_step_id,
                    evaluations=evaluations,
                )
        return RoutingDecision(target_step_id=None, evaluations=evaluations)

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
