from __future__ import annotations

from typing import Any

from business.boards.productized.models import ProductizedRunState
from business.boards.productized.payloads import signal_item_payload
from business.foundation import Signal
from business.foundation.skills import BusinessSkillRuntime


class ProductizedDeduplicationService:
    def __init__(self, *, skill_runtime: BusinessSkillRuntime) -> None:
        self.skill_runtime = skill_runtime

    def deduplicate(
        self,
        *,
        request: dict[str, Any],
        board_signals: list[Signal],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        items = [signal_item_payload(signal) for signal in board_signals]
        result = self.skill_runtime.run_event_deduplication(
            items,
            run_id=productized_run.run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(result.to_dict())
        run_state = productized_run.with_updates(
            deduplication_result=result.output,
            skill_traces=skill_traces,
        )
        return {
            "deduplicated_signals": board_signals,
            "deduplication_result": result.output,
            "skill_traces": skill_traces,
            "productized_run": run_state,
        }


__all__ = ["ProductizedDeduplicationService"]
