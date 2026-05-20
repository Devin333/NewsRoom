from framework.agent.harness import AgentHarness, AgentHarnessScenario
from framework.agent.models import AgentLoopResult, AgentSpec


class _Runner:
    def run_spec(self, spec, inputs, *, run_id=None):
        return AgentLoopResult.success_result(spec.agent_id, {"answer": inputs["question"]})


def test_harness_runs_scenario_and_evaluates_trace() -> None:
    scenario = AgentHarnessScenario(
        scenario_id="scenario-1",
        spec=AgentSpec(agent_id="analyst", name="Analyst", instructions="answer"),
        inputs={"question": "ok"},
        expected={"status": "succeeded", "output_keys": ["answer"]},
    )

    trace = AgentHarness(_Runner()).run_scenario(scenario)

    assert trace.success is True
    assert trace.to_dict()["evaluation"]["passed"] is True
