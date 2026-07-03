import { describe, expect, it } from "vitest"
import { filterRunList } from "@/features/studio/runs/hooks/use-run-list"
import type { StudioRunListItem } from "@/types/agent"

const runs: StudioRunListItem[] = [
  run("run-a", "daily", "live", "success", "2026-05-24T01:00:00Z", 90),
  run("run-b", "weekly", "editor", "failed", "2026-05-24T02:00:00Z", 40),
  run("run-c", "daily", "offline", "waiting_for_human", "2026-05-24T03:00:00Z", 70)
]

describe("useRunList filtering", () => {
  it("filters by status, workflow, and profile", () => {
    expect(filterRunList(runs, { status: ["failed"] }).map((item) => item.id)).toEqual(["run-b"])
    expect(filterRunList(runs, { workflowId: ["daily"] }).map((item) => item.id)).toEqual(["run-c", "run-a"])
    expect(filterRunList(runs, { profile: ["offline"] }).map((item) => item.id)).toEqual(["run-c"])
  })

  it("filters by agent and date range", () => {
    const realNow = Date.now
    Date.now = () => new Date("2026-05-24T04:00:00Z").getTime()
    try {
      expect(filterRunList(runs, { agentName: ["weekly"] }).map((item) => item.id)).toEqual(["run-b"])
      expect(filterRunList(runs, { dateRange: "today" }).map((item) => item.id)).toEqual(["run-c", "run-b", "run-a"])
      expect(filterRunList(runs, { dateRange: "custom" }).map((item) => item.id)).toEqual(["run-c", "run-b", "run-a"])
    } finally {
      Date.now = realNow
    }
  })

  it("sorts latest first by default", () => {
    expect(filterRunList(runs, {}).map((item) => item.id)).toEqual(["run-c", "run-b", "run-a"])
  })
})

function run(
  id: string,
  workflowId: string,
  profile: string,
  status: StudioRunListItem["status"],
  startedAt: string,
  qualityScore: number
): StudioRunListItem {
  return {
    id,
    agentName: workflowId,
    workflowId,
    workflowName: workflowId,
    profile,
    status,
    startedAt,
    durationSeconds: 60,
    inputCount: 0,
    outputCount: 0,
    artifactCount: 0,
    qualityScore,
    errorCount: status === "failed" ? 1 : 0,
    stepCount: 2,
    dataState: "ready",
    notices: []
  }
}
