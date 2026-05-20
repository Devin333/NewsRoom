from __future__ import annotations

from framework.agent.models import AgentLoopMetrics, AgentLoopResult, AgentLoopStatus
from framework.specs import StepSpec, StepType
from framework.workflow.buffer import DataBuffer
from framework.workflow.runners._step_runner_impl import AgentLoopStepRunner


def test_agent_loop_step_outcome_exposes_trajectory_summary() -> None:
    runner = AgentLoopStepRunner(
        agent_runner=_FakeAgentRunner(),
        agent_registry={"agent-1": object()},
    )
    runner.configure_run_context(artifact_manager=object(), run_id="run-1")
    step = StepSpec(
        step_id="agent_step",
        step_type=StepType.AGENT_LOOP,
        implementation="agent-1",
        write_keys=[
            "agent_loop_result",
            "agent_loop_metrics",
            "agent_loop_trace",
            "agent_loop_trajectory",
            "agent_loop_termination_reason",
            "agent_loop_max_steps_reached",
        ],
    )
    buffer = DataBuffer({"input": "x"}).scope(step.read_keys, step.write_keys, step_id=step.step_id)

    outcome = runner.run(step, buffer)

    assert outcome.status.value == "succeeded"
    assert outcome.outputs["agent_loop_termination_reason"] == "final_output_accepted"
    assert outcome.outputs["agent_loop_max_steps_reached"] is False
    assert outcome.outputs["agent_loop_trajectory"][0]["parsed_action"]["action_type"] == "final_output"
    assert outcome.metrics["trajectory_summary"]["iteration_count"] == 1
    assert outcome.metrics["trajectory_summary"]["termination_reason"] == "final_output_accepted"
    assert outcome.trace_events[0]["event_type"] == "agent_loop_trajectory"


class _FakeAgentRunner:
    def run(self, agent: object, inputs: dict[str, object], **kwargs: object) -> AgentLoopResult:
        _ = agent, inputs, kwargs
        trajectory = [
            {
                "iteration": 1,
                "trace_id": "trace-1",
                "span_id": "span-1",
                "parsed_action": {"action_type": "final_output", "output_keys": ["summary"]},
                "tool_calls": [],
                "observations": [],
                "memory_ops": [],
                "decision": "accept",
                "duration_ms": 1.0,
            }
        ]
        return AgentLoopResult(
            success=True,
            status=AgentLoopStatus.ACCEPTED,
            output={"summary": "ok"},
            iterations=1,
            metrics=AgentLoopMetrics(iterations=1),
            trace={"agent_id": "agent-1", "trace_id": "trace-1", "summary": {}},
            trajectory=trajectory,
            termination_reason="final_output_accepted",
            max_steps_reached=False,
            trace_id="trace-1",
            trace_ref="agent_loop_trace",
        )
