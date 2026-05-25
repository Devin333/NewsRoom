import type { AgentRun, AgentRunDetail } from "@/types/agent"

export const studioAcceptanceRunIds = {
  failed: "run-daily-20260522-0800",
  passed: "run-daily-20260521-0800",
  pending: "run-report-20260522-0715"
} as const

export const studioRunFixtures: AgentRun[] = [
  {
    id: studioAcceptanceRunIds.failed,
    agentName: "DailyNewsAgent",
    workflowId: "daily-newsroom-brief",
    workflowName: "Daily NewsRoom Brief",
    profile: "ops-studio",
    status: "failed",
    startedAt: "2026-05-22T08:00:00.000Z",
    finishedAt: "2026-05-22T08:54:00.000Z",
    durationMs: 3_240_000,
    durationSeconds: 3240,
    inputCount: 126,
    outputCount: 38,
    artifactCount: 5,
    qualityScore: 72,
    errorCount: 1,
    eventCount: 24,
    reportId: "report-daily-20260522",
    manifestPath: "artifacts/runs/run-daily-20260522-0800/manifest.json",
    dataState: "fallback",
    notices: ["Fallback data is visible while /api/v1/runs is unavailable."],
    stepCount: 4,
    steps: [
      { id: "collect", label: "Collect", status: "success" },
      { id: "analyze", label: "Analyze", status: "success" },
      { id: "quality", label: "Quality gate", status: "failed" },
      { id: "publish", label: "Publish", status: "skipped" }
    ]
  },
  {
    id: studioAcceptanceRunIds.passed,
    agentName: "DailyNewsAgent",
    workflowId: "daily-newsroom-brief",
    workflowName: "Daily NewsRoom Brief",
    profile: "ops-studio",
    status: "success",
    startedAt: "2026-05-21T08:00:00.000Z",
    finishedAt: "2026-05-21T08:44:00.000Z",
    durationMs: 2_640_000,
    durationSeconds: 2640,
    inputCount: 118,
    outputCount: 41,
    artifactCount: 6,
    qualityScore: 89,
    errorCount: 0,
    eventCount: 18,
    reportId: "report-daily-20260521",
    manifestPath: "artifacts/runs/run-daily-20260521-0800/manifest.json",
    dataState: "ready",
    notices: [],
    stepCount: 4
  },
  {
    id: studioAcceptanceRunIds.pending,
    agentName: "ReportWriterAgent",
    workflowId: "report-writer",
    workflowName: "Report Writer",
    profile: "editorial",
    status: "running",
    startedAt: "2026-05-22T07:15:00.000Z",
    durationMs: 0,
    durationSeconds: 0,
    inputCount: 42,
    outputCount: 8,
    artifactCount: 2,
    qualityScore: 64,
    errorCount: 0,
    eventCount: 9,
    reportId: "report-weekly-20260522",
    dataState: "partial",
    notices: ["Run is still producing events."],
    stepCount: 3
  }
]

export const studioFailedRunDetailFixture: AgentRunDetail = {
  run: studioRunFixtures[0],
  steps: [
    {
      id: "step-collect",
      runId: studioAcceptanceRunIds.failed,
      nodeId: "node-collect",
      label: "Collect source signals",
      type: "collect",
      status: "success",
      startedAt: "2026-05-22T08:00:00.000Z",
      finishedAt: "2026-05-22T08:08:00.000Z"
    },
    {
      id: "step-quality",
      runId: studioAcceptanceRunIds.failed,
      nodeId: "node-quality",
      label: "Quality gate",
      type: "quality",
      status: "failed",
      startedAt: "2026-05-22T08:48:00.000Z",
      finishedAt: "2026-05-22T08:53:00.000Z",
      errorMessage: "Unsupported claim failed citation coverage."
    }
  ],
  dag: {
    nodes: [
      { id: "node-collect", stepId: "step-collect", label: "Collect source signals", type: "collect", status: "success" },
      {
        id: "node-quality",
        stepId: "step-quality",
        label: "Quality gate",
        type: "quality",
        status: "failed",
        errorMessage: "Unsupported claim failed citation coverage."
      }
    ],
    edges: [{ id: "collect-quality", source: "node-collect", target: "node-quality" }]
  },
  logs: [
    {
      id: "event-001",
      timestamp: "2026-05-22T08:50:00.000Z",
      level: "error",
      message: "quality_gate_failed",
      stepId: "step-quality",
      eventType: "quality_gate_failed"
    }
  ],
  toolCalls: [],
  memoryHits: [],
  artifacts: [],
  quality: {
    runId: studioAcceptanceRunIds.failed,
    score: 72,
    status: "failed",
    checks: [
      {
        id: "citation-coverage",
        name: "Citation coverage",
        status: "failed",
        message: "Unsupported claim failed citation coverage."
      }
    ]
  },
  errors: [
    {
      id: "err-citation-coverage",
      runId: studioAcceptanceRunIds.failed,
      stepId: "step-quality",
      timestamp: "2026-05-22T08:52:00.000Z",
      message: "Unsupported claim failed citation coverage.",
      retryHint: "Add primary evidence and rerun the quality step."
    }
  ],
  dataState: "fallback",
  notices: ["Fallback data is visible while /api/v1/runs is unavailable."]
}
