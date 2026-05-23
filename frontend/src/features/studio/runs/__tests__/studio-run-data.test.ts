import { describe, expect, it } from "vitest";
import { studioAgentRunDetails, studioAgentRuns, fallbackDetailForRun } from "@/features/studio/runs/lib/mock-agent-runs";
import { filterRunsForTest } from "@/features/studio/runs/lib/run-test-utils";
import { layoutWorkflowNodes } from "@/features/studio/runs/lib/workflow-layout";

const completeDetail = studioAgentRunDetails["run-daily-20260522-0800"];

describe("Task 04 Studio run data", () => {
  it("meets the Agent Run mock data floor", () => {
    expect(studioAgentRuns.length).toBeGreaterThanOrEqual(12);
    expect(studioAgentRuns.filter((run) => run.status === "running").length).toBeGreaterThanOrEqual(1);
    expect(studioAgentRuns.filter((run) => run.status === "failed").length).toBeGreaterThanOrEqual(2);
    expect(studioAgentRuns.filter((run) => run.status === "partially_failed").length).toBeGreaterThanOrEqual(1);
  });

  it("provides a complete run detail for the primary mock run", () => {
    expect(completeDetail.steps).toHaveLength(8);
    expect(completeDetail.dag.nodes.length).toBeGreaterThanOrEqual(8);
    expect(completeDetail.dag.edges.length).toBeGreaterThanOrEqual(7);
    expect(completeDetail.logs.length).toBeGreaterThanOrEqual(20);
    expect(completeDetail.toolCalls.length).toBeGreaterThanOrEqual(5);
    expect(completeDetail.memoryHits.length).toBeGreaterThanOrEqual(5);
    expect(completeDetail.artifacts.length).toBeGreaterThanOrEqual(4);
    expect(completeDetail.quality?.checks.length).toBeGreaterThanOrEqual(5);
    expect(completeDetail.errors.length).toBeGreaterThanOrEqual(1);
  });

  it("builds deterministic fallback detail for list-only runs", () => {
    const fallback = fallbackDetailForRun(studioAgentRuns[1]);

    expect(fallback.run.id).toBe(studioAgentRuns[1].id);
    expect(fallback.dataState).toBe("fallback");
    expect(fallback.steps.length).toBeGreaterThan(0);
    expect(fallback.dag.nodes.every((node) => node.stepId.startsWith(studioAgentRuns[1].id))).toBe(true);
  });

  it("filters runs by status, agent, quality, errors, and sort order", () => {
    expect(filterRunsForTest(studioAgentRuns, { status: ["failed"] }).every((run) => run.status === "failed")).toBe(true);
    expect(filterRunsForTest(studioAgentRuns, { agentName: ["DailyNewsAgent"] }).every((run) => run.agentName === "DailyNewsAgent")).toBe(true);
    expect(filterRunsForTest(studioAgentRuns, { hasError: true }).every((run) => run.errorCount > 0)).toBe(true);
    expect(filterRunsForTest(studioAgentRuns, { minQualityScore: 85 }).every((run) => (run.qualityScore ?? 0) >= 85)).toBe(true);

    const byErrors = filterRunsForTest(studioAgentRuns, { sort: "errorCount" });
    expect(byErrors[0].errorCount).toBeGreaterThanOrEqual(byErrors[byErrors.length - 1].errorCount);
  });

  it("lays out workflow nodes in execution order", () => {
    const nodes = layoutWorkflowNodes(completeDetail.dag.nodes);

    expect(nodes[0].data.type).toBe("collect");
    expect(nodes.at(-1)?.data.type).toBe("final");
  });
});
