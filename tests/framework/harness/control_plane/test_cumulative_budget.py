from __future__ import annotations

from framework.events import CanonicalBudgetFact
from framework.events.canonical import checksum_for
from framework.governance.budget import (
    BudgetAmounts,
    BudgetEvent,
    BudgetScopeRef,
    BudgetSettlement,
)
from framework.harness import HarnessWorkerResult
from framework.harness.control_plane.cumulative_budget import (
    resolve_harness_cumulative_budget_fact,
)
from framework.shared.graph_identity import GraphExecutionIdentity


class _FactResolver:
    def __init__(self, fact: CanonicalBudgetFact | None) -> None:
        self.fact = fact
        self.calls: list[tuple[str, str, int, object | None]] = []

    def resolve(
        self,
        *,
        run_id: str,
        operation_id: str,
        ledger_revision: int,
        expected_identity=None,
    ):
        self.calls.append((run_id, operation_id, ledger_revision, expected_identity))
        return self.fact


def test_worker_locator_resolves_verified_durable_budget_fact() -> None:
    fact = _fact(event_type="budget_reservation_settled", revision=2)
    resolver = _FactResolver(fact)
    worker = _worker_check(
        within_budget=True,
        ledger_revision=2,
        reservation_id="reservation-1",
    )

    resolved = resolve_harness_cumulative_budget_fact(
        run_id="run-budget",
        worker_result=worker,
        resolver=resolver,  # type: ignore[arg-type]
    )

    assert resolved is not None
    assert resolved.resolution_status == "verified"
    assert resolved.fact_ref == fact.fact_ref
    assert resolved.event_type == "budget_reservation_settled"
    assert resolver.calls == [("run-budget", "operation-1", 2, None)]


def test_worker_locator_forwards_expected_graph_identity() -> None:
    fact = _fact(event_type="budget_reservation_settled", revision=2)
    resolver = _FactResolver(fact)
    identity = GraphExecutionIdentity(
        run_id="run-budget",
        graph_id="research.paper-analysis",
        graph_version="4",
        graph_ref="research.paper-analysis@4",
        graph_checksum="sha256:" + "a" * 64,
        node_id="analyze",
        node_instance_id="analyze:1",
        activity_id="activity-budget",
        attempt=1,
    )

    resolved = resolve_harness_cumulative_budget_fact(
        run_id="run-budget",
        worker_result=_worker_check(
            within_budget=True,
            ledger_revision=2,
            reservation_id="reservation-1",
        ),
        resolver=resolver,  # type: ignore[arg-type]
        expected_identity=identity,
    )

    assert resolved is not None
    assert resolver.calls == [("run-budget", "operation-1", 2, identity)]


def test_worker_decision_cannot_override_durable_budget_fact() -> None:
    resolver = _FactResolver(
        _fact(
            event_type="budget_reservation_denied",
            revision=1,
            reservation_id=None,
            reason_codes=("max_llm_calls",),
        )
    )
    worker = _worker_check(
        within_budget=True,
        ledger_revision=1,
        reservation_id=None,
    )

    resolved = resolve_harness_cumulative_budget_fact(
        run_id="run-budget",
        worker_result=worker,
        resolver=resolver,  # type: ignore[arg-type]
    )

    assert resolved is not None
    assert resolved.resolution_status == "invalid"
    assert resolved.reason_code == "budget_fact_decision_mismatch"
    assert resolved.within_budget is True


def test_worker_scope_projection_cannot_point_at_another_budget_scope() -> None:
    resolver = _FactResolver(
        _fact(event_type="budget_reservation_settled", revision=2)
    )
    worker = _worker_check(
        within_budget=True,
        ledger_revision=2,
        reservation_id="reservation-1",
    )
    worker.metrics["global_budget_check"]["scope_id"] = "run:other"

    resolved = resolve_harness_cumulative_budget_fact(
        run_id="run-budget",
        worker_result=worker,
        resolver=resolver,  # type: ignore[arg-type]
    )

    assert resolved is not None
    assert resolved.reason_code == "budget_fact_scope_mismatch"


def test_missing_or_malformed_budget_history_fails_closed() -> None:
    missing = resolve_harness_cumulative_budget_fact(
        run_id="run-budget",
        worker_result=_worker_check(
            within_budget=True,
            ledger_revision=2,
            reservation_id="reservation-1",
        ),
        resolver=_FactResolver(None),  # type: ignore[arg-type]
    )
    malformed = resolve_harness_cumulative_budget_fact(
        run_id="run-budget",
        worker_result=HarnessWorkerResult(
            status="succeeded",
            metrics={"global_budget_check": {"within_budget": True}},
        ),
        resolver=_FactResolver(None),  # type: ignore[arg-type]
    )

    assert missing is not None
    assert missing.reason_code == "budget_fact_missing"
    assert missing.resolution_status == "invalid"
    assert malformed is not None
    assert malformed.reason_code == "budget_fact_locator_invalid"


def _worker_check(
    *,
    within_budget: bool,
    ledger_revision: int,
    reservation_id: str | None,
    violations: tuple[str, ...] = (),
) -> HarnessWorkerResult:
    return HarnessWorkerResult(
        status="succeeded",
        metrics={
            "global_budget_check": {
                "within_budget": within_budget,
                "violations": list(violations),
                "reservation_id": reservation_id,
                "operation_id": "operation-1",
                "ledger_revision": ledger_revision,
            }
        },
    )


def _fact(
    *,
    event_type: str,
    revision: int,
    reservation_id: str | None = "reservation-1",
    reason_codes: tuple[str, ...] = (),
) -> CanonicalBudgetFact:
    scope = BudgetScopeRef(
        run_id="run-budget",
        scope_id="run-budget:root",
        scope_type="run",
        policy_revision="policy-v1",
    )
    policy_digest = checksum_for({"policy": "v1"})
    settlement = (
        BudgetSettlement(
            reservation_id=reservation_id,
            operation_id="operation-1",
            scope=scope,
            policy_digest=policy_digest,
            actual=BudgetAmounts(llm_calls=1),
            request_dispatched=True,
            cache_hit=False,
            outcome="succeeded",
            settled_event_id=f"event-{revision}",
        )
        if event_type == "budget_reservation_settled"
        and reservation_id is not None
        else None
    )
    event = BudgetEvent(
        event_id=f"event-{revision}",
        event_type=event_type,
        run_id="run-budget",
        scope=scope,
        policy_digest=policy_digest,
        ledger_revision=revision,
        operation_id="operation-1",
        idempotency_key="idempotency-1",
        reservation_id=reservation_id,
        amounts=BudgetAmounts(llm_calls=1),
        reason_codes=reason_codes,
        outcome=("denied" if event_type == "budget_reservation_denied" else "succeeded"),
        settlement=settlement,
    )
    return CanonicalBudgetFact(
        event=event,
        fact_ref=checksum_for(event.to_dict()),
        stream_sequence=revision,
    )
