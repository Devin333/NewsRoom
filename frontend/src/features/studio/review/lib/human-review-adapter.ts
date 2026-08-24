import { safeApiGet } from "@/lib/api/server"
import type {
  ReviewHistoryEvent,
  ReviewRiskLevel,
  StudioReviewDetail,
  StudioReviewItem,
  StudioReviewQueue
} from "@/types/review"

export type ApiGraphWaitList = {
  run_id?: string
  waits?: ApiGraphWait[]
}

export type ApiGraphWait = {
  run_id?: string | null
  node_instance_id?: string | null
  wait_id?: string | null
  kind?: string | null
  status?: string | null
  lifecycle?: string | null
  outcome?: string | null
  graph_id?: string | null
  graph_version?: string | null
  graph_ref?: string | null
  graph_checksum?: string | null
  approval_id?: string | null
  signal_schema_ref?: string | null
  registered_sequence?: number | null
  last_event_sequence?: number | null
}

export type ApiRunList = {
  run_count?: number
  runs?: ApiRun[]
}

export type ApiRun = {
  run_id?: string | null
  id?: string | null
  status?: string | null
  graph_id?: string | null
  graph_version?: string | null
  graph_ref?: string | null
  graph_checksum?: string | null
  profile?: string | null
  started_at?: string | null
  finished_at?: string | null
  report_id?: string | null
  invalid_reason?: string | null
  output_preview?: Record<string, unknown> | null
  manifest?: Record<string, unknown> | null
}

export type ApiReportList = {
  report_count?: number
  reports?: ApiReport[]
}

export type ApiReport = {
  report_id?: string | null
  id?: string | null
  run_id?: string | null
  status?: string | null
  title?: string | null
  summary?: string | null
  created_at?: string | null
  metadata?: Record<string, unknown> | null
}

const BLOCKED_RUN_STATUSES = new Set(["blocked", "waiting_for_human"])
const FALLBACK_REPORT_STATUSES = new Set(["needs_review", "draft"])

export async function getReviewQueue(): Promise<StudioReviewQueue> {
  const runsResult = await safeApiGet<ApiRunList>("/api/v2/graph-runs?limit=100")

  const notices: string[] = []
  let dataState: StudioReviewQueue["dataState"] = "ready"
  let items: StudioReviewItem[] = []

  if (runsResult.ok) {
    const candidateRuns = runsResult.data.runs ?? []
    const waitResults = await Promise.all(
      candidateRuns
        .filter(isBlockedRun)
        .map((run) => {
          const runId = readString(run.run_id) ?? readString(run.id)
          return runId
            ? safeApiGet<ApiGraphWaitList>(`/api/v2/graph-runs/${encodeURIComponent(runId)}/waits`)
            : Promise.resolve({ ok: false as const, errorMessage: "run id is missing", errorCode: "missing_run_id" })
        })
    )
    waitResults.forEach((result) => {
      if (result.ok) items.push(...(result.data.waits ?? []).filter(isApprovalWait).map(mapGraphWaitToReviewItem))
      else notices.push(`Graph Wait API unavailable: ${result.errorMessage}.`)
    })
  } else {
    dataState = "partial"
    notices.push(`Runs API unavailable: ${runsResult.errorMessage}. Graph Wait review items may be incomplete.`)
  }

  if (!items.length) {
    const reportsResult = await safeApiGet<ApiReportList>("/api/v1/reports?limit=50")
    if (reportsResult.ok) {
      items.push(...mapFallbackReportsToReviewItems(reportsResult.data.reports ?? [], "Graph Wait queue is empty"))
    } else {
      notices.push(`Reports API unavailable: ${reportsResult.errorMessage}. Report fallback queue is incomplete.`)
    }
  }

  const uniqueItems = dedupeReviewItems(items)
  return {
    items: sortReviewItems(uniqueItems),
    notices,
    dataState
  }
}

export async function getReviewItemDetail(approvalId: string): Promise<StudioReviewDetail | undefined> {
  const queue = await getReviewQueue()
  const decodedApprovalId = decodeURIComponent(approvalId)
  const item = queue.items.find((candidate) => candidate.approvalId === decodedApprovalId)
  if (!item) return undefined

  return {
    item,
    notices: queue.notices,
    dataState: queue.dataState
  }
}

export function isApprovalWait(wait: ApiGraphWait): boolean {
  return normalizeText(wait.kind) === "approval" && Boolean(readString(wait.approval_id))
}

export function mapGraphWaitToReviewItem(wait: ApiGraphWait): StudioReviewItem {
  const approvalId = readString(wait.approval_id) ?? `wait:${readString(wait.wait_id) ?? "unknown"}`
  const runId = readString(wait.run_id)
  return {
    approvalId,
    requestedAction: "graph_approval_decision",
    status: "pending",
    rawStatus: readString(wait.status) ?? "registered",
    riskLevel: "high",
    reason: "A Graph Wait requires an explicit approval decision.",
    runId,
    nodeInstanceId: readString(wait.node_instance_id),
    waitId: readString(wait.wait_id),
    graphId: readString(wait.graph_id),
    graphVersion: readString(wait.graph_version),
    graphRef: readString(wait.graph_ref),
    graphChecksum: readString(wait.graph_checksum),
    notices: [],
    source: "graph_wait",
    actionKind: "approval_decision",
    history: [{ id: `${approvalId}:registered`, type: "graph_wait_registered", status: readString(wait.status) }],
    actionDisabledReason: runId && readString(wait.node_instance_id) && readString(wait.graph_checksum) ? undefined : "Graph Wait identity is incomplete; decision is disabled."
  }
}

