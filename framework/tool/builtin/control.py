from __future__ import annotations

from typing import Any, Protocol

from framework.tool.governance.redaction import reject_sensitive_mapping_keys
from framework.tool.governance.approval import ApprovalRequest
from framework.tool.models.definition import ToolDefinition
from framework.tool.registry.registry import ToolRegistry
from framework.workers.models.task import DEFAULT_TASK_QUEUE, Task


class TaskQueueWriter(Protocol):
    def enqueue(self, task: Any) -> Any: ...


def register_control_tools(
    registry: ToolRegistry,
    *,
    approval_store: Any | None = None,
    task_queue: TaskQueueWriter | None = None,
    run_id: str | None = None,
) -> None:
    registry.register(
        ToolDefinition(
            name="control.set_output",
            description="Submit a final output candidate for the current agent loop.",
            input_schema={
                "required": ["output"],
                "properties": {"output": {"type": "object"}, "reason": {"type": "string"}},
                "additionalProperties": False,
            },
            side_effect="none",
            concurrency_safe=False,
        ),
        _set_output,
    )
    registry.register(
        ToolDefinition(
            name="control.report_progress",
            description="Report structured progress for the current agent loop.",
            input_schema={
                "required": ["message"],
                "properties": {
                    "message": {"type": "string"},
                    "percent": {"type": "number"},
                    "metadata": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            concurrency_safe=True,
        ),
        _report_progress,
    )
    if approval_store is not None:
        registry.register(
            ToolDefinition(
                name="control.request_human_review",
                description="Create a human review approval request.",
                input_schema={
                    "required": ["requested_action", "reason"],
                    "properties": {
                        "requested_action": {"type": "string"},
                        "reason": {"type": "string"},
                        "risk_level": {"type": "string"},
                        "payload": {"type": "object"},
                        "task_id": {"type": "string"},
                        "requested_by": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                concurrency_safe=False,
                metadata={"writes_approval_request": True},
            ),
            lambda args: _request_human_review(args, approval_store=approval_store, run_id=run_id),
        )
        registry.register(
            ToolDefinition(
                name="control.escalate",
                description="Create an escalation request for human handling.",
                input_schema={
                    "required": ["escalation_type", "reason"],
                    "properties": {
                        "escalation_type": {"type": "string"},
                        "reason": {"type": "string"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                        "payload": {"type": "object"},
                        "task_id": {"type": "string"},
                        "requested_by": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                side_effect="none",
                concurrency_safe=False,
                metadata={"writes_escalation_request": True},
            ),
            lambda args: _escalate(args, approval_store=approval_store, run_id=run_id),
        )
    if task_queue is not None:
        registry.register(
            ToolDefinition(
                name="control.delegate_to_subagent",
                description="Delegate work to a worker queue for subagent-style execution.",
                input_schema={
                    "required": ["task_type"],
                    "properties": {
                        "task_type": {"type": "string"},
                        "payload": {"type": "object"},
                        "queue_name": {"type": "string"},
                        "task_id": {"type": "string"},
                        "subagent_id": {"type": "string"},
                        "max_attempts": {"type": "integer"},
                        "metadata": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                side_effect="writes_external_state",
                requires_approval=True,
                concurrency_safe=False,
                metadata={"writes_worker_task": True},
            ),
            lambda args: _delegate_to_subagent(args, task_queue=task_queue, run_id=run_id),
        )


def _set_output(args: dict[str, Any]) -> dict[str, Any]:
    output = args["output"]
    if not isinstance(output, dict):
        raise ValueError("output must be an object")
    reason = args.get("reason")
    return {
        "control_action": "set_output",
        "output": dict(output),
        "reason": str(reason) if reason is not None else None,
    }


def _report_progress(args: dict[str, Any]) -> dict[str, Any]:
    percent = args.get("percent")
    if percent is not None:
        percent = float(percent)
        if percent < 0.0 or percent > 100.0:
            raise ValueError("percent must be between 0 and 100")
    metadata = args.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    return {
        "control_action": "report_progress",
        "message": str(args["message"]),
        "percent": percent,
        "metadata": dict(metadata),
    }


def _request_human_review(args: dict[str, Any], *, approval_store: Any, run_id: str | None) -> dict[str, Any]:
    requested_action = str(args["requested_action"]).strip()
    if not requested_action:
        raise ValueError("requested_action is required")
    reason = str(args["reason"]).strip()
    if not reason:
        raise ValueError("reason is required")
    payload = args.get("payload") or {}
    metadata = args.get("metadata") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    reject_sensitive_mapping_keys(payload, label="payload")
    reject_sensitive_mapping_keys(metadata, label="metadata")
    request = ApprovalRequest(
        requested_action=requested_action,
        risk_level=str(args.get("risk_level") or "medium"),
        reason=reason,
        payload=dict(payload),
        task_id=args.get("task_id"),
        run_id=run_id,
        requested_by=args.get("requested_by"),
        metadata={**dict(metadata), "control_tool": "control.request_human_review"},
    )
    stored = approval_store.upsert_approval(request)
    return {
        "control_action": "request_human_review",
        "approval_id": stored.approval_id,
        "approval": stored.to_dict(),
    }


def _escalate(args: dict[str, Any], *, approval_store: Any, run_id: str | None) -> dict[str, Any]:
    escalation_type = str(args["escalation_type"]).strip()
    if not escalation_type:
        raise ValueError("escalation_type is required")
    reason = str(args["reason"]).strip()
    if not reason:
        raise ValueError("reason is required")
    payload = args.get("payload") or {}
    metadata = args.get("metadata") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    reject_sensitive_mapping_keys(payload, label="payload")
    reject_sensitive_mapping_keys(metadata, label="metadata")
    severity = str(args.get("severity") or "high")
    request = ApprovalRequest(
        requested_action=f"escalate:{escalation_type}",
        risk_level=severity,
        reason=reason,
        payload=dict(payload),
        task_id=args.get("task_id"),
        run_id=run_id,
        requested_by=args.get("requested_by"),
        metadata={**dict(metadata), "control_tool": "control.escalate", "escalation_type": escalation_type},
    )
    stored = approval_store.upsert_approval(request)
    return {
        "control_action": "escalate",
        "escalation_type": escalation_type,
        "approval_id": stored.approval_id,
        "approval": stored.to_dict(),
    }


def _delegate_to_subagent(args: dict[str, Any], *, task_queue: TaskQueueWriter, run_id: str | None) -> dict[str, Any]:
    task_type = str(args["task_type"]).strip()
    if not task_type:
        raise ValueError("task_type is required")
    payload = args.get("payload") or {}
    metadata = args.get("metadata") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    queue_name = str(args.get("queue_name") or DEFAULT_TASK_QUEUE).strip()
    if not queue_name:
        raise ValueError("queue_name is required")
    max_attempts = int(args.get("max_attempts") or 3)
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    task_id = _optional_text(args.get("task_id"))
    subagent_id = _optional_text(args.get("subagent_id"))
    task_metadata = {**dict(metadata), "control_tool": "control.delegate_to_subagent"}
    if run_id is not None:
        task_metadata["run_id"] = run_id
    if subagent_id is not None:
        task_metadata["subagent_id"] = subagent_id
    task_kwargs: dict[str, Any] = {
        "task_type": task_type,
        "payload": dict(payload),
        "queue_name": queue_name,
        "max_attempts": max_attempts,
        "metadata": task_metadata,
    }
    if task_id is not None:
        task_kwargs["task_id"] = task_id
    task = Task(**task_kwargs)
    message_id = _normalize_message_id(task_queue.enqueue(task))
    return {
        "control_action": "delegate_to_subagent",
        "task_id": task.task_id,
        "task_type": task.task_type,
        "queue_name": task.queue_name,
        "message_id": message_id,
        "task": task.to_dict(),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_message_id(message_id: Any) -> str | None:
    if message_id is None:
        return None
    nested_message_id = getattr(message_id, "message_id", None)
    if nested_message_id is not None:
        return _normalize_message_id(nested_message_id)
    if isinstance(message_id, bytes):
        return message_id.decode("utf-8")
    return str(message_id)
