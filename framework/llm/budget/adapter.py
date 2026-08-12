from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from framework.governance.budget import (
    BudgetAmounts,
    BudgetDecision,
    BudgetLedger,
    BudgetReservation,
    BudgetSettlement,
    BudgetSettlementOutcome,
)
from framework.governance.budget.models import MAX_COST_USD
from framework.llm.budget.estimator import CostEstimator
from framework.llm.budget.pricing import ModelPricing
from framework.llm.models.usage import TokenUsage


@dataclass(frozen=True)
class LLMBudgetOperation:
    operation_id: str
    reservation: BudgetReservation

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "reservation": self.reservation.to_dict(),
        }


class LLMBudgetAdapter:
    """Translates LLM-specific usage and pricing into canonical ledger commands."""

    def __init__(
        self,
        ledger: BudgetLedger,
        *,
        scope: Any | None = None,
        estimator: CostEstimator | None = None,
    ) -> None:
        self.ledger = ledger
        self.scope = scope or ledger.root_scope
        self.estimator = estimator or CostEstimator()

    def reserve(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        input_tokens: int,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cached_input_tokens: int = 0,
        estimated_cost_usd: Decimal | str | float | int = Decimal("0"),
        count_request: bool = True,
    ) -> LLMBudgetOperation | BudgetDecision:
        requested = BudgetAmounts(
            llm_calls=1 if count_request else 0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_input_tokens=cached_input_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        result = self.ledger.reserve(
            self.scope,
            requested,
            operation_id,
            idempotency_key,
        )
        if isinstance(result, BudgetDecision):
            return result
        return LLMBudgetOperation(operation_id=operation_id, reservation=result)

    def reserve_prepared(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        input_tokens: int,
        output_tokens: int,
        pricing: ModelPricing | None,
        count_request: bool = True,
    ) -> LLMBudgetOperation | BudgetDecision:
        cost_ceiling = estimate_cost_ceiling(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pricing=pricing,
        )
        pricing_is_incomplete = pricing is None or (
            pricing.input_usd_per_1m_tokens is None
            or pricing.output_usd_per_1m_tokens is None
        )
        available_cost = self.ledger.view(self.scope).usage.available.estimated_cost_usd
        if pricing_is_incomplete and available_cost < MAX_COST_USD:
            cost_ceiling = available_cost
        return self.reserve(
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=input_tokens,
            estimated_cost_usd=cost_ceiling,
            count_request=count_request,
        )

    def settle(
        self,
        operation: LLMBudgetOperation,
        usage: TokenUsage,
        pricing: ModelPricing | None = None,
        *,
        estimated_cost_usd: float | Decimal | str | None = None,
        request_dispatched: bool = True,
        cache_hit: bool = False,
        outcome: BudgetSettlementOutcome | str = BudgetSettlementOutcome.SUCCEEDED,
        event_id: str | None = None,
        reason_code: str | None = None,
    ) -> BudgetSettlement:
        normalized = TokenUsage.from_any(usage)
        call_cost = (
            estimated_cost_usd
            if estimated_cost_usd is not None
            else self.estimator.estimate(normalized, pricing)
        )
        reservation = operation.reservation
        settlement = BudgetSettlement(
            reservation_id=reservation.reservation_id,
            operation_id=operation.operation_id,
            scope=reservation.scope,
            policy_digest=reservation.policy_digest,
            actual=BudgetAmounts(
                llm_calls=reservation.requested.llm_calls,
                input_tokens=normalized.input_tokens,
                output_tokens=normalized.output_tokens,
                reasoning_tokens=normalized.reasoning_tokens,
                cached_input_tokens=normalized.cached_input_tokens,
                estimated_cost_usd=call_cost,
            ),
            request_dispatched=request_dispatched,
            cache_hit=cache_hit,
            outcome=outcome,
            settled_event_id=event_id or self.next_identity("settlement"),
            reason_code=reason_code,
        )
        return self.ledger.settle(reservation.reservation_id, settlement)

    def settle_cache_hit(
        self,
        operation: LLMBudgetOperation,
        *,
        observed_usage: TokenUsage | None = None,
        event_id: str | None = None,
    ) -> BudgetSettlement:
        _ = TokenUsage.from_any(observed_usage)
        return self.settle(
            operation,
            TokenUsage(),
            estimated_cost_usd=0,
            request_dispatched=False,
            cache_hit=True,
            event_id=event_id,
        )

    def release(
        self,
        operation: LLMBudgetOperation,
        *,
        reason: str,
        request_dispatched: bool = False,
    ) -> BudgetSettlement:
        return self.ledger.release(
            operation.reservation.reservation_id,
            operation_id=operation.operation_id,
            reason=reason,
            request_dispatched=request_dispatched,
        )

    def mark_indeterminate(
        self,
        operation: LLMBudgetOperation,
        *,
        reason: str,
    ) -> BudgetSettlement:
        return self.ledger.mark_indeterminate(
            operation.reservation.reservation_id,
            operation_id=operation.operation_id,
            reason=reason,
        )

    def next_identity(self, prefix: str) -> str:
        return f"{prefix}:{self.scope.run_id}:{uuid4().hex}"


def estimate_cost_ceiling(
    *,
    input_tokens: int,
    output_tokens: int,
    pricing: ModelPricing | None,
) -> Decimal:
    if pricing is None:
        return Decimal("0")
    input_rate = Decimal(str(pricing.input_usd_per_1m_tokens or 0))
    output_rate = Decimal(str(pricing.output_usd_per_1m_tokens or 0))
    return (
        Decimal(input_tokens) * input_rate
        + Decimal(output_tokens) * output_rate
    ) / Decimal(1_000_000)


__all__ = ["LLMBudgetAdapter", "LLMBudgetOperation", "estimate_cost_ceiling"]
