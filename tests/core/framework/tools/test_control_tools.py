from core.framework.tools import (
    ToolCall,
    ToolExecutor,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
    register_control_tools,
)
from core.framework.workers import InMemoryApprovalStore


def test_control_set_output_tool_returns_final_output_payload() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.set_output",
            arguments={
                "output": {"analysis_result": {"summary": "ok"}},
                "reason": "complete",
            },
        ),
        ToolPolicy(allowed_tools=["control.set_output"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "control_action": "set_output",
        "output": {"analysis_result": {"summary": "ok"}},
        "reason": "complete",
    }


def test_control_report_progress_tool_returns_structured_progress() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.report_progress",
            arguments={
                "message": "collected sources",
                "percent": 40,
                "metadata": {"source_count": 3},
            },
        ),
        ToolPolicy(allowed_tools=["control.report_progress"]),
    )

    assert observation.status == ToolStatus.SUCCEEDED
    assert observation.result.output == {
        "control_action": "report_progress",
        "message": "collected sources",
        "percent": 40.0,
        "metadata": {"source_count": 3},
    }


def test_control_report_progress_tool_rejects_invalid_percent() -> None:
    registry = ToolRegistry()
    register_control_tools(registry)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.report_progress",
            arguments={"message": "bad", "percent": 101},
        ),
        ToolPolicy(allowed_tools=["control.report_progress"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert "percent" in (observation.result.error_message or "")


def test_control_request_human_review_tool_persists_approval_request() -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(
        registry,
        approval_store=approval_store,
        run_id="run-approval",
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.request_human_review",
            arguments={
                "requested_action": "review:report",
                "reason": "editor review required",
                "risk_level": "high",
                "payload": {"report_id": "report-1"},
                "task_id": "task-1",
                "requested_by": "analyst",
                "metadata": {"stage": "editor"},
            },
        ),
        ToolPolicy(allowed_tools=["control.request_human_review"]),
    )

    approvals = approval_store.list_approvals()
    stored = approvals[0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert len(approvals) == 1
    assert observation.result.output["control_action"] == "request_human_review"
    assert observation.result.output["approval_id"] == stored.approval_id
    assert stored.requested_action == "review:report"
    assert stored.reason == "editor review required"
    assert stored.risk_level == "high"
    assert stored.payload == {"report_id": "report-1"}
    assert stored.task_id == "task-1"
    assert stored.run_id == "run-approval"
    assert stored.requested_by == "analyst"
    assert stored.metadata == {
        "stage": "editor",
        "control_tool": "control.request_human_review",
    }


def test_control_request_human_review_tool_rejects_secret_payload_keys_before_store() -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(registry, approval_store=approval_store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.request_human_review",
            arguments={
                "requested_action": "review:report",
                "reason": "editor review required",
                "payload": {"api_key": "hidden"},
            },
        ),
        ToolPolicy(allowed_tools=["control.request_human_review"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert approval_store.list_approvals() == []
    assert "payload key is not allowed" in (observation.result.error_message or "")


def test_control_escalate_tool_persists_escalation_request() -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(
        registry,
        approval_store=approval_store,
        run_id="run-escalation",
    )
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.escalate",
            arguments={
                "escalation_type": "source_outage",
                "reason": "all official sources failed",
                "severity": "critical",
                "payload": {"source_ids": ["official-ai"]},
                "task_id": "task-2",
                "requested_by": "collector",
                "metadata": {"stage": "source_collection"},
            },
        ),
        ToolPolicy(allowed_tools=["control.escalate"]),
    )

    approvals = approval_store.list_approvals()
    stored = approvals[0]

    assert observation.status == ToolStatus.SUCCEEDED
    assert len(approvals) == 1
    assert observation.result.output["control_action"] == "escalate"
    assert observation.result.output["approval_id"] == stored.approval_id
    assert stored.requested_action == "escalate:source_outage"
    assert stored.reason == "all official sources failed"
    assert stored.risk_level == "critical"
    assert stored.payload == {"source_ids": ["official-ai"]}
    assert stored.task_id == "task-2"
    assert stored.run_id == "run-escalation"
    assert stored.requested_by == "collector"
    assert stored.metadata == {
        "stage": "source_collection",
        "control_tool": "control.escalate",
        "escalation_type": "source_outage",
    }


def test_control_escalate_tool_rejects_secret_payload_keys_before_store() -> None:
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    register_control_tools(registry, approval_store=approval_store)
    executor = ToolExecutor(registry)

    observation = executor.execute(
        ToolCall(
            tool_name="control.escalate",
            arguments={
                "escalation_type": "publish_blocked",
                "reason": "operator token required",
                "payload": {"token": "hidden"},
            },
        ),
        ToolPolicy(allowed_tools=["control.escalate"]),
    )

    assert observation.status == ToolStatus.FAILED
    assert approval_store.list_approvals() == []
    assert "payload key is not allowed" in (observation.result.error_message or "")
