from core.framework.tools import REDACTED_VALUE, ToolApprovalRequest, ToolCall


def test_tool_approval_request_serializes_redacted_tool_call() -> None:
    request = ToolApprovalRequest(
        approval_id="tool-appr-1",
        tool_call=ToolCall(
            tool_name="report.publish",
            arguments={"report_id": "report-1", "authorization": "Bearer secret12345"},
            requested_by_agent_id="publisher",
            call_id="call-1",
        ),
        tool_name="report.publish",
        side_effect="publishing",
        reason="publish requires approval",
        risk_level="high",
        run_id="run-1",
    )

    payload = request.to_dict()
    worker_request = request.to_worker_approval_request()

    assert payload["agent_id"] == "publisher"
    assert payload["tool_call"]["arguments"]["authorization"] == REDACTED_VALUE
    assert worker_request.approval_id == "tool-appr-1"
    assert worker_request.requested_action == "tool:report.publish"
    assert worker_request.payload["tool_approval"]["tool_name"] == "report.publish"
