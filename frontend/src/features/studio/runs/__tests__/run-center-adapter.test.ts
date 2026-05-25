import { describe, expect, it } from "vitest"
import { adaptRunDetail, adaptRunList, normalizeRunStatus } from "@/features/studio/runs/lib/run-center-adapter"
import type { RunCenterDetailResponses } from "@/features/studio/runs/api/run-center-api"

describe("Run Center adapter", () => {
  it("maps snake_case API fields to Studio run view models", () => {
    const result = adaptRunList({
      ok: true,
      data: {
        run_count: 1,
        runs: [
          {
            run_id: "run-api-1",
            workflow_id: "daily",
            workflow_version: "1.2.3",
            profile: "live",
            status: "queued",
            started_at: "2026-05-24T01:00:00Z",
            finished_at: "2026-05-24T01:01:00Z",
            report_id: "report-1",
            artifact_dir: ".newsroom/runs/run-api-1",
            quality_score: 0.82,
            step_count: 3,
            event_count: 7,
            artifact_count: 2,
            manifest_path: ".newsroom/runs/run-api-1/manifest.json"
          }
        ]
      }
    })

    expect(result.notices).toEqual([])
    expect(result.runs[0]).toMatchObject({
      id: "run-api-1",
      workflowId: "daily",
      workflowVersion: "1.2.3",
      profile: "live",
      status: "pending",
      reportId: "report-1",
      artifactDir: ".newsroom/runs/run-api-1",
      qualityScore: 82,
      stepCount: 3,
      eventCount: 7,
      manifestPath: ".newsroom/runs/run-api-1/manifest.json",
      dataState: "ready"
    })
  })

  it("normalizes runtime statuses", () => {
    expect(normalizeRunStatus("queued")).toBe("pending")
    expect(normalizeRunStatus("succeeded")).toBe("success")
    expect(normalizeRunStatus("completed")).toBe("success")
    expect(normalizeRunStatus("blocked")).toBe("blocked")
    expect(normalizeRunStatus("waiting_for_human")).toBe("waiting_for_human")
    expect(normalizeRunStatus("review_required")).toBe("waiting_for_human")
  })

  it("marks missing API steps as partial and uses fallback steps", () => {
    const detail = adaptRunDetail("run-daily-20260522-0800", responses({ steps: [] }))

    expect(detail?.dataState).toBe("partial")
    expect(detail?.steps.length).toBeGreaterThan(0)
    expect(detail?.dag.nodes.length).toBe(detail?.steps.length)
  })

  it("uses fallback when the API is unavailable and disables operations", () => {
    const detail = adaptRunDetail("run-daily-20260522-0800", failedResponses())

    expect(detail?.dataState).toBe("fallback")
    expect(detail?.notices.join(" ")).toContain("当前为 fallback 数据")
    expect(detail?.operations).toEqual({
      canCancel: false,
      canRerunFromStep: false,
      canSkipStep: false,
      canResolveBlocked: false
    })
  })

  it("preserves events, diagnostics, and health for detail tabs", () => {
    const detail = adaptRunDetail("run-api-2", responses())

    expect(detail?.dataState).toBe("ready")
    expect(detail?.events[0]).toMatchObject({
      eventType: "step_failed",
      level: "error",
      payload: { message: "failed", step_id: "collect" }
    })
    expect(detail?.diagnostics).toEqual({ summary: "diagnostic" })
    expect(detail?.health).toEqual({ status: "degraded" })
  })
})

function responses(overrides: { steps?: RunCenterDetailResponses["steps"] extends { ok: true; data: infer T } ? T["steps"] : never } = {}): RunCenterDetailResponses {
  return {
    detail: {
      ok: true,
      data: {
        run_id: "run-api-2",
        workflow_id: "daily",
        profile: "live",
        status: "blocked",
        started_at: "2026-05-24T01:00:00Z",
        artifact_count: 1,
        manifest: {
          steps: {
            collect: { status: "failed", error: "failed" }
          },
          path: ["collect"]
        }
      }
    },
    steps: {
      ok: true,
      data: {
        steps:
          overrides.steps ??
          [
            {
              step_id: "collect",
              status: "failed",
              started_at: "2026-05-24T01:00:00Z",
              finished_at: "2026-05-24T01:00:05Z",
              raw: { outputs: { items: 1 }, error: "failed" }
            }
          ]
      }
    },
    events: {
      ok: true,
      data: {
        events: [
          {
            event_id: "event-1",
            event_type: "step_failed",
            occurred_at: "2026-05-24T01:00:05Z",
            payload: { message: "failed", step_id: "collect" }
          }
        ]
      }
    },
    diagnostics: { ok: true, data: { diagnostics: { summary: "diagnostic" } } },
    health: { ok: true, data: { health: { status: "degraded" } } },
    artifacts: { ok: true, data: { artifacts: [] } }
  }
}

function failedResponses(): RunCenterDetailResponses {
  const failed = { ok: false as const, errorCode: "request_failed", errorMessage: "API unavailable" }
  return {
    detail: failed,
    steps: failed,
    events: failed,
    diagnostics: failed,
    health: failed,
    artifacts: failed
  }
}
