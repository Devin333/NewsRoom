from __future__ import annotations

from framework.agent.models import AgentLoopMetrics, AgentLoopResult, AgentLoopStatus
from framework.specs import StepSpec, StepType
from framework.workflow.buffer import DataBuffer
from framework.workflow.runners.agent_loop import AgentLoopStepRunner


def test_agent_loop_step_outcome_exposes_trajectory_summary() -> None:
    agent_runner = _FakeAgentRunner()
    runner = AgentLoopStepRunner(
        agent_runner=agent_runner,
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
    buffer = DataBuffer({"input": "x"}).scope(
        step.read_keys,
        step.write_keys,
        step_id=step.step_id,
    )

    outcome = runner.run(step, buffer)

    assert outcome.status.value == "succeeded"
    assert outcome.outputs["agent_loop_termination_reason"] == "final_output_accepted"
    assert outcome.outputs["agent_loop_max_steps_reached"] is False
    assert (
        outcome.outputs["agent_loop_trajectory"][0]["parsed_action"]["action_type"]
        == "final_output"
    )
    assert outcome.metrics["trajectory_summary"]["iteration_count"] == 1
    assert outcome.metrics["trajectory_summary"]["termination_reason"] == "final_output_accepted"
    assert outcome.trace_events[0]["event_type"] == "agent_loop_trajectory"
    assert outcome.trace_events[1]["event_type"] == "structured_output_validation_accepted"
    assert "raw-secret" not in str(outcome.trace_events)


def test_agent_loop_step_runner_passes_present_optional_reads() -> None:
    agent_runner = _FakeAgentRunner()
    runner = AgentLoopStepRunner(
        agent_runner=agent_runner,
        agent_registry={"agent-1": object()},
    )
    runner.configure_run_context(artifact_manager=object(), run_id="run-1")
    step = StepSpec(
        step_id="agent_step",
        step_type=StepType.AGENT_LOOP,
        implementation="agent-1",
        read_keys=["required_input"],
        write_keys=[
            "agent_loop_result",
            "agent_loop_metrics",
            "agent_loop_trace",
            "agent_loop_trajectory",
            "agent_loop_termination_reason",
            "agent_loop_max_steps_reached",
        ],
        metadata={"optional_read_keys": ["optional_input", "missing_optional"]},
    )
    buffer = DataBuffer(
        {"required_input": "required", "optional_input": "optional"}
    ).scope(
        step.read_keys,
        step.write_keys,
        optional_read_keys=step.metadata["optional_read_keys"],
        step_id=step.step_id,
    )

    outcome = runner.run(step, buffer)

    assert outcome.status.value == "succeeded"
    assert agent_runner.last_inputs == {
        "required_input": "required",
        "optional_input": "optional",
    }


def test_agent_loop_step_runner_projects_declared_output_aliases() -> None:
    agent_runner = _FakeAgentRunner()
    runner = AgentLoopStepRunner(
        agent_runner=agent_runner,
        agent_registry={"agent-1": object()},
    )
    runner.configure_run_context(artifact_manager=object(), run_id="run-1")
    step = StepSpec(
        step_id="agent_step",
        step_type=StepType.AGENT_LOOP,
        implementation="agent-1",
        write_keys=[
            "agent_loop_result",
            "agent.loop.result",
            "agent_loop_metrics",
            "agent.loop.metrics",
        ],
        metadata={
            "output_aliases": {
                "agent_loop_result": "agent.loop.result",
                "agent_loop_metrics": "agent.loop.metrics",
            }
        },
    )
    buffer = DataBuffer({"input": "x"}).scope(
        step.read_keys,
        step.write_keys,
        step_id=step.step_id,
    )

    outcome = runner.run(step, buffer)

    assert outcome.status.value == "succeeded"
    assert outcome.outputs["agent.loop.result"] is outcome.outputs["agent_loop_result"]
    assert outcome.outputs["agent.loop.metrics"] is outcome.outputs["agent_loop_metrics"]


class _FakeAgentRunner:
    def __init__(self) -> None:
        self.last_inputs: dict[str, object] | None = None

    def run(self, agent: object, inputs: dict[str, object], **kwargs: object) -> AgentLoopResult:
        _ = agent, kwargs
        self.last_inputs = dict(inputs)
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
            events=[
                {
                    "event_type": "structured_output_validation_accepted",
                    "agent_id": "agent-1",
                    "iteration": 1,
                    "contract": {"schema_digest": "sha256:" + "a" * 64},
                    "response_fingerprint": "sha256:" + "b" * 64,
                    "budget_disposition": "accepted_for_domain_gates",
                },
                {
                    "event_type": "llm_call",
                    "raw_output": "raw-secret",
                },
            ],
            trace={"agent_id": "agent-1", "trace_id": "trace-1", "summary": {}},
            trajectory=trajectory,
            termination_reason="final_output_accepted",
            max_steps_reached=False,
            trace_id="trace-1",
            trace_ref="agent_loop_trace",
        )
