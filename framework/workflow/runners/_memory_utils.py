from __future__ import annotations

from typing import Any

from framework.specs import StepSpec
from framework.workflow.buffer import StepScopedDataBufferView
from framework.workflow.runners.base import StepExecutionError
from framework.workflow.runners.memory_models import (
    MemoryConsolidationRequest,
    MemoryQuery,
)


def memory_query_from_step(
    step: StepSpec, buffer: StepScopedDataBufferView
) -> MemoryQuery:
    raw_query = step.metadata.get("query")
    if raw_query is None and step.metadata.get("query_key") is not None:
        raw_query = buffer.read(str(step.metadata["query_key"]))
    if raw_query is None:
        raise StepExecutionError(f"memory_recall step {step.step_id} requires a query")

    if isinstance(raw_query, dict):
        payload: dict[str, Any] = dict(raw_query)
    else:
        payload = {"query": str(raw_query)}

    for key in (
        "scopes",
        "kinds",
        "filters",
        "limit",
        "min_score",
        "max_context_tokens",
    ):
        if key in step.metadata:
            payload[key] = step.metadata[key]

    if step.metadata.get("filters_key") is not None:
        raw_filters = buffer.read(str(step.metadata["filters_key"]))
        if not isinstance(raw_filters, dict):
            raise StepExecutionError(
                f"memory_recall step {step.step_id} filters_key must reference an object"
            )
        existing_filters = payload.get("filters")
        payload["filters"] = {
            **dict(raw_filters),
            **(dict(existing_filters) if isinstance(existing_filters, dict) else {}),
        }

    return MemoryQuery.from_dict(payload)


def memory_records_from_step(step: StepSpec, buffer: StepScopedDataBufferView) -> list[Any]:
    raw_records = step.metadata.get("records")
    if raw_records is None and step.metadata.get("records_key") is not None:
        raw_records = buffer.read(str(step.metadata["records_key"]))
    if raw_records is None:
        raise StepExecutionError(f"memory_write step {step.step_id} requires records")
    if isinstance(raw_records, dict):
        nested_records = raw_records.get("records")
        if isinstance(nested_records, list):
            return list(nested_records)
        return [dict(raw_records)]
    if isinstance(raw_records, (list, tuple)):
        return list(raw_records)
    raise StepExecutionError(
        f"memory_write step {step.step_id} records must be an object or list of objects"
    )


def memory_actor_from_step(step: StepSpec, buffer: StepScopedDataBufferView) -> str:
    if step.metadata.get("actor_key") is not None:
        actor = buffer.read(str(step.metadata["actor_key"]))
    else:
        actor = (
            step.metadata.get("actor")
            or step.metadata.get("requested_by")
            or step.step_id
        )
    return str(actor or step.step_id)


def memory_consolidation_request_from_step(
    step: StepSpec,
    buffer: StepScopedDataBufferView,
    *,
    run_id: str | None,
) -> MemoryConsolidationRequest:
    raw_memory_ids = step.metadata.get("memory_ids")
    if raw_memory_ids is None and step.metadata.get("memory_ids_key") is not None:
        raw_memory_ids = buffer.read(str(step.metadata["memory_ids_key"]))
    raw_query = step.metadata.get("query")
    if raw_query is None and step.metadata.get("query_key") is not None:
        raw_query = buffer.read(str(step.metadata["query_key"]))
    raw_filters = step.metadata.get("filters")
    if raw_filters is None and step.metadata.get("filters_key") is not None:
        raw_filters = buffer.read(str(step.metadata["filters_key"]))

    memory_ids = coerce_memory_ids_for_consolidation(raw_memory_ids, step=step)
    query = coerce_query_for_consolidation(raw_query, step=step)
    filters = coerce_filters_for_consolidation(raw_filters, step=step)
    payload: dict[str, Any] = {
        "memory_ids": memory_ids,
        "filters": filters,
        "actor": memory_actor_from_step(step, buffer),
        "run_id": run_id or step.metadata.get("run_id"),
        "reason": step.metadata.get("reason"),
    }
    if query is not None:
        payload["query"] = query.to_dict()
    return MemoryConsolidationRequest.from_dict(payload)


def coerce_memory_ids_for_consolidation(value: Any, *, step: StepSpec) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    raise StepExecutionError(
        f"memory_consolidate step {step.step_id} memory_ids must be a string or list"
    )


def coerce_query_for_consolidation(value: Any, *, step: StepSpec) -> MemoryQuery | None:
    if value is None:
        return None
    if isinstance(value, MemoryQuery):
        return value
    if isinstance(value, dict):
        return MemoryQuery.from_dict(dict(value))
    return MemoryQuery(query=str(value))


def coerce_filters_for_consolidation(value: Any, *, step: StepSpec) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StepExecutionError(
            f"memory_consolidate step {step.step_id} filters must be an object"
        )
    return dict(value)


def memory_recall_result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or "memory_recall_result")


def memory_context_key(step: StepSpec) -> str:
    return str(step.metadata.get("context_key") or "memory_context")


def memory_records_key(step: StepSpec) -> str:
    return str(
        step.metadata.get("records_key")
        or step.metadata.get("records_output_key")
        or "memory_records"
    )


def memory_write_result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or "memory_write_result")


def memory_consolidate_result_key(step: StepSpec) -> str:
    return str(step.metadata.get("result_key") or "memory_consolidate_result")
