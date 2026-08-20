from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest

from framework.governance.budget import (
    BudgetAmounts,
    BudgetDecision,
    BudgetLedger,
    BudgetLimits,
    BudgetPolicy,
    BudgetReservation,
    BudgetScopeRef,
)


@pytest.mark.parametrize(
    ("limits", "requested"),
    [
        (BudgetLimits(llm_calls=5), BudgetAmounts(llm_calls=1)),
        (BudgetLimits(input_tokens=50), BudgetAmounts(input_tokens=10)),
        (
            BudgetLimits(estimated_cost_usd="5"),
            BudgetAmounts(estimated_cost_usd="1"),
        ),
    ],
)
@pytest.mark.parametrize("caller_count", [4, 5, 6])
def test_concurrent_boundary_reservations_are_linearized_across_scopes(
    limits: BudgetLimits,
    requested: BudgetAmounts,
    caller_count: int,
) -> None:
    policy = BudgetPolicy(policy_revision="root-v1", limits=limits)
    root = BudgetScopeRef(
        run_id="run-1",
        scope_id="root",
        scope_type="run",
        policy_revision=policy.policy_revision,
    )
    ledger = BudgetLedger(root, policy)
    scopes: list[BudgetScopeRef] = []
    for index in range(caller_count):
        child_policy = BudgetPolicy(policy_revision=f"child-v{index}")
        child = BudgetScopeRef(
            run_id=root.run_id,
            scope_id=f"child:{index}",
            scope_type="agent_loop" if index % 2 == 0 else "subagent",
            parent_scope_id=root.scope_id,
            policy_revision=child_policy.policy_revision,
        )
        ledger.register_scope(child, child_policy)
        scopes.append(child)
    barrier = Barrier(len(scopes))

    def reserve(index: int) -> BudgetReservation | BudgetDecision:
        barrier.wait()
        return ledger.reserve(
            scopes[index],
            requested,
            f"operation-{index}",
            f"key-{index}",
        )

    with ThreadPoolExecutor(max_workers=len(scopes)) as pool:
        results = list(pool.map(reserve, range(len(scopes))))

    admitted = [item for item in results if isinstance(item, BudgetReservation)]
    denied = [item for item in results if isinstance(item, BudgetDecision)]
    assert len(admitted) == min(caller_count, 5)
    assert len(denied) == max(0, caller_count - 5)
    root_reserved = ledger.view(root).usage.reserved
    assert root_reserved.llm_calls <= (limits.llm_calls or 2**63 - 1)
    assert root_reserved.input_tokens <= (limits.input_tokens or 2**63 - 1)
    assert root_reserved.estimated_cost_usd <= (
        limits.estimated_cost_usd or Decimal("1000000000000")
    )
