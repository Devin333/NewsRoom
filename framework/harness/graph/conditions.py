from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.canonical import freeze_json, required_text, thaw_json
from framework.harness.graph.versioning import HARNESS_CONDITION_POLICY_VERSION


ALLOWED_CONDITION_PATH_PREFIXES = (
    "state.inputs.",
    "state.outputs.",
    "state.step_status.",
    "worker_result.status",
    "quality_verdict.passed",
    "quality_verdict.score",
    "graph.inputs.",
    "graph.outputs.",
    "node.outputs.",
    "node.outcome",
    "gate_results.",
    "run.lifecycle",
    "run.outcome",
)


class ConditionOperator(StrEnum):
    EXISTS = "exists"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"


@dataclass(frozen=True, slots=True)
class ConditionPredicate:
    path: str
    operator: ConditionOperator | str
    expected: Any
    policy_version: str = HARNESS_CONDITION_POLICY_VERSION

    def __post_init__(self) -> None:
        path = _condition_path(self.path)
        operator = ConditionOperator(self.operator)
        expected = freeze_json(self.expected, "condition.expected")
        if operator == ConditionOperator.EXISTS and not isinstance(expected, bool):
            raise HarnessValidationError(
                "exists condition expected value must be boolean",
                code="invalid_condition_operand",
                details={"operator": operator.value},
            )
        if operator in {ConditionOperator.IN, ConditionOperator.NOT_IN}:
            if not isinstance(expected, tuple):
                raise HarnessValidationError(
                    "in condition expected value must be an array",
                    code="invalid_condition_operand",
                    details={"operator": operator.value},
                )
        if operator in {
            ConditionOperator.GTE,
            ConditionOperator.GT,
            ConditionOperator.LTE,
            ConditionOperator.LT,
        } and not _is_finite_number(expected):
            raise HarnessValidationError(
                "ordered comparison expected value must be a finite number",
                code="invalid_condition_operand",
                details={"operator": operator.value},
            )
        policy_version = required_text(self.policy_version, "condition.policy_version")
        if policy_version != HARNESS_CONDITION_POLICY_VERSION:
            raise HarnessValidationError(
                "unsupported condition policy version",
                code="unsupported_condition_policy",
                details={"policy_version": policy_version},
            )
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "policy_version", policy_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "predicate",
            "path": self.path,
            "operator": self.operator.value,
            "expected": thaw_json(self.expected),
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, slots=True)
class ConditionAll:
    conditions: tuple["HarnessCondition", ...]
    policy_version: str = HARNESS_CONDITION_POLICY_VERSION

    def __post_init__(self) -> None:
        conditions = _condition_tuple(self.conditions, "all")
        policy_version = _validate_policy_version(self.policy_version)
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "policy_version", policy_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "all",
            "conditions": [condition.to_dict() for condition in self.conditions],
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True, slots=True)
class ConditionAny:
    conditions: tuple["HarnessCondition", ...]
    policy_version: str = HARNESS_CONDITION_POLICY_VERSION

    def __post_init__(self) -> None:
        conditions = _condition_tuple(self.conditions, "any")
        policy_version = _validate_policy_version(self.policy_version)
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "policy_version", policy_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "any",
            "conditions": [condition.to_dict() for condition in self.conditions],
            "policy_version": self.policy_version,
        }


HarnessCondition: TypeAlias = ConditionPredicate | ConditionAll | ConditionAny


def condition_from_dict(value: Mapping[str, Any]) -> HarnessCondition:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "condition must be an object",
            code="invalid_condition_contract",
        )
    kind = value.get("kind")
    if kind == "predicate":
        _require_exact_keys(
            value,
            required={"kind", "path", "operator", "expected", "policy_version"},
            field_name="condition predicate",
        )
        return ConditionPredicate(
            path=value["path"],
            operator=value["operator"],
            expected=value["expected"],
            policy_version=value["policy_version"],
        )
    if kind in {"all", "any"}:
        _require_exact_keys(
            value,
            required={"kind", "conditions", "policy_version"},
            field_name=f"condition {kind}",
        )
        raw_conditions = value["conditions"]
        if not isinstance(raw_conditions, Sequence) or isinstance(
            raw_conditions, (str, bytes, bytearray)
        ):
            raise HarnessValidationError(
                "condition children must be an array",
                code="invalid_condition_contract",
            )
        conditions = tuple(condition_from_dict(item) for item in raw_conditions)
        if kind == "all":
            return ConditionAll(conditions=conditions, policy_version=value["policy_version"])
        return ConditionAny(conditions=conditions, policy_version=value["policy_version"])
    raise HarnessValidationError(
        "unsupported condition contract kind",
        code="unsupported_condition_kind",
        details={"kind": str(kind)},
    )


