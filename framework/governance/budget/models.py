from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from enum import Enum
from hashlib import sha256
from typing import Any, ClassVar, Mapping

from framework.governance.budget.errors import BudgetContractError
from framework.shared.json import stable_json_dumps
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity


BUDGET_SCHEMA_VERSION = "newsroom.budget/v1"
BUDGET_EVENT_SCHEMA_VERSION = "newsroom.budget-event/v1"
MAX_BUDGET_INTEGER = 2**63 - 1
MAX_RESERVATION_TTL_SECONDS = 7 * 24 * 60 * 60
COST_QUANTUM = Decimal("0.000000000001")
MAX_COST_USD = Decimal("1000000000000")
MAX_SNAPSHOT_RECORDS = 10_000
MAX_BUDGET_REASON_CODES = 16


class BudgetDimension(str, Enum):
    LLM_CALLS = "llm_calls"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    REASONING_TOKENS = "reasoning_tokens"
    CACHED_INPUT_TOKENS = "cached_input_tokens"
    ESTIMATED_COST_USD = "estimated_cost_usd"


class BudgetScopeType(str, Enum):
    RUN = "run"
    GRAPH = "graph"
    AGENT_LOOP = "agent_loop"
    SUBAGENT = "subagent"
    OPERATION = "operation"


