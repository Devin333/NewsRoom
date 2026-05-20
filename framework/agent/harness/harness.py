from __future__ import annotations

from collections.abc import Iterable

from framework.agent.harness.evaluator import AgentHarnessEvaluator
from framework.agent.harness.scenario import AgentHarnessScenario
from framework.agent.harness.trace import AgentHarnessTrace
from framework.agent.loop.runner import AgentRunner


class AgentHarness:
    def __init__(
        self,
        runner: AgentRunner,
        *,
        evaluator: AgentHarnessEvaluator | None = None,
    ) -> None:
        self._runner = runner
        self._evaluator = evaluator or AgentHarnessEvaluator()

    def run_scenario(self, scenario: AgentHarnessScenario) -> AgentHarnessTrace:
        result = self._runner.run_spec(scenario.spec, scenario.inputs, run_id=scenario.scenario_id)
        evaluation = self._evaluator.evaluate(result, scenario)
        return AgentHarnessTrace(
            scenario_id=scenario.scenario_id,
            result=result,
            evaluation=evaluation,
            metadata=dict(scenario.metadata),
        )

    def run_many(self, scenarios: Iterable[AgentHarnessScenario]) -> list[AgentHarnessTrace]:
        return [self.run_scenario(scenario) for scenario in scenarios]
