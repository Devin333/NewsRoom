from __future__ import annotations

from typing import Any

from business.boards.productized.context import analysis_context_from_request, run_id_from_request
from business.boards.productized.models import ProductizedRunState
from business.boards.productized.payloads import (
    source_reliability_content_payload,
    source_reliability_source_payload,
)
from business.foundation import BoardType
from business.foundation.skills import BusinessSkillRuntime
from business.layers.signal import SignalPipeline


class ProductizedSignalPreparationService:
    def __init__(
        self,
        *,
        board_type: BoardType,
        skill_runtime: BusinessSkillRuntime,
        improvement_service: Any,
        signal_pipeline: SignalPipeline | None = None,
    ) -> None:
        self.board_type = board_type
        self.skill_runtime = skill_runtime
        self.improvement_service = improvement_service
        self.signal_pipeline = signal_pipeline or SignalPipeline()

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        run_id = run_id_from_request(request, self.board_type)
        context = analysis_context_from_request(self.board_type, request, run_id)
        raw_signals = list(request.get("signals") or [])
        pipeline_result = self.signal_pipeline.coerce_signals(
            raw_signals,
            context=context,
            board_type=self.board_type,
            topic=request.get("topic"),
        )
        skill_traces: list[dict[str, Any]] = []
        reliability_results = []
        for signal in pipeline_result.signals:
            source_result = self.skill_runtime.run_source_reliability(
                source_reliability_source_payload(signal),
                source_reliability_content_payload(signal),
                run_id=run_id,
                fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
            )
            reliability_results.append(source_result.output)
            skill_traces.append(source_result.to_dict())
        improvement_context = self.improvement_service.apply_approved_policy_experiments(
            run_id=run_id,
            board_type=self.board_type.value,
        )
        policy_experiment_application_context = improvement_context.to_application_dict()
        run_state = ProductizedRunState.from_request(
            request=request,
            board_type=self.board_type,
            run_id=run_id,
        ).with_updates(
            skill_traces=skill_traces,
            source_reliability_results=reliability_results,
            improvement_context=policy_experiment_application_context,
        )
        return {
            "context": context,
            "raw_signals": raw_signals,
            "prepared_signals": pipeline_result.signals,
            "source_reliability_results": reliability_results,
            "skill_traces": skill_traces,
            "policy_experiment_application_context": policy_experiment_application_context,
            "improvement_context": policy_experiment_application_context,
            "productized_run": run_state,
        }


__all__ = ["ProductizedSignalPreparationService"]
