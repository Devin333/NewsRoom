from __future__ import annotations

from typing import Any

from framework.workflow.runners.skill.accessors import (
    buffer_write,
    output_buffer_key,
    output_key,
    result_key,
    step_id,
    store_full_result,
    store_output,
)
from framework.workflow.runners.skill.result_mapper import skill_output


def write_skill_outputs(
    step: Any,
    buffer: Any,
    skill_result: Any,
    *,
    runner_id: str,
) -> dict[str, Any]:
    resolved_step_id = step_id(step)
    output = skill_output(skill_result)
    outputs: dict[str, Any] = {}

    if store_full_result(step):
        key = result_key(step)
        buffer_write(
            buffer,
            key,
            skill_result,
            lineage={"step_id": resolved_step_id, "runner_id": runner_id},
        )
        outputs[key] = skill_result
    if store_output(step):
        key = output_buffer_key(step)
        buffer_write(
            buffer,
            key,
            output,
            lineage={"step_id": resolved_step_id, "runner_id": runner_id},
        )
        outputs[key] = output
    resolved_output_key = output_key(step)
    if resolved_output_key:
        buffer_write(
            buffer,
            resolved_output_key,
            output,
            lineage={"step_id": resolved_step_id, "runner_id": runner_id},
        )
        outputs[resolved_output_key] = output
    return outputs


__all__ = [
    "write_skill_outputs",
]