class BudgetReservationStatus(str, Enum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    EXPIRED = "expired"
    INDETERMINATE = "indeterminate"


class BudgetSettlementOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INDETERMINATE = "indeterminate"


class BudgetReasonCode(str, Enum):
    MAX_LLM_CALLS = "max_llm_calls"
    MAX_INPUT_TOKENS = "max_input_tokens"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    MAX_REASONING_TOKENS = "max_reasoning_tokens"
    MAX_CACHED_INPUT_TOKENS = "max_cached_input_tokens"
    MAX_TOTAL_TOKENS = "max_total_tokens"
    MAX_ESTIMATED_COST_USD = "max_estimated_cost_usd"
    RESERVATION_EXPIRED = "reservation_expired"
    RESERVATION_RELEASED = "reservation_released"
    DISPATCH_INDETERMINATE = "dispatch_indeterminate"
    ACTUAL_EXCEEDS_RESERVATION = "actual_exceeds_reservation"


_AMOUNT_FIELDS = tuple(item.value for item in BudgetDimension)


def canonical_cost(value: Any, field_name: str = "estimated_cost_usd") -> Decimal:
    if isinstance(value, bool):
        raise BudgetContractError(f"{field_name} must be a decimal value")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BudgetContractError(f"{field_name} must be a decimal value") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > MAX_COST_USD:
        raise BudgetContractError(
            f"{field_name} must be finite and between 0 and {MAX_COST_USD}"
        )
    return parsed.quantize(COST_QUANTUM, rounding=ROUND_HALF_EVEN)


def canonical_cost_text(value: Decimal) -> str:
    normalized = value.quantize(COST_QUANTUM, rounding=ROUND_HALF_EVEN)
    return format(normalized, "f")


def _bounded_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetContractError(f"{field_name} must be an integer")
    if value < 0 or value > MAX_BUDGET_INTEGER:
        raise BudgetContractError(
            f"{field_name} must be between 0 and {MAX_BUDGET_INTEGER}"
        )
    return value


def _optional_bounded_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _bounded_int(value, field_name)


def _required_text(value: Any, field_name: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise BudgetContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise BudgetContractError(f"{field_name} is required and must be bounded")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BudgetContractError(f"{field_name} must be an object")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], field_name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BudgetContractError(f"{field_name} contains unknown fields: {unknown}")


@dataclass(frozen=True)
class BudgetAmounts:
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in _AMOUNT_FIELDS[:-1]:
            object.__setattr__(self, name, _bounded_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "estimated_cost_usd",
            canonical_cost(self.estimated_cost_usd),
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens

    def add(self, other: "BudgetAmounts") -> "BudgetAmounts":
        return BudgetAmounts(
            llm_calls=_checked_sum(self.llm_calls, other.llm_calls, "llm_calls"),
            input_tokens=_checked_sum(
                self.input_tokens, other.input_tokens, "input_tokens"
            ),
            output_tokens=_checked_sum(
                self.output_tokens, other.output_tokens, "output_tokens"
            ),
            reasoning_tokens=_checked_sum(
                self.reasoning_tokens, other.reasoning_tokens, "reasoning_tokens"
            ),
            cached_input_tokens=_checked_sum(
                self.cached_input_tokens,
                other.cached_input_tokens,
                "cached_input_tokens",
            ),
            estimated_cost_usd=canonical_cost(
                self.estimated_cost_usd + other.estimated_cost_usd
            ),
        )

    def subtract(self, other: "BudgetAmounts") -> "BudgetAmounts":
        values = {
            name: getattr(self, name) - getattr(other, name)
            for name in _AMOUNT_FIELDS[:-1]
        }
        if any(value < 0 for value in values.values()):
            raise BudgetContractError("budget amount subtraction would become negative")
        cost = self.estimated_cost_usd - other.estimated_cost_usd
        if cost < 0:
            raise BudgetContractError("budget cost subtraction would become negative")
        return BudgetAmounts(**values, estimated_cost_usd=cost)

    def within(self, ceiling: "BudgetAmounts") -> bool:
        return all(
            getattr(self, name) <= getattr(ceiling, name)
            for name in _AMOUNT_FIELDS
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "estimated_cost_usd": canonical_cost_text(self.estimated_cost_usd),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetAmounts":
        value = _mapping(value, "amounts")
        _reject_unknown(value, set(_AMOUNT_FIELDS), "amounts")
        return cls(
            llm_calls=value.get("llm_calls", 0),
            input_tokens=value.get("input_tokens", 0),
            output_tokens=value.get("output_tokens", 0),
            reasoning_tokens=value.get("reasoning_tokens", 0),
            cached_input_tokens=value.get("cached_input_tokens", 0),
            estimated_cost_usd=value.get("estimated_cost_usd", "0"),
        )


@dataclass(frozen=True)
class BudgetLimits:
    llm_calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    estimated_cost_usd: Decimal | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in _AMOUNT_FIELDS[:-1]:
            object.__setattr__(
                self,
                name,
                _optional_bounded_int(getattr(self, name), name),
            )
        object.__setattr__(
            self,
            "total_tokens",
            _optional_bounded_int(self.total_tokens, "total_tokens"),
        )
        if self.estimated_cost_usd is not None:
            object.__setattr__(
                self,
                "estimated_cost_usd",
                canonical_cost(self.estimated_cost_usd),
            )

    def violations(self, amounts: BudgetAmounts) -> tuple[str, ...]:
        codes: list[str] = []
        mapping = {
            "llm_calls": BudgetReasonCode.MAX_LLM_CALLS.value,
            "input_tokens": BudgetReasonCode.MAX_INPUT_TOKENS.value,
            "output_tokens": BudgetReasonCode.MAX_OUTPUT_TOKENS.value,
            "reasoning_tokens": BudgetReasonCode.MAX_REASONING_TOKENS.value,
            "cached_input_tokens": BudgetReasonCode.MAX_CACHED_INPUT_TOKENS.value,
            "estimated_cost_usd": BudgetReasonCode.MAX_ESTIMATED_COST_USD.value,
        }
        for name, code in mapping.items():
            limit = getattr(self, name)
            if limit is not None and getattr(amounts, name) > limit:
                codes.append(code)
        if self.total_tokens is not None and amounts.total_tokens > self.total_tokens:
            codes.append(BudgetReasonCode.MAX_TOTAL_TOKENS.value)
        return tuple(sorted(codes))

    def available(self, used: BudgetAmounts) -> BudgetAmounts:
        def remaining(name: str) -> Any:
            limit = getattr(self, name)
            if limit is None:
                return MAX_COST_USD if name == "estimated_cost_usd" else MAX_BUDGET_INTEGER
            return max(0, limit - getattr(used, name))

        return BudgetAmounts(**{name: remaining(name) for name in _AMOUNT_FIELDS})

    def to_dict(self) -> dict[str, int | str | None]:
        payload = {
            name: (
                canonical_cost_text(value)
                if name == "estimated_cost_usd" and value is not None
                else value
            )
            for name in _AMOUNT_FIELDS
            if (value := getattr(self, name)) is not None
        }
        if self.total_tokens is not None:
            payload["total_tokens"] = self.total_tokens
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetLimits":
        value = _mapping(value, "limits")
        _reject_unknown(value, {*_AMOUNT_FIELDS, "total_tokens"}, "limits")
        return cls(
            **{name: value.get(name) for name in _AMOUNT_FIELDS},
            total_tokens=value.get("total_tokens"),
        )


@dataclass(frozen=True)
class BudgetPolicy:
    policy_revision: str
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    reservation_ttl_seconds: int = 300
    schema_version: str = BUDGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUDGET_SCHEMA_VERSION:
            raise BudgetContractError(
                f"unsupported budget policy schema: {self.schema_version}"
            )
        object.__setattr__(
            self, "policy_revision", _required_text(self.policy_revision, "policy_revision")
        )
        if not isinstance(self.limits, BudgetLimits):
            object.__setattr__(
                self, "limits", BudgetLimits.from_dict(_mapping(self.limits, "limits"))
            )
        ttl = _bounded_int(self.reservation_ttl_seconds, "reservation_ttl_seconds")
        if ttl > MAX_RESERVATION_TTL_SECONDS:
            raise BudgetContractError("reservation_ttl_seconds exceeds the supported bound")
        object.__setattr__(self, "reservation_ttl_seconds", ttl)

    @property
    def digest(self) -> str:
        payload = stable_json_dumps(self.to_dict()).encode("utf-8")
        return f"sha256:{sha256(payload).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_revision": self.policy_revision,
            "limits": self.limits.to_dict(),
            "reservation_ttl_seconds": self.reservation_ttl_seconds,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetPolicy":
        value = _mapping(value, "policy")
        _reject_unknown(
            value,
            {
                "schema_version",
                "policy_revision",
                "limits",
                "reservation_ttl_seconds",
            },
            "policy",
        )
        return cls(
            schema_version=value.get("schema_version", BUDGET_SCHEMA_VERSION),
            policy_revision=value.get("policy_revision"),
            limits=BudgetLimits.from_dict(_mapping(value.get("limits", {}), "limits")),
            reservation_ttl_seconds=value.get("reservation_ttl_seconds", 300),
        )


@dataclass(frozen=True)
class BudgetScopeRef:
    run_id: str
    scope_id: str
    scope_type: BudgetScopeType | str
    policy_revision: str
    parent_scope_id: str | None = None
    execution_identity: GraphRunIdentity | GraphExecutionIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _required_text(self.run_id, "run_id"))
        object.__setattr__(self, "scope_id", _required_text(self.scope_id, "scope_id"))
        object.__setattr__(
            self, "scope_type", _enum_value(BudgetScopeType, self.scope_type, "scope_type")
        )
        object.__setattr__(
            self, "policy_revision", _required_text(self.policy_revision, "policy_revision")
        )
        object.__setattr__(
            self,
            "parent_scope_id",
            _optional_text(self.parent_scope_id, "parent_scope_id"),
        )
        identity = self.execution_identity
        if identity is not None and not isinstance(
            identity, (GraphRunIdentity, GraphExecutionIdentity)
        ):
            if not isinstance(identity, Mapping):
                raise BudgetContractError("execution_identity must be an object")
            if "activity_id" in identity:
                identity = GraphExecutionIdentity.from_dict(identity)
            else:
                identity = GraphRunIdentity.from_dict(identity)
        if identity is not None and identity.run_id != self.run_id:
            raise BudgetContractError("budget scope execution identity run mismatch")
        object.__setattr__(self, "execution_identity", identity)
        if self.scope_type is BudgetScopeType.GRAPH and not isinstance(
            identity,
            GraphExecutionIdentity,
        ):
            raise BudgetContractError(
                "graph budget scope requires an exact execution identity"
            )
        if self.scope_type is BudgetScopeType.RUN and self.parent_scope_id is not None:
            raise BudgetContractError("run scope cannot have a parent")
        if self.scope_type is not BudgetScopeType.RUN and self.parent_scope_id is None:
            raise BudgetContractError("non-run scope requires parent_scope_id")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "scope_id": self.scope_id,
            "scope_type": self.scope_type.value,
            "parent_scope_id": self.parent_scope_id,
            "policy_revision": self.policy_revision,
        }
        if self.execution_identity is not None:
            payload["execution_identity"] = self.execution_identity.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetScopeRef":
        value = _mapping(value, "scope")
        _reject_unknown(
            value,
            {
                "run_id",
                "scope_id",
                "scope_type",
                "parent_scope_id",
                "policy_revision",
                "execution_identity",
            },
            "scope",
        )
        return cls(**value)


@dataclass(frozen=True)
class BudgetUsage:
    committed: BudgetAmounts
    reserved: BudgetAmounts
    available: BudgetAmounts
    ledger_revision: int

    def __post_init__(self) -> None:
        for name in ("committed", "reserved", "available"):
            value = getattr(self, name)
            if not isinstance(value, BudgetAmounts):
                object.__setattr__(
                    self,
                    name,
                    BudgetAmounts.from_dict(_mapping(value, name)),
                )
        object.__setattr__(
            self,
            "ledger_revision",
            _bounded_int(self.ledger_revision, "ledger_revision"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed": self.committed.to_dict(),
            "reserved": self.reserved.to_dict(),
            "available": self.available.to_dict(),
            "ledger_revision": self.ledger_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetUsage":
        value = _mapping(value, "usage")
        _reject_unknown(
            value, {"committed", "reserved", "available", "ledger_revision"}, "usage"
        )
        return cls(
            committed=BudgetAmounts.from_dict(_mapping(value.get("committed"), "committed")),
            reserved=BudgetAmounts.from_dict(_mapping(value.get("reserved"), "reserved")),
            available=BudgetAmounts.from_dict(_mapping(value.get("available"), "available")),
            ledger_revision=value.get("ledger_revision"),
        )


@dataclass(frozen=True)
class BudgetReservation:
    reservation_id: str
    operation_id: str
    idempotency_key: str
    scope: BudgetScopeRef
    policy_digest: str
    requested: BudgetAmounts
    status: BudgetReservationStatus | str
    created_event_id: str
    created_at_epoch_ms: int

    def __post_init__(self) -> None:
        for name in (
            "reservation_id",
            "operation_id",
            "idempotency_key",
            "policy_digest",
            "created_event_id",
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if not isinstance(self.scope, BudgetScopeRef):
            object.__setattr__(
                self, "scope", BudgetScopeRef.from_dict(_mapping(self.scope, "scope"))
            )
        if not isinstance(self.requested, BudgetAmounts):
            object.__setattr__(
                self,
                "requested",
                BudgetAmounts.from_dict(_mapping(self.requested, "requested")),
            )
        object.__setattr__(
            self,
            "status",
            _enum_value(BudgetReservationStatus, self.status, "status"),
        )
        object.__setattr__(
            self,
            "created_at_epoch_ms",
            _bounded_int(self.created_at_epoch_ms, "created_at_epoch_ms"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "operation_id": self.operation_id,
            "idempotency_key": self.idempotency_key,
            "scope": self.scope.to_dict(),
            "policy_digest": self.policy_digest,
            "requested": self.requested.to_dict(),
            "status": self.status.value,
            "created_event_id": self.created_event_id,
            "created_at_epoch_ms": self.created_at_epoch_ms,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetReservation":
        value = _mapping(value, "reservation")
        _reject_unknown(value, set(cls.__dataclass_fields__), "reservation")
        return cls(**value)


@dataclass(frozen=True)
class BudgetSettlement:
    reservation_id: str
    operation_id: str
    scope: BudgetScopeRef
    policy_digest: str
    actual: BudgetAmounts
    request_dispatched: bool
    cache_hit: bool
    outcome: BudgetSettlementOutcome | str
    settled_event_id: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "reservation_id",
            "operation_id",
            "policy_digest",
            "settled_event_id",
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if not isinstance(self.scope, BudgetScopeRef):
            object.__setattr__(
                self, "scope", BudgetScopeRef.from_dict(_mapping(self.scope, "scope"))
            )
        if not isinstance(self.actual, BudgetAmounts):
            object.__setattr__(
                self,
                "actual",
                BudgetAmounts.from_dict(_mapping(self.actual, "actual")),
            )
        if not isinstance(self.request_dispatched, bool) or not isinstance(
            self.cache_hit, bool
        ):
            raise BudgetContractError("settlement dispatch and cache flags must be booleans")
        object.__setattr__(
            self,
            "outcome",
            _enum_value(BudgetSettlementOutcome, self.outcome, "outcome"),
        )
        object.__setattr__(
            self, "reason_code", _optional_text(self.reason_code, "reason_code")
        )

    def command_projection(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "operation_id": self.operation_id,
            "scope": self.scope.to_dict(),
            "policy_digest": self.policy_digest,
            "actual": self.actual.to_dict(),
            "request_dispatched": self.request_dispatched,
            "cache_hit": self.cache_hit,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.command_projection(), "settled_event_id": self.settled_event_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetSettlement":
        value = _mapping(value, "settlement")
        _reject_unknown(value, set(cls.__dataclass_fields__), "settlement")
        return cls(**value)


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    violations: tuple[str, ...]
    projected_usage: BudgetUsage
    reservation_id: str | None
    ledger_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise BudgetContractError("allowed must be a boolean")
        violations = tuple(sorted({_required_text(item, "violation") for item in self.violations}))
        if len(violations) > MAX_BUDGET_REASON_CODES:
            raise BudgetContractError("decision contains too many violations")
        object.__setattr__(self, "violations", violations)
        if self.allowed and violations:
            raise BudgetContractError("allowed decision cannot contain violations")
        if not self.allowed and not violations:
            raise BudgetContractError("denied decision requires violations")
        if not isinstance(self.projected_usage, BudgetUsage):
            object.__setattr__(
                self,
                "projected_usage",
                BudgetUsage.from_dict(_mapping(self.projected_usage, "projected_usage")),
            )
        object.__setattr__(
            self, "reservation_id", _optional_text(self.reservation_id, "reservation_id")
        )
        object.__setattr__(
            self,
            "ledger_revision",
            _bounded_int(self.ledger_revision, "ledger_revision"),
        )

    @property
    def within_budget(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "within_budget": self.allowed,
            "violations": list(self.violations),
            "projected_usage": self.projected_usage.to_dict(),
            "reservation_id": self.reservation_id,
            "ledger_revision": self.ledger_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetDecision":
        value = _mapping(value, "decision")
        _reject_unknown(
            value,
            {
                "allowed",
                "within_budget",
                "violations",
                "projected_usage",
                "reservation_id",
                "ledger_revision",
            },
            "decision",
        )
        allowed = value.get("allowed", value.get("within_budget"))
        return cls(
            allowed=allowed,
            violations=tuple(value.get("violations") or ()),
            projected_usage=BudgetUsage.from_dict(
                _mapping(value.get("projected_usage"), "projected_usage")
            ),
            reservation_id=value.get("reservation_id"),
            ledger_revision=value.get("ledger_revision"),
        )


@dataclass(frozen=True)
class BudgetView:
    scope: BudgetScopeRef
    policy: BudgetPolicy
    usage: BudgetUsage

    def __post_init__(self) -> None:
        if not isinstance(self.scope, BudgetScopeRef):
            object.__setattr__(
                self, "scope", BudgetScopeRef.from_dict(_mapping(self.scope, "scope"))
            )
        if not isinstance(self.policy, BudgetPolicy):
            object.__setattr__(
                self,
                "policy",
                BudgetPolicy.from_dict(_mapping(self.policy, "policy")),
            )
        if not isinstance(self.usage, BudgetUsage):
            object.__setattr__(
                self, "usage", BudgetUsage.from_dict(_mapping(self.usage, "usage"))
            )
        if self.scope.policy_revision != self.policy.policy_revision:
            raise BudgetContractError("view scope policy revision mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "policy": self.policy.to_dict(),
            "policy_digest": self.policy.digest,
            "usage": self.usage.to_dict(),
        }


@dataclass(frozen=True)
class BudgetScopeSnapshot:
    scope: BudgetScopeRef
    policy: BudgetPolicy
    committed: BudgetAmounts
    reserved: BudgetAmounts
    baseline_committed: BudgetAmounts | None = None

    def __post_init__(self) -> None:
        for name, model_type in (
            ("scope", BudgetScopeRef),
            ("policy", BudgetPolicy),
            ("committed", BudgetAmounts),
            ("reserved", BudgetAmounts),
        ):
            value = getattr(self, name)
            if not isinstance(value, model_type):
                object.__setattr__(
                    self,
                    name,
                    model_type.from_dict(_mapping(value, name)),
                )
        if self.baseline_committed is not None and not isinstance(
            self.baseline_committed, BudgetAmounts
        ):
            object.__setattr__(
                self,
                "baseline_committed",
                BudgetAmounts.from_dict(
                    _mapping(self.baseline_committed, "baseline_committed")
                ),
            )
        if self.scope.policy_revision != self.policy.policy_revision:
            raise BudgetContractError("snapshot scope policy revision mismatch")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "scope": self.scope.to_dict(),
            "policy": self.policy.to_dict(),
            "committed": self.committed.to_dict(),
            "reserved": self.reserved.to_dict(),
        }
        if self.baseline_committed is not None:
            payload["baseline_committed"] = self.baseline_committed.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetScopeSnapshot":
        value = _mapping(value, "scope_snapshot")
        _reject_unknown(
            value,
            {"scope", "policy", "committed", "reserved", "baseline_committed"},
            "scope_snapshot",
        )
        return cls(
            scope=BudgetScopeRef.from_dict(_mapping(value.get("scope"), "scope")),
            policy=BudgetPolicy.from_dict(_mapping(value.get("policy"), "policy")),
            committed=BudgetAmounts.from_dict(_mapping(value.get("committed"), "committed")),
            reserved=BudgetAmounts.from_dict(_mapping(value.get("reserved"), "reserved")),
            baseline_committed=(
                BudgetAmounts.from_dict(
                    _mapping(value.get("baseline_committed"), "baseline_committed")
                )
                if "baseline_committed" in value
                else None
            ),
        )


@dataclass(frozen=True)
class BudgetOperationRecord:
    operation_id: str
    idempotency_key: str
    fingerprint: str
    reservation_id: str | None
    reservation: BudgetReservation | None = None
    decision: BudgetDecision | None = None
    settlement: BudgetSettlement | None = None

    def __post_init__(self) -> None:
        for name in ("operation_id", "idempotency_key", "fingerprint"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(
            self, "reservation_id", _optional_text(self.reservation_id, "reservation_id")
        )
        for name, model_type in (
            ("reservation", BudgetReservation),
            ("decision", BudgetDecision),
            ("settlement", BudgetSettlement),
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, model_type):
                object.__setattr__(
                    self,
                    name,
                    model_type.from_dict(_mapping(value, name)),
                )
        if self.reservation is not None:
            if (
                self.reservation_id != self.reservation.reservation_id
                or self.operation_id != self.reservation.operation_id
                or self.idempotency_key != self.reservation.idempotency_key
            ):
                raise BudgetContractError("operation record conflicts with reservation")
        elif self.reservation_id is not None:
            raise BudgetContractError("operation record reservation is missing")
        if self.settlement is not None:
            if (
                self.reservation_id != self.settlement.reservation_id
                or self.operation_id != self.settlement.operation_id
            ):
                raise BudgetContractError("operation record conflicts with settlement")
        if self.decision is not None:
            if self.decision.allowed or self.reservation_id is not None:
                raise BudgetContractError("operation denial record is inconsistent")
        elif self.reservation is None:
            raise BudgetContractError("operation record requires reservation or denial")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "idempotency_key": self.idempotency_key,
            "fingerprint": self.fingerprint,
            "reservation_id": self.reservation_id,
            "reservation": self.reservation.to_dict() if self.reservation else None,
            "decision": self.decision.to_dict() if self.decision else None,
            "settlement": self.settlement.to_dict() if self.settlement else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetOperationRecord":
        value = _mapping(value, "operation_record")
        _reject_unknown(value, set(cls.__dataclass_fields__), "operation_record")
        return cls(
            operation_id=value.get("operation_id"),
            idempotency_key=value.get("idempotency_key"),
            fingerprint=value.get("fingerprint"),
            reservation_id=value.get("reservation_id"),
            reservation=(
                BudgetReservation.from_dict(
                    _mapping(value.get("reservation"), "reservation")
                )
                if value.get("reservation") is not None
                else None
            ),
            decision=(
                BudgetDecision.from_dict(_mapping(value.get("decision"), "decision"))
                if value.get("decision") is not None
                else None
            ),
            settlement=(
                BudgetSettlement.from_dict(
                    _mapping(value.get("settlement"), "settlement")
                )
                if value.get("settlement") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class BudgetSnapshot:
    root_scope_id: str
    policy_digest: str
    scopes: tuple[BudgetScopeSnapshot, ...]
    open_reservations: tuple[BudgetReservation, ...]
    operation_records: tuple[BudgetOperationRecord, ...]
    last_event_id: str | None
    ledger_revision: int
    schema_version: str = BUDGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUDGET_SCHEMA_VERSION:
            raise BudgetContractError(f"unsupported budget snapshot schema: {self.schema_version}")
        object.__setattr__(self, "root_scope_id", _required_text(self.root_scope_id, "root_scope_id"))
        object.__setattr__(self, "policy_digest", _required_text(self.policy_digest, "policy_digest"))
        for name, model_type in (
            ("scopes", BudgetScopeSnapshot),
            ("open_reservations", BudgetReservation),
            ("operation_records", BudgetOperationRecord),
        ):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)):
                raise BudgetContractError(f"snapshot {name} must be an array")
            object.__setattr__(
                self,
                name,
                tuple(
                    value
                    if isinstance(value, model_type)
                    else model_type.from_dict(_mapping(value, name))
                    for value in values
                ),
            )
        if len(self.scopes) > MAX_SNAPSHOT_RECORDS:
            raise BudgetContractError("snapshot contains too many scopes")
        if len(self.open_reservations) > MAX_SNAPSHOT_RECORDS:
            raise BudgetContractError("snapshot contains too many open reservations")
        if len(self.operation_records) > MAX_SNAPSHOT_RECORDS:
            raise BudgetContractError("snapshot contains too many operation records")
        object.__setattr__(self, "last_event_id", _optional_text(self.last_event_id, "last_event_id"))
        object.__setattr__(self, "ledger_revision", _bounded_int(self.ledger_revision, "ledger_revision"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root_scope_id": self.root_scope_id,
            "policy_digest": self.policy_digest,
            "scopes": [item.to_dict() for item in self.scopes],
            "open_reservations": [item.to_dict() for item in self.open_reservations],
            "operation_records": [item.to_dict() for item in self.operation_records],
            "last_event_id": self.last_event_id,
            "ledger_revision": self.ledger_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetSnapshot":
        value = _mapping(value, "snapshot")
        _reject_unknown(value, set(cls.__dataclass_fields__), "snapshot")
        scopes = value.get("scopes")
        reservations = value.get("open_reservations")
        records = value.get("operation_records")
        if not isinstance(scopes, list):
            raise BudgetContractError("snapshot scopes must be an array")
        if not isinstance(reservations, list):
            raise BudgetContractError("snapshot open_reservations must be an array")
        if not isinstance(records, list):
            raise BudgetContractError("snapshot operation_records must be an array")
        return cls(
            schema_version=value.get("schema_version"),
            root_scope_id=value.get("root_scope_id"),
            policy_digest=value.get("policy_digest"),
            scopes=tuple(
                BudgetScopeSnapshot.from_dict(_mapping(item, "scope_snapshot"))
                for item in scopes
            ),
            open_reservations=tuple(
                BudgetReservation.from_dict(_mapping(item, "reservation"))
                for item in reservations
            ),
            operation_records=tuple(
                BudgetOperationRecord.from_dict(_mapping(item, "operation_record"))
                for item in records
            ),
            last_event_id=value.get("last_event_id"),
            ledger_revision=value.get("ledger_revision"),
        )


@dataclass(frozen=True)
class BudgetEvent:
    event_id: str
    event_type: str
    run_id: str
    scope: BudgetScopeRef
    policy_digest: str
    ledger_revision: int
    operation_id: str
    idempotency_key: str
    reservation_id: str | None
    amounts: BudgetAmounts
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    outcome: str | None = None
    reservation: BudgetReservation | None = None
    settlement: BudgetSettlement | None = None
    schema_version: str = BUDGET_EVENT_SCHEMA_VERSION

    ALLOWED_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "budget_reservation_created",
            "budget_reservation_denied",
            "budget_reservation_settled",
            "budget_reservation_released",
            "budget_reservation_expired",
            "budget_reservation_indeterminate",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != BUDGET_EVENT_SCHEMA_VERSION:
            raise BudgetContractError(f"unsupported budget event schema: {self.schema_version}")
        for name in (
            "event_id",
            "run_id",
            "policy_digest",
            "operation_id",
            "idempotency_key",
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if self.event_type not in self.ALLOWED_TYPES:
            raise BudgetContractError(f"unsupported budget event type: {self.event_type}")
        if not isinstance(self.scope, BudgetScopeRef):
            object.__setattr__(self, "scope", BudgetScopeRef.from_dict(_mapping(self.scope, "scope")))
        if not isinstance(self.amounts, BudgetAmounts):
            object.__setattr__(self, "amounts", BudgetAmounts.from_dict(_mapping(self.amounts, "amounts")))
        if self.reservation is not None and not isinstance(
            self.reservation, BudgetReservation
        ):
            object.__setattr__(
                self,
                "reservation",
                BudgetReservation.from_dict(
                    _mapping(self.reservation, "reservation")
                ),
            )
        if self.settlement is not None and not isinstance(
            self.settlement, BudgetSettlement
        ):
            object.__setattr__(
                self,
                "settlement",
                BudgetSettlement.from_dict(
                    _mapping(self.settlement, "settlement")
                ),
            )
        object.__setattr__(self, "reservation_id", _optional_text(self.reservation_id, "reservation_id"))
        object.__setattr__(self, "ledger_revision", _bounded_int(self.ledger_revision, "ledger_revision"))
        if self.ledger_revision < 1:
            raise BudgetContractError("budget event ledger_revision must be positive")
        reason_codes = tuple(
            sorted({_required_text(item, "reason_code") for item in self.reason_codes})
        )
        if len(reason_codes) > MAX_BUDGET_REASON_CODES:
            raise BudgetContractError("budget event contains too many reason codes")
        object.__setattr__(self, "reason_codes", reason_codes)
        object.__setattr__(self, "outcome", _optional_text(self.outcome, "outcome"))
        self._validate_projection()

    def _validate_projection(self) -> None:
        if self.run_id != self.scope.run_id:
            raise BudgetContractError("budget event run_id does not match scope")
        if self.reservation is not None:
            reservation = self.reservation
            if (
                self.reservation_id != reservation.reservation_id
                or self.operation_id != reservation.operation_id
                or self.idempotency_key != reservation.idempotency_key
                or self.scope != reservation.scope
                or self.policy_digest != reservation.policy_digest
            ):
                raise BudgetContractError(
                    "budget event conflicts with its reservation projection"
                )
        if self.settlement is not None:
            settlement = self.settlement
            if (
                self.reservation_id != settlement.reservation_id
                or self.operation_id != settlement.operation_id
                or self.scope != settlement.scope
                or self.policy_digest != settlement.policy_digest
                or self.event_id != settlement.settled_event_id
            ):
                raise BudgetContractError(
                    "budget event conflicts with its settlement projection"
                )

        if self.event_type == "budget_reservation_created":
            if (
                self.reservation is None
                or self.settlement is not None
                or self.reservation.status is not BudgetReservationStatus.RESERVED
                or self.reservation.created_event_id != self.event_id
                or self.amounts != self.reservation.requested
                or self.outcome != BudgetReservationStatus.RESERVED.value
                or self.reason_codes
            ):
                raise BudgetContractError("invalid reservation-created event projection")
            return
        if self.event_type == "budget_reservation_denied":
            if (
                self.reservation_id is not None
                or self.reservation is not None
                or self.settlement is not None
                or self.outcome != "denied"
                or not self.reason_codes
            ):
                raise BudgetContractError("invalid reservation-denied event projection")
            return
        if self.event_type == "budget_reservation_settled":
            if (
                self.reservation is not None
                or self.settlement is None
                or self.settlement.outcome
                not in {
                    BudgetSettlementOutcome.SUCCEEDED,
                    BudgetSettlementOutcome.FAILED,
                }
                or self.amounts != self.settlement.actual
                or self.outcome != self.settlement.outcome.value
                or self.reason_codes
                != (
                    (self.settlement.reason_code,)
                    if self.settlement.reason_code is not None
                    else ()
                )
            ):
                raise BudgetContractError("invalid reservation-settled event projection")
            return
        if self.event_type in {
            "budget_reservation_released",
            "budget_reservation_expired",
        }:
            expected_outcome = (
                BudgetReservationStatus.RELEASED.value
                if self.event_type == "budget_reservation_released"
                else BudgetReservationStatus.EXPIRED.value
            )
            if (
                self.reservation is not None
                or self.settlement is None
                or self.settlement.outcome is not BudgetSettlementOutcome.CANCELLED
                or self.settlement.request_dispatched
                or self.settlement.actual != BudgetAmounts()
                or self.outcome != expected_outcome
                or self.settlement.reason_code is None
                or self.reason_codes != (self.settlement.reason_code,)
            ):
                raise BudgetContractError("invalid reservation-release event projection")
            return
        if (
            self.reservation is not None
            or self.settlement is None
            or self.settlement.outcome is not BudgetSettlementOutcome.INDETERMINATE
            or not self.settlement.request_dispatched
            or self.settlement.actual != BudgetAmounts()
            or self.outcome != BudgetReservationStatus.INDETERMINATE.value
            or self.settlement.reason_code is None
            or self.reason_codes != (self.settlement.reason_code,)
        ):
            raise BudgetContractError("invalid reservation-indeterminate event projection")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "scope": self.scope.to_dict(),
            "policy_digest": self.policy_digest,
            "ledger_revision": self.ledger_revision,
            "operation_id": self.operation_id,
            "idempotency_key": self.idempotency_key,
            "reservation_id": self.reservation_id,
            "amounts": self.amounts.to_dict(),
            "reason_codes": list(self.reason_codes),
            "outcome": self.outcome,
            "reservation": self.reservation.to_dict() if self.reservation else None,
            "settlement": self.settlement.to_dict() if self.settlement else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BudgetEvent":
        value = _mapping(value, "event")
        _reject_unknown(value, set(cls.__dataclass_fields__) - {"ALLOWED_TYPES"}, "event")
        return cls(
            schema_version=value.get("schema_version"),
            event_id=value.get("event_id"),
            event_type=value.get("event_type"),
            run_id=value.get("run_id"),
            scope=BudgetScopeRef.from_dict(_mapping(value.get("scope"), "scope")),
            policy_digest=value.get("policy_digest"),
            ledger_revision=value.get("ledger_revision"),
            operation_id=value.get("operation_id"),
            idempotency_key=value.get("idempotency_key"),
            reservation_id=value.get("reservation_id"),
            amounts=BudgetAmounts.from_dict(_mapping(value.get("amounts"), "amounts")),
            reason_codes=tuple(value.get("reason_codes") or ()),
            outcome=value.get("outcome"),
            reservation=(
                BudgetReservation.from_dict(_mapping(value.get("reservation"), "reservation"))
                if value.get("reservation") is not None
                else None
            ),
            settlement=(
                BudgetSettlement.from_dict(_mapping(value.get("settlement"), "settlement"))
                if value.get("settlement") is not None
                else None
            ),
        )


def operation_fingerprint(
    *, scope: BudgetScopeRef, requested: BudgetAmounts, policy_digest: str
) -> str:
    projection = {
        "scope": scope.to_dict(),
        "requested": requested.to_dict(),
        "policy_digest": policy_digest,
    }
    return f"sha256:{sha256(stable_json_dumps(projection).encode('utf-8')).hexdigest()}"


def _checked_sum(left: int, right: int, field_name: str) -> int:
    result = left + right
    if result > MAX_BUDGET_INTEGER:
        raise BudgetContractError(f"{field_name} exceeds the supported bound")
    return result


def _enum_value(enum_type: type[Enum], value: Any, field_name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise BudgetContractError(f"invalid {field_name}: {value}") from exc


__all__ = [
    "BUDGET_EVENT_SCHEMA_VERSION",
    "BUDGET_SCHEMA_VERSION",
    "BudgetAmounts",
    "BudgetDecision",
    "BudgetDimension",
    "BudgetEvent",
    "BudgetLimits",
    "BudgetOperationRecord",
    "BudgetPolicy",
    "BudgetReasonCode",
    "BudgetReservation",
    "BudgetReservationStatus",
    "BudgetScopeRef",
    "BudgetScopeSnapshot",
    "BudgetScopeType",
    "BudgetSettlement",
    "BudgetSettlementOutcome",
    "BudgetSnapshot",
    "BudgetUsage",
    "BudgetView",
    "canonical_cost",
    "canonical_cost_text",
    "operation_fingerprint",
]
