from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


def register_memory_index_tools(
    registry: ToolRegistry,
    *,
    ingestion_service: Any,
) -> None:
    registry.register(
        ToolDefinition(
            name="memory.index",
            description="Deprecated: index report or evidence payloads into vector memory.",
            input_schema={
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string"},
                    "report": {"type": "object"},
                    "evidence_bundle": {"type": "object"},
                    "run_output": {"type": "object"},
                    "report_id": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="writes_external_state",
            concurrency_safe=False,
            max_result_bytes=100_000,
            metadata={
                "deprecated": True,
                "deprecated_replacement": "memory.write",
                "writes_vector_memory": True,
            },
        ),
        lambda args: _index_memory(args, ingestion_service=ingestion_service),
    )


def _index_memory(
    args: dict[str, Any],
    *,
    ingestion_service: Any,
) -> dict[str, Any]:
    run_id = str(args["run_id"]).strip()
    if not run_id:
        raise ValueError("run_id is required")

    output: dict[str, Any] = {}
    indexed_inputs: list[str] = []
    if args.get("run_output") is not None:
        run_output = args["run_output"]
        if not isinstance(run_output, dict):
            raise ValueError("run_output must be an object")
        output.update(run_output)
        indexed_inputs.append("run_output")
    if args.get("report") is not None:
        output["final_report"] = args["report"]
        indexed_inputs.append("report")
    if args.get("evidence_bundle") is not None:
        output["evidence_bundle"] = args["evidence_bundle"]
        indexed_inputs.append("evidence_bundle")

    if "final_report" not in output and "evidence_bundle" not in output:
        raise ValueError("report, evidence_bundle, or run_output is required")

    result = ingestion_service.ingest_run_output(
        output,
        run_id=run_id,
        report_id=_optional_string(args.get("report_id")),
        topic=_optional_string(args.get("topic")),
    )
    return {
        "run_id": run_id,
        "report_id": _optional_string(args.get("report_id")),
        "topic": _optional_string(args.get("topic")),
        "indexed_inputs": indexed_inputs,
        **result.to_dict(),
    }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
