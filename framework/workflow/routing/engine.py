from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from framework.workflow.buffer import DataBuffer
from framework.workflow.routing.builtin_predicates import build_builtin_predicate_registry
from framework.workflow.routing.conditions import ConditionalExpressionError, evaluate_condition
from framework.workflow.routing.predicates import RoutingPredicateContext, RoutingPredicateRegistry
from framework.workflow.runtime.result import StepOutcome


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
    def __init__(self, predicate_registry: RoutingPredicateRegistry | None = None) -> None:
        self.predicate_registry = build_builtin_predicate_registry().merge(predicate_registry)

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
            matched = self._edge_matches(edge, outcome=outcome, buffer=buffer)
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
        self,
        edge: EdgeSpec,
        *,
        outcome: StepOutcome,
        buffer: DataBuffer | None,
    ) -> bool:
        predicate = self.predicate_registry.get(edge.condition.value)
        if predicate is None:
            return False
        return predicate(RoutingPredicateContext(edge=edge, outcome=outcome, buffer=buffer))


def _edge_matches(
    edge: EdgeSpec,
    *,
    outcome: StepOutcome,
    buffer: DataBuffer | None,
) -> bool:
    return RoutingEngine()._edge_matches(edge, outcome=outcome, buffer=buffer)


def _evaluate_condition(
    expression: str | None,
    *,
    outcome: StepOutcome,
    buffer: DataBuffer | None,
) -> bool:
    return evaluate_condition(expression, outcome=outcome, buffer=buffer)


__all__ = [
    "ConditionalExpressionError",
    "EdgeEvaluation",
    "RoutingDecision",
    "RoutingEngine",
]
