from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from framework.agent.loop.extensions import OutputValidationResult
from framework.agent.models import AgentAction, AgentSpec, JudgeDecision, JudgeVerdict
from framework.shared.time import format_datetime


@dataclass(frozen=True)
class AgentOutputBudget:
    max_json_bytes: int | None = 1_048_576
    max_depth: int | None = 80
    max_collection_items: int | None = 50_000
    max_string_bytes: int | None = 262_144

    def __post_init__(self) -> None:
        for field_name in (
            "max_json_bytes",
            "max_depth",
            "max_collection_items",
            "max_string_bytes",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            object.__setattr__(self, field_name, max(1, int(value)))

    def to_dict(self) -> dict[str, int | None]:
        return {
            "max_json_bytes": self.max_json_bytes,
            "max_depth": self.max_depth,
            "max_collection_items": self.max_collection_items,
            "max_string_bytes": self.max_string_bytes,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any] | None,
        *,
        default: "AgentOutputBudget | None" = None,
    ) -> "AgentOutputBudget":
        base = default or cls()
        if not isinstance(payload, dict):
            return base
        return cls(
            max_json_bytes=_optional_int(
                payload,
                "max_json_bytes",
                "max_payload_bytes",
                "max_bytes",
                default=base.max_json_bytes,
            ),
            max_depth=_optional_int(payload, "max_depth", default=base.max_depth),
            max_collection_items=_optional_int(
                payload,
                "max_collection_items",
                "max_items",
                default=base.max_collection_items,
            ),
            max_string_bytes=_optional_int(
                payload,
                "max_string_bytes",
                "max_text_bytes",
                default=base.max_string_bytes,
            ),
        )


DEFAULT_AGENT_OUTPUT_BUDGET = AgentOutputBudget()


@dataclass(frozen=True)
class AgentOutputMeasurement:
    json_bytes: int
    max_depth: int
    collection_items: int
    max_string_bytes: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "json_bytes": self.json_bytes,
            "max_depth": self.max_depth,
            "collection_items": self.collection_items,
            "max_string_bytes": self.max_string_bytes,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class AgentOutputBudgetViolation:
    code: str
    message: str
    limit: int
    actual: int
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "limit": self.limit,
            "actual": self.actual,
        }
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class AgentOutputBudgetCheck:
    budget: AgentOutputBudget
    measurement: AgentOutputMeasurement
    violations: tuple[AgentOutputBudgetViolation, ...] = ()

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget.to_dict(),
            "measurement": self.measurement.to_dict(),
            "violations": [violation.to_dict() for violation in self.violations],
        }


class AgentOutputBudgetValidator:
    def __init__(
        self,
        *,
        default_budget: AgentOutputBudget | None = DEFAULT_AGENT_OUTPUT_BUDGET,
    ) -> None:
        self._default_budget = default_budget

    def __call__(
        self,
        *,
        agent: AgentSpec,
        action: AgentAction,
        called_tools: list[str],
        inputs: dict[str, Any],
    ) -> OutputValidationResult:
        _ = called_tools, inputs
        budget = resolve_agent_output_budget(
            agent.validation_policy,
            default=self._default_budget,
        )
        if budget is None:
            return OutputValidationResult()
        check = validate_agent_output_budget(action.output or {}, budget=budget)
        return output_budget_validation_result(check)


def resolve_agent_output_budget(
    validation_policy: dict[str, Any] | None,
    *,
    default: AgentOutputBudget | None = DEFAULT_AGENT_OUTPUT_BUDGET,
) -> AgentOutputBudget | None:
    if not isinstance(validation_policy, dict):
        return default
    raw_budget = validation_policy.get("output_budget")
    if raw_budget is False:
        return None
    if raw_budget is None:
        return default
    if not isinstance(raw_budget, dict):
        return default
    if raw_budget.get("enabled") is False:
        return None
    return AgentOutputBudget.from_dict(raw_budget, default=default)


def measure_agent_output(value: Any) -> AgentOutputMeasurement:
    return _inspect_output(value, budget=None).measurement


def validate_agent_output_budget(
    value: Any,
    *,
    budget: AgentOutputBudget,
) -> AgentOutputBudgetCheck:
    return _inspect_output(value, budget=budget)


def output_budget_validation_result(check: AgentOutputBudgetCheck) -> OutputValidationResult:
    if not check.has_violations:
        return OutputValidationResult()
    return OutputValidationResult(
        policy_violations=[violation.message for violation in check.violations],
        block=True,
        feedback=output_budget_feedback(check),
    )


def output_budget_judge_verdict(check: AgentOutputBudgetCheck) -> JudgeVerdict:
    result = output_budget_validation_result(check)
    return JudgeVerdict(
        decision=JudgeDecision.BLOCK,
        confidence=1.0,
        feedback=result.feedback,
        policy_violations=list(result.policy_violations),
    )


def output_budget_feedback(check: AgentOutputBudgetCheck) -> str:
    if not check.violations:
        return "agent output is within budget"
    return f"agent output exceeds configured budget: {check.violations[0].message}"


