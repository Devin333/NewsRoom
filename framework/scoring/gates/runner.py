from __future__ import annotations

from typing import Any

from framework.scoring.core.context import ScoringContext
from framework.scoring.core.target import ScoringTarget
from framework.scoring.features import FeatureVector
from framework.scoring.gates.models import GateAction, GateResult, GateSpec


class GateRunner:
    def run(
        self,
        gates: list[GateSpec],
        *,
        target: ScoringTarget,
        features: FeatureVector,
        context: ScoringContext,
    ) -> list[GateResult]:
        return [self._run_one(gate, target=target, features=features, context=context) for gate in gates]

    def _run_one(
        self,
        gate: GateSpec,
        *,
        target: ScoringTarget,
        features: FeatureVector,
        context: ScoringContext,
    ) -> GateResult:
        passed = self._evaluate(gate, features)
        active = passed if gate.action == GateAction.BOOST else not passed
        observed = self._observed(gate, features)
        return GateResult(
            gate_id=gate.gate_id,
            action=gate.action,
            passed=passed,
            blocked=active and gate.action == GateAction.BLOCK,
            review_required=active and gate.action == GateAction.REVIEW,
            score_cap=gate.score_cap if active and gate.action == GateAction.CAP else None,
            penalty=gate.penalty if active and gate.action == GateAction.PENALTY else 0.0,
            boost=gate.boost if active and gate.action == GateAction.BOOST else 0.0,
            reason=gate.reason or _default_reason(gate, passed),
            observed=observed,
            metadata={
                "target_id": target.target_id,
                "target_type": target.target_type,
                "severity": gate.severity,
                "context": {"run_id": context.run_id, "recipe_id": context.recipe_id},
            },
        )

    def _evaluate(self, gate: GateSpec, features: FeatureVector) -> bool:
        if gate.operator == "missing":
            return gate.feature not in features.values
        if gate.operator == "exists":
            return gate.feature is not None and gate.feature in features.values
        value = features.get(gate.feature or "", default=float("nan")) if gate.feature else None
        return self._compare(value, gate.operator, gate.threshold)

    def _compare(
        self,
        value: float | None,
        operator: str,
        threshold: float | tuple[float, float] | None,
    ) -> bool:
        if value is None or threshold is None:
            return False
        numeric = float(value)
        if operator == "eq":
            return numeric == float(threshold)
        if operator == "neq":
            return numeric != float(threshold)
        if operator == "lt":
            return numeric < float(threshold)
        if operator == "lte":
            return numeric <= float(threshold)
        if operator == "gt":
            return numeric > float(threshold)
        if operator == "gte":
            return numeric >= float(threshold)
        if operator == "between":
            if not isinstance(threshold, tuple):
                return False
            lower, upper = threshold
            return float(lower) <= numeric <= float(upper)
        raise ValueError(f"unsupported gate operator: {operator}")

    def _observed(self, gate: GateSpec, features: FeatureVector) -> dict[str, Any]:
        value = features.values.get(gate.feature or "")
        return {
            "feature": gate.feature,
            "operator": gate.operator,
            "threshold": gate.threshold,
            "value": value.value if value is not None else None,
            "missing_features": list(features.missing_features),
        }


def _default_reason(gate: GateSpec, passed: bool) -> str:
    state = "passed" if passed else "failed"
    return f"{gate.gate_id} {state}"
