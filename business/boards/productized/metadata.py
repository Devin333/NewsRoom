from __future__ import annotations

from typing import Any


class ProductizedRunStateMetadataProjector:
    def runtime_metadata(self, run_state: Any) -> dict[str, Any]:
        return {
            "skill_trace_metadata": list(_field(run_state, "skill_traces", [])),
            "extracted_entities": list(_field(run_state, "extracted_entities", [])),
            "evidence_items": list(_field(run_state, "evidence_items", [])),
            "trend_analysis": dict(_field(run_state, "trend_analysis", {})),
            "deduplication_result": dict(_field(run_state, "deduplication_result", {})),
            "improvement_context": dict(_field(run_state, "improvement_context", {})),
            "productized_run_state": _run_state_payload(run_state),
        }

    def board_output_metadata(self, run_state: Any) -> dict[str, Any]:
        return {
            "skill_trace_metadata": list(_field(run_state, "skill_traces", [])),
            "improvement_context": dict(_field(run_state, "improvement_context", {})),
            "trend_analysis": dict(_field(run_state, "trend_analysis", {})),
            "productized_run_state": _run_state_payload(run_state),
        }


def _field(run_state: Any, field_name: str, default: Any) -> Any:
    if isinstance(run_state, dict):
        return run_state.get(field_name, default)
    return getattr(run_state, field_name, default)


def _run_state_payload(run_state: Any) -> dict[str, Any]:
    if isinstance(run_state, dict):
        return dict(run_state)
    to_dict = getattr(run_state, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    model_dump = getattr(run_state, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json"))
    return {}


__all__ = ["ProductizedRunStateMetadataProjector"]