export function mapBlockedRunsToReviewItems(runs: ApiRun[]): StudioReviewItem[] {
  return runs.filter(isBlockedRun).map(mapBlockedRunToReviewItem)
}

export function mapBlockedRunToReviewItem(run: ApiRun): StudioReviewItem {
  const runId = readString(run.run_id) ?? readString(run.id) ?? "unknown-run"
  const status = normalizeText(run.status) ?? "blocked"
  const reportId = readString(run.report_id) ?? extractReportId(objectRecord(run.output_preview)) ?? extractReportId(objectRecord(run.manifest))
  const requestedAt = readString(run.started_at)
  const reason = readString(run.invalid_reason) ?? (status === "waiting_for_human" ? "Run is waiting for a human decision." : "Run is blocked.")

  return {
    approvalId: `run:${runId}:blocked`,
    requestedAction: "graph_run_blocked",
    status: "pending",
    rawStatus: status,
    riskLevel: "high",
    reason,
    runId,
    reportId,
    requestedBy: readString(run.profile),
    requestedAt,
    payloadPreview: {
      run_id: runId,
      run_status: status,
      profile: run.profile,
      report_id: reportId
    },
    notices: ["Blocked run is shown for inspection only; no Graph Wait approval is registered."],
    source: "run",
    actionKind: "none",
    actionDisabledReason: "Blocked run has no registered Graph Wait approval; no review action is available.",
    history: [
      {
        id: `${runId}:blocked`,
        type: "run_blocked",
        at: requestedAt,
        reason,
        status
      }
    ]
  }
}

export function mapFallbackReportsToReviewItems(reports: ApiReport[], fallbackReason = "Graph Wait API unavailable"): StudioReviewItem[] {
  return reports.filter(isFallbackReport).map((report) => mapFallbackReportToReviewItem(report, fallbackReason))
}

export function mapFallbackReportToReviewItem(report: ApiReport, fallbackReason = "Graph Wait API unavailable"): StudioReviewItem {
  const reportId = readString(report.report_id) ?? readString(report.id) ?? "unknown-report"
  const runId = readString(report.run_id) ?? extractRunId(objectRecord(report.metadata))
  const status = normalizeText(report.status) ?? "draft"
  const title = readString(report.title)
  const summary = readString(report.summary)

  return {
    approvalId: `report:${reportId}:review`,
    requestedAction: status === "draft" ? "review_draft_report" : "review_report",
    status: "pending",
    rawStatus: status,
    riskLevel: "medium",
    reason: summary ?? title ?? "Report requires human review.",
    runId,
    reportId,
    requestedAt: readString(report.created_at),
    payloadPreview: {
      report_id: reportId,
      run_id: runId,
      status,
      title,
      metadata: objectRecord(report.metadata)
    },
    notices: [`Partial fallback item: ${fallbackReason}. Graph Wait decisions are disabled.`],
    source: "fallback",
    actionKind: "none",
    actionDisabledReason: "Graph Wait data is unavailable; fallback report items cannot be approved here.",
    history: [
      {
        id: `${reportId}:fallback`,
        type: "fallback_report_detected",
        at: readString(report.created_at),
        reason: summary ?? title,
        status
      }
    ]
  }
}

export function isBlockedRun(run: ApiRun): boolean {
  const status = normalizeText(run.status)
  return Boolean(status && BLOCKED_RUN_STATUSES.has(status))
}

export function isFallbackReport(report: ApiReport): boolean {
  const status = normalizeText(report.status)
  return Boolean(status && FALLBACK_REPORT_STATUSES.has(status))
}

function sortReviewItems(items: StudioReviewItem[]): StudioReviewItem[] {
  const riskWeight: Record<ReviewRiskLevel, number> = {
    critical: 4,
    high: 3,
    medium: 2,
    low: 1
  }
  return [...items].sort((left, right) => {
    if (left.status === "pending" && right.status !== "pending") return -1
    if (left.status !== "pending" && right.status === "pending") return 1
    const riskDelta = riskWeight[right.riskLevel] - riskWeight[left.riskLevel]
    if (riskDelta) return riskDelta
    return dateValue(right.requestedAt) - dateValue(left.requestedAt)
  })
}

function dedupeReviewItems(items: StudioReviewItem[]): StudioReviewItem[] {
  const byId = new Map<string, StudioReviewItem>()
  for (const item of items) {
    if (!byId.has(item.approvalId)) byId.set(item.approvalId, item)
  }
  return [...byId.values()]
}

function extractReportId(record: Record<string, unknown>): string | undefined {
  return (
    readString(record.report_id) ??
    readString(record.reportId) ??
    readString(record.final_report_id) ??
    readString(record.finalReportId)
  )
}

function extractRunId(record: Record<string, unknown>): string | undefined {
  return readString(record.run_id) ?? readString(record.runId) ?? readString(record.approval_run_id)
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {}
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length ? value : undefined
}

function normalizeText(value: unknown): string | undefined {
  return readString(value)?.trim().toLowerCase()
}

function dateValue(value: string | undefined): number {
  if (!value) return 0
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : 0
}
