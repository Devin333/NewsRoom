from __future__ import annotations

from pathlib import Path
from typing import Any

from framework import RunResult, WorkflowRunner
from framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from framework.workflow import FunctionStepRegistry
from framework.workflow.buffer.data_buffer import StepScopedDataBufferView
from business.boards.cross_board.workflows.daily_intelligence.artifact_publisher import (
    build_daily_intelligence_artifact_publishers,
)

PROFILE = "test-no-llm"
WORKFLOW_ID = "daily-intelligence-test-no-llm"
WORKFLOW_VERSION = "0.1.0"


def build_test_no_llm_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=WORKFLOW_ID,
        name="Daily Intelligence Test No LLM",
        version=WORKFLOW_VERSION,
        description="Deterministic function-only workflow for runtime regression tests.",
        start_step_id="plan",
        terminal_step_ids=["write_report"],
        steps=[
            StepSpec(
                step_id="plan",
                name="Build deterministic research plan",
                implementation="daily_test_no_llm.plan",
                read_keys=["request"],
                write_keys=["research_plan"],
                required_output_keys=["research_plan"],
            ),
            StepSpec(
                step_id="analyze",
                name="Build deterministic analysis result",
                implementation="daily_test_no_llm.analyze",
                read_keys=["research_plan"],
                write_keys=["analysis_result"],
                required_output_keys=["analysis_result"],
            ),
            StepSpec(
                step_id="write_report",
                name="Render deterministic report",
                implementation="daily_test_no_llm.write_report",
                read_keys=["request", "research_plan", "analysis_result"],
                write_keys=["final_report", "report_markdown"],
                required_output_keys=["final_report", "report_markdown"],
            ),
        ],
        edges=[
            EdgeSpec(edge_id="plan-to-analyze", source_step_id="plan", target_step_id="analyze"),
            EdgeSpec(
                edge_id="analyze-to-write-report",
                source_step_id="analyze",
                target_step_id="write_report",
            ),
        ],
        metadata={"profile": PROFILE, "product_path": False},
    )


def build_test_no_llm_registry() -> FunctionStepRegistry:
    registry = FunctionStepRegistry()
    registry.register("daily_test_no_llm.plan", _plan)
    registry.register("daily_test_no_llm.analyze", _analyze)
    registry.register("daily_test_no_llm.write_report", _write_report)
    return registry


def run_test_no_llm(
    *,
    artifact_root: str | Path,
    request: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> RunResult:
    runner = WorkflowRunner(
        artifact_root=artifact_root,
        function_registry=build_test_no_llm_registry(),
        artifact_publishers=build_daily_intelligence_artifact_publishers(),
    )
    return runner.run(
        build_test_no_llm_workflow(),
        request or {"topic": "daily intelligence runtime smoke"},
        profile=PROFILE,
        run_id=run_id,
    )


def _topic_from_request(request: dict[str, Any]) -> str:
    topic = request.get("topic") or "daily intelligence runtime smoke"
    return str(topic).strip() or "daily intelligence runtime smoke"


def _plan(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    request = buffer.read("request")
    topic = _topic_from_request(request)
    return {
        "research_plan": {
            "topic": topic,
            "sections": ["summary", "signals", "risks"],
            "constraints": {
                "network": "disabled",
                "llm": "disabled",
                "deterministic": True,
            },
        }
    }


def _analyze(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    plan = buffer.read("research_plan")
    topic = plan["topic"]
    return {
        "analysis_result": {
            "findings": [
                {
                    "id": "finding-1",
                    "title": f"{topic} baseline signal",
                    "summary": f"Deterministic runtime smoke analysis for {topic}.",
                    "confidence": "high",
                }
            ],
            "risk_notes": ["No live sources or LLM calls are used in this test runner."],
        }
    }


def _write_report(buffer: StepScopedDataBufferView) -> dict[str, Any]:
    request = buffer.read("request")
    plan = buffer.read("research_plan")
    analysis = buffer.read("analysis_result")
    topic = _topic_from_request(request)
    finding = analysis["findings"][0]
    markdown = (
        f"# Daily Intelligence Test Report: {topic}\n\n"
        "## Summary\n"
        f"- {finding['summary']}\n\n"
        "## Runtime\n"
        "- Profile: test-no-llm\n"
        "- Network: disabled\n"
        "- LLM: disabled\n"
    )
    final_report = {
        "title": f"Daily Intelligence Test Report: {topic}",
        "profile": PROFILE,
        "topic": topic,
        "sections": [
            {
                "title": "Summary",
                "content": finding["summary"],
                "sources": [],
                "evidence_ids": [],
            },
            {
                "title": "Runtime",
                "content": "Deterministic function-only runner.",
                "sources": [],
                "evidence_ids": [],
            },
        ],
        "metadata": {
            "workflow_id": WORKFLOW_ID,
            "workflow_version": WORKFLOW_VERSION,
            "planned_sections": plan["sections"],
        },
    }
    return {"final_report": final_report, "report_markdown": markdown}
