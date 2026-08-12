from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from framework.events.budget import CanonicalBudgetFact, DurableBudgetFactResolver
from framework.governance.budget import BudgetHistoryError
from framework.governance.budget import MAX_BUDGET_REASON_CODES
from framework.harness.workers.result import HarnessWorkerResult


_TERMINAL_ALLOWED_EVENTS = frozenset(
    {
        "budget_reservation_settled",
        "budget_reservation_released",
        "budget_reservation_expired",
    }
)
_TERMINAL_DENIED_EVENTS = frozenset(
    {
        "budget_reservation_denied",
        "budget_reservation_indeterminate",
    }
)


@dataclass(frozen=True, slots=True)
class HarnessCumulativeBudgetFact:
    resolution_status: str
    operation_id: str
    ledger_revision: int
    within_budget: bool
    violations: tuple[str, ...]
    fact_ref: str | None = None
    event_id: str | None = None
    event_type: str | None = None
    reservation_id: str | None = None
    policy_digest: str | None = None
    scope_id: str | None = None
    stream_sequence: int | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.resolution_status not in {"verified", "invalid"}:
            raise ValueError("resolution_status must be verified or invalid")
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("operation_id is required")
        if (
            isinstance(self.ledger_revision, bool)
            or not isinstance(self.ledger_revision, int)
            or self.ledger_revision < 1
        ):
            raise ValueError("ledger_revision must be a positive integer")
        if not isinstance(self.within_budget, bool):
            raise ValueError("within_budget must be a boolean")
        violations = tuple(sorted(set(self.violations)))
        if any(not isinstance(item, str) or not item.strip() for item in violations):
            raise ValueError("violations must contain bounded reason strings")
        if len(violations) > MAX_BUDGET_REASON_CODES:
            raise ValueError("violations exceed the supported bound")
        object.__setattr__(self, "operation_id", self.operation_id.strip())
        object.__setattr__(self, "violations", violations)
        if self.resolution_status == "verified":
            for field_name in (
                "fact_ref",
                "event_id",
                "event_type",
                "policy_digest",
                "scope_id",
            ):
                value = getattr(self, field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field_name} is required for a verified fact")
            if (
                isinstance(self.stream_sequence, bool)
                or not isinstance(self.stream_sequence, int)
                or self.stream_sequence < 1
            ):
                raise ValueError("stream_sequence is required for a verified fact")
            if self.reason_code is not None:
                raise ValueError("verified fact cannot carry a resolution error")
        elif not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ValueError("invalid fact requires a stable reason_code")

    @property
    def indeterminate(self) -> bool:
        return self.event_type == "budget_reservation_indeterminate"

    @property
    def denied(self) -> bool:
        return self.event_type == "budget_reservation_denied"

    def control_projection(self) -> dict[str, Any]:
        return {
            "resolution_status": self.resolution_status,
            "operation_id": self.operation_id,
            "ledger_revision": self.ledger_revision,
            "within_budget": self.within_budget,
            "violations": list(self.violations),
            "fact_ref": self.fact_ref,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "reservation_id": self.reservation_id,
            "policy_digest": self.policy_digest,
            "scope_id": self.scope_id,
            "stream_sequence": self.stream_sequence,
            "reason_code": self.reason_code,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.control_projection()


def resolve_harness_cumulative_budget_fact(
    *,
    run_id: str,
    worker_result: HarnessWorkerResult,
    resolver: DurableBudgetFactResolver | None,
) -> HarnessCumulativeBudgetFact | None:
    check = _budget_check(worker_result)
    if check is None:
        return None
    operation_id = check.get("operation_id")
    revision = check.get("ledger_revision")
    within_budget = check.get("within_budget", check.get("allowed"))
    violations = check.get("violations", ())
    if (
        not isinstance(operation_id, str)
        or not operation_id.strip()
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or not isinstance(within_budget, bool)
        or not isinstance(violations, list | tuple)
        or any(not isinstance(item, str) or not item.strip() for item in violations)
    ):
        return _invalid_fact(
            operation_id=operation_id,
            ledger_revision=revision,
            within_budget=within_budget,
            violations=violations,
            reason_code="budget_fact_locator_invalid",
        )
    if resolver is None:
        return _invalid_fact(
            operation_id=operation_id,
            ledger_revision=revision,
            within_budget=within_budget,
            violations=violations,
            reason_code="budget_fact_resolver_unavailable",
        )
    try:
        fact = resolver.resolve(
            run_id=run_id,
            operation_id=operation_id,
            ledger_revision=revision,
        )
    except (BudgetHistoryError, TypeError, ValueError):
        return _invalid_fact(
            operation_id=operation_id,
            ledger_revision=revision,
            within_budget=within_budget,
            violations=violations,
            reason_code="budget_fact_history_invalid",
        )
    if fact is None:
        return _invalid_fact(
            operation_id=operation_id,
            ledger_revision=revision,
            within_budget=within_budget,
            violations=violations,
            reason_code="budget_fact_missing",
        )
    return _verified_fact(check, fact)


def _verified_fact(
    check: Mapping[str, Any],
    fact: CanonicalBudgetFact,
) -> HarnessCumulativeBudgetFact:
    event = fact.event
    expected_within_budget = event.event_type in _TERMINAL_ALLOWED_EVENTS
    if event.event_type not in _TERMINAL_ALLOWED_EVENTS | _TERMINAL_DENIED_EVENTS:
        return _invalid_from_resolved(check, fact, "budget_fact_not_terminal")
    if bool(check.get("within_budget", check.get("allowed"))) != expected_within_budget:
        return _invalid_from_resolved(check, fact, "budget_fact_decision_mismatch")
    check_reservation_id = check.get("reservation_id")
    if check_reservation_id != event.reservation_id:
        return _invalid_from_resolved(check, fact, "budget_fact_identity_mismatch")
    for field_name, expected in (
        ("run_id", event.run_id),
        ("scope_id", event.scope.scope_id),
        ("policy_digest", event.policy_digest),
    ):
        supplied = check.get(field_name)
        if supplied is not None and supplied != expected:
            return _invalid_from_resolved(check, fact, "budget_fact_scope_mismatch")
    check_violations = tuple(sorted(set(check.get("violations", ()))))
    if expected_within_budget:
        if check_violations:
            return _invalid_from_resolved(check, fact, "budget_fact_reason_mismatch")
    elif check_violations != tuple(sorted(event.reason_codes)):
        return _invalid_from_resolved(check, fact, "budget_fact_reason_mismatch")
    return HarnessCumulativeBudgetFact(
        resolution_status="verified",
        operation_id=event.operation_id,
        ledger_revision=event.ledger_revision,
        within_budget=expected_within_budget,
        violations=check_violations,
        fact_ref=fact.fact_ref,
        event_id=event.event_id,
        event_type=event.event_type,
        reservation_id=event.reservation_id,
        policy_digest=event.policy_digest,
        scope_id=event.scope.scope_id,
        stream_sequence=fact.stream_sequence,
    )


def _invalid_from_resolved(
    check: Mapping[str, Any],
    fact: CanonicalBudgetFact,
    reason_code: str,
) -> HarnessCumulativeBudgetFact:
    return HarnessCumulativeBudgetFact(
        resolution_status="invalid",
        operation_id=fact.event.operation_id,
        ledger_revision=fact.event.ledger_revision,
        within_budget=bool(check.get("within_budget", check.get("allowed"))),
        violations=tuple(check.get("violations", ())),
        reason_code=reason_code,
    )


def _invalid_fact(
    *,
    operation_id: Any,
    ledger_revision: Any,
    within_budget: Any,
    violations: Any,
    reason_code: str,
) -> HarnessCumulativeBudgetFact:
    safe_operation_id = (
        operation_id.strip()
        if isinstance(operation_id, str) and operation_id.strip()
        else "invalid-budget-operation"
    )
    safe_revision = (
        ledger_revision
        if isinstance(ledger_revision, int)
        and not isinstance(ledger_revision, bool)
        and ledger_revision > 0
        else 1
    )
    safe_violations = (
        tuple(item for item in violations if isinstance(item, str) and item.strip())
        if isinstance(violations, list | tuple)
        else ()
    )
    return HarnessCumulativeBudgetFact(
        resolution_status="invalid",
        operation_id=safe_operation_id,
        ledger_revision=safe_revision,
        within_budget=within_budget if isinstance(within_budget, bool) else False,
        violations=safe_violations,
        reason_code=reason_code,
    )


def _budget_check(worker_result: HarnessWorkerResult) -> Mapping[str, Any] | None:
    for channel in (worker_result.metrics, worker_result.diagnostics):
        value = channel.get("global_budget_check")
        if value is not None:
            return value if isinstance(value, Mapping) else {"invalid": True}
    return None


__all__ = [
    "HarnessCumulativeBudgetFact",
    "resolve_harness_cumulative_budget_fact",
]
