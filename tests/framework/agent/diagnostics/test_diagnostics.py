from framework.agent.diagnostics import AgentLoopDiagnosticsBuilder, metrics_from_trace
from framework.agent.models import AgentLoopDiagnosticSeverity, AgentLoopMetrics


def test_diagnostics_builder_and_metrics_from_trace() -> None:
    builder = AgentLoopDiagnosticsBuilder(agent_id="analyst")
    builder.add_issue("warning", "check this", AgentLoopDiagnosticSeverity.WARNING)
    diagnostics = builder.build()

    metrics = metrics_from_trace(
        {
            "summary": {
                "iterations": 2,
                "llm_calls": 1,
                "tool_calls": 1,
                "token_usage": {"input_tokens": 3, "output_tokens": 4},
            }
        }
    )

    assert diagnostics.healthy is False
    assert diagnostics.issues[0].code == "warning"
    assert isinstance(metrics, AgentLoopMetrics)
    assert metrics.token_usage.total_tokens == 7
