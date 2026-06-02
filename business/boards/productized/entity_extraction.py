from __future__ import annotations

from typing import Any

from business.boards.productized.models import ProductizedRunState
from business.boards.productized.payloads import signal_item_payload
from business.foundation import Signal
from business.foundation.skills import BusinessSkillRuntime


class ProductizedEntityExtractionService:
    def __init__(self, *, skill_runtime: BusinessSkillRuntime) -> None:
        self.skill_runtime = skill_runtime

    def extract(
        self,
        *,
        request: dict[str, Any],
        board_signals: list[Signal],
        productized_run: ProductizedRunState,
    ) -> dict[str, Any]:
        skill_traces = list(productized_run.skill_traces)
        extracted = []
        for signal in board_signals:
            result = self.skill_runtime.run_entity_extraction(
                signal_item_payload(signal),
                run_id=productized_run.run_id,
                fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
            )
            extracted.append({"signal_id": signal.signal_id, **result.output})
            skill_traces.append(result.to_dict())
        run_state = productized_run.with_updates(
            extracted_entities=extracted,
            skill_traces=skill_traces,
        )
        return {"extracted_entities": extracted, "skill_traces": skill_traces, "productized_run": run_state}


__all__ = ["ProductizedEntityExtractionService"]