def _inspect_output(
    root: Any,
    *,
    budget: AgentOutputBudget | None,
) -> AgentOutputBudgetCheck:
    json_bytes = 0
    max_depth = 0
    collection_items = 0
    max_string_bytes = 0
    truncated = False
    violations: list[AgentOutputBudgetViolation] = []
    seen_violation_codes: set[str] = set()
    stack: list[tuple[Any, int, str]] = [(root, 1, "$")]

    def add_violation(
        *,
        code: str,
        message: str,
        limit: int | None,
        actual: int,
        path: str | None = None,
    ) -> None:
        if limit is None or code in seen_violation_codes:
            return
        seen_violation_codes.add(code)
        violations.append(
            AgentOutputBudgetViolation(
                code=code,
                message=message,
                limit=limit,
                actual=actual,
                path=path,
            )
        )

    while stack:
        value, depth, path = stack.pop()
        max_depth = max(max_depth, depth)

        if budget is not None and budget.max_depth is not None and depth > budget.max_depth:
            add_violation(
                code="agent.output.max_depth",
                message=f"agent output depth exceeded at {path}: {depth} > {budget.max_depth}",
                limit=budget.max_depth,
                actual=depth,
                path=path,
            )
            truncated = True
            continue

        if isinstance(value, dict):
            item_count = len(value)
            collection_items += item_count
            json_bytes += 2 + max(0, item_count - 1)
            skip_children = False
            if (
                budget is not None
                and budget.max_collection_items is not None
                and collection_items > budget.max_collection_items
            ):
                add_violation(
                    code="agent.output.max_collection_items",
                    message=(
                        "agent output collection items exceeded: "
                        f"{collection_items} > {budget.max_collection_items}"
                    ),
                    limit=budget.max_collection_items,
                    actual=collection_items,
                )
                truncated = True
                skip_children = True
            if skip_children:
                continue
            for key, child in value.items():
                key_text = _json_key(key)
                key_bytes = _json_scalar_bytes(key_text)
                raw_key_bytes = len(key_text.encode("utf-8"))
                max_string_bytes = max(max_string_bytes, raw_key_bytes)
                json_bytes += key_bytes + 1
                if (
                    budget is not None
                    and budget.max_string_bytes is not None
                    and raw_key_bytes > budget.max_string_bytes
                ):
                    add_violation(
                        code="agent.output.max_string_bytes",
                        message=(
                            "agent output string bytes exceeded at "
                            f"{_child_path(path, key_text)}: {raw_key_bytes} > {budget.max_string_bytes}"
                        ),
                        limit=budget.max_string_bytes,
                        actual=raw_key_bytes,
                        path=_child_path(path, key_text),
                    )
                if not skip_children:
                    stack.append((child, depth + 1, _child_path(path, key_text)))
        elif isinstance(value, (list, tuple)):
            item_count = len(value)
            collection_items += item_count
            json_bytes += 2 + max(0, item_count - 1)
            if (
                budget is not None
                and budget.max_collection_items is not None
                and collection_items > budget.max_collection_items
            ):
                add_violation(
                    code="agent.output.max_collection_items",
                    message=(
                        "agent output collection items exceeded: "
                        f"{collection_items} > {budget.max_collection_items}"
                    ),
                    limit=budget.max_collection_items,
                    actual=collection_items,
                )
                truncated = True
                continue
            for index in range(item_count - 1, -1, -1):
                stack.append((value[index], depth + 1, f"{path}[{index}]"))
        else:
            if isinstance(value, str):
                raw_string_bytes = len(value.encode("utf-8"))
                max_string_bytes = max(max_string_bytes, raw_string_bytes)
                if (
                    budget is not None
                    and budget.max_string_bytes is not None
                    and raw_string_bytes > budget.max_string_bytes
                ):
                    add_violation(
                        code="agent.output.max_string_bytes",
                        message=(
                            "agent output string bytes exceeded at "
                            f"{path}: {raw_string_bytes} > {budget.max_string_bytes}"
                        ),
                        limit=budget.max_string_bytes,
                        actual=raw_string_bytes,
                        path=path,
                    )
            json_bytes += _json_scalar_bytes(value)

        if (
            budget is not None
            and budget.max_json_bytes is not None
            and json_bytes > budget.max_json_bytes
        ):
            add_violation(
                code="agent.output.max_json_bytes",
                message=f"agent output JSON bytes exceeded: {json_bytes} > {budget.max_json_bytes}",
                limit=budget.max_json_bytes,
                actual=json_bytes,
            )
            truncated = True

    measurement = AgentOutputMeasurement(
        json_bytes=json_bytes,
        max_depth=max_depth,
        collection_items=collection_items,
        max_string_bytes=max_string_bytes,
        truncated=truncated,
    )
    return AgentOutputBudgetCheck(
        budget=budget or DEFAULT_AGENT_OUTPUT_BUDGET,
        measurement=measurement,
        violations=tuple(violations),
    )


def _json_scalar_bytes(value: Any) -> int:
    # Fast-path common types to avoid json.dumps overhead on every leaf node
    if value is None:
        return 4  # "null"
    if value is True:
        return 4  # "true"
    if value is False:
        return 5  # "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return len(str(value))
    if isinstance(value, float):
        return len(repr(value))
    if isinstance(value, str):
        return len(value.encode("utf-8")) + 2  # +2 for surrounding quotes
    try:
        return len(
            json.dumps(
                _json_scalar(value),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        return len(json.dumps(str(value), ensure_ascii=False).encode("utf-8"))


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)


def _json_key(key: Any) -> str:
    scalar = _json_scalar(key)
    return scalar if isinstance(scalar, str) else str(scalar)


def _child_path(path: str, key: str) -> str:
    if key.isidentifier() and len(key) <= 48:
        return f"{path}.{key}"
    preview = key[:48]
    if len(key) > 48:
        preview += "..."
    return f"{path}[{preview!r}]"


def _optional_int(
    payload: dict[str, Any],
    *keys: str,
    default: int | None,
) -> int | None:
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            return None
        return max(1, int(value))
    return default
