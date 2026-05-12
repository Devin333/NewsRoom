from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from core.framework.workers.approval import ApprovalRequest, ApprovalStore


def register_control_tools(
    registry: ToolRegistry,
    *,
    approval_store: ApprovalStore | None = None,
    run_id: str | None = None,
) -> None:
    registry.register(
        ToolDefinition(
            name="control.set_output",
            description="Submit a final output candidate for the current agent loop.",
            input_schema={
                "required": ["output"],
                "properties": {
                    "output": {"type": "object"},
                    "reason": {"type": "string"},
                },
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
            lambda args: _request_human_review(
                args,
                approval_store=approval_store,
                run_id=run_id,
            ),
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
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                        },
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
            lambda args: _escalate(
                args,
                approval_store=approval_store,
                run_id=run_id,
            ),
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


def _request_human_review(
    args: dict[str, Any],
    *,
    approval_store: ApprovalStore,
    run_id: str | None,
) -> dict[str, Any]:
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


def _escalate(
    args: dict[str, Any],
    *,
    approval_store: ApprovalStore,
    run_id: str | None,
) -> dict[str, Any]:
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
    severity = str(args.get("severity") or "high")
    request = ApprovalRequest(
        requested_action=f"escalate:{escalation_type}",
        risk_level=severity,
        reason=reason,
        payload=dict(payload),
        task_id=args.get("task_id"),
        run_id=run_id,
        requested_by=args.get("requested_by"),
        metadata={
            **dict(metadata),
            "control_tool": "control.escalate",
            "escalation_type": escalation_type,
        },
    )
    stored = approval_store.upsert_approval(request)
    return {
        "control_action": "escalate",
        "escalation_type": escalation_type,
        "approval_id": stored.approval_id,
        "approval": stored.to_dict(),
    }