def condition_from_legacy_dict(value: Mapping[str, Any]) -> HarnessCondition:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "legacy condition must be an object",
            code="invalid_condition_contract",
        )
    keys = set(value)
    if "all" in value or "any" in value:
        if keys not in ({"all"}, {"any"}):
            raise HarnessValidationError(
                "legacy boolean condition cannot mix all/any with other fields",
                code="ambiguous_condition_contract",
            )
        combinator = "all" if "all" in value else "any"
        raw_children = value[combinator]
        if not isinstance(raw_children, Sequence) or isinstance(
            raw_children, (str, bytes, bytearray)
        ):
            raise HarnessValidationError(
                f"legacy {combinator} condition must be an array",
                code="invalid_condition_contract",
            )
        children = tuple(condition_from_legacy_dict(child) for child in raw_children)
        return ConditionAll(children) if combinator == "all" else ConditionAny(children)

    path_keys = keys.intersection({"path", "field"})
    if len(path_keys) != 1:
        raise HarnessValidationError(
            "legacy condition requires exactly one path or field",
            code="invalid_condition_path",
        )
    path_key = next(iter(path_keys))
    operator_keys = keys.intersection({operator.value for operator in ConditionOperator})
    unknown = keys.difference(path_keys).difference(operator_keys)
    if unknown:
        raise HarnessValidationError(
            "legacy condition contains unsupported fields",
            code="unsupported_condition_field",
            details={"fields": sorted(str(item) for item in unknown)},
        )
    if not operator_keys:
        raise HarnessValidationError(
            "legacy condition requires an explicit operator",
            code="missing_condition_operator",
        )
    predicates = tuple(
        ConditionPredicate(path=value[path_key], operator=operator, expected=value[operator])
        for operator in sorted(operator_keys)
    )
    return predicates[0] if len(predicates) == 1 else ConditionAll(predicates)


def evaluate_condition(condition: HarnessCondition, context: Mapping[str, Any]) -> bool:
    if isinstance(condition, ConditionAll):
        return all(evaluate_condition(child, context) for child in condition.conditions)
    if isinstance(condition, ConditionAny):
        return any(evaluate_condition(child, context) for child in condition.conditions)
    if not isinstance(condition, ConditionPredicate):
        raise TypeError("condition must be a HarnessCondition")
    actual = resolve_condition_path(condition.path, context)
    expected = thaw_json(condition.expected)
    operator = condition.operator
    if operator == ConditionOperator.EXISTS:
        return (actual is not None) is expected
    if operator == ConditionOperator.EQUALS:
        return actual == expected
    if operator == ConditionOperator.NOT_EQUALS:
        return actual != expected
    if operator == ConditionOperator.IN:
        return actual in expected
    if operator == ConditionOperator.NOT_IN:
        return actual not in expected
    if not _is_finite_number(actual):
        return False
    if operator == ConditionOperator.GTE:
        return bool(actual >= expected)
    if operator == ConditionOperator.GT:
        return bool(actual > expected)
    if operator == ConditionOperator.LTE:
        return bool(actual <= expected)
    if operator == ConditionOperator.LT:
        return bool(actual < expected)
    raise AssertionError(f"unhandled condition operator: {operator}")


def resolve_condition_path(path: str, context: Mapping[str, Any]) -> Any:
    normalized = _condition_path(path)
    if normalized in context:
        return context[normalized]
    current: Any = context
    for segment in normalized.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


def _condition_path(value: Any) -> str:
    path = required_text(value, "condition.path")
    if path.startswith(".") or path.endswith(".") or ".." in path:
        raise HarnessValidationError(
            "condition path contains an empty segment",
            code="invalid_condition_path",
            details={"path": path},
        )
    if not any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_CONDITION_PATH_PREFIXES):
        raise HarnessValidationError(
            "condition path is outside the structural Harness allowlist",
            code="forbidden_condition_path",
            details={"path": path},
        )
    return path


def _condition_tuple(
    values: tuple[HarnessCondition, ...],
    combinator: str,
) -> tuple[HarnessCondition, ...]:
    conditions = tuple(values)
    if not conditions:
        raise HarnessValidationError(
            f"{combinator} condition must contain at least one child",
            code="empty_condition_group",
        )
    if not all(isinstance(item, ConditionPredicate | ConditionAll | ConditionAny) for item in conditions):
        raise HarnessValidationError(
            f"{combinator} condition contains an unsupported child",
            code="invalid_condition_contract",
        )
    return conditions


def _validate_policy_version(value: Any) -> str:
    version = required_text(value, "condition.policy_version")
    if version != HARNESS_CONDITION_POLICY_VERSION:
        raise HarnessValidationError(
            "unsupported condition policy version",
            code="unsupported_condition_policy",
            details={"policy_version": version},
        )
    return version


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    field_name: str,
) -> None:
    keys = set(value)
    if keys != required:
        raise HarnessValidationError(
            f"{field_name} fields do not match its schema",
            code="invalid_condition_contract",
            details={
                "missing": sorted(required.difference(keys)),
                "unknown": sorted(str(item) for item in keys.difference(required)),
            },
        )


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return not isinstance(value, float) or math.isfinite(value)


__all__ = [
    "ALLOWED_CONDITION_PATH_PREFIXES",
    "ConditionAll",
    "ConditionAny",
    "ConditionOperator",
    "ConditionPredicate",
    "HarnessCondition",
    "condition_from_dict",
    "condition_from_legacy_dict",
    "evaluate_condition",
    "resolve_condition_path",
]
