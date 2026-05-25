import { safeApiGet, type SafeApiResult } from "@/lib/api/server"
import {
  adaptEvidenceOverview,
  adaptRunEvidenceDetail,
  buildFallbackEvidenceOverview,
  buildFallbackRunEvidenceDetail
} from "@/features/studio/evidence/lib/evidence-adapter"
import type { StudioEvidenceOverview, StudioRunEvidenceDetail } from "@/types/evidence"

type ApiRunList = {
  run_count?: number
  runs?: ApiRunListItem[]
}

type ApiRunListItem = {
  run_id?: string | null
  id?: string | null
  report_id?: string | null
}

export async function getEvidenceOverview(): Promise<StudioEvidenceOverview> {
  const runsResult = await safeApiGet<ApiRunList>("/api/v1/runs?limit=12")
  if (!runsResult.ok || !runsResult.data?.runs?.length) {
    return buildFallbackEvidenceOverview([noticeFromResult("runs", runsResult)])
  }

  const runItems = runsResult.data.runs.slice(0, 8)
  const details = await Promise.all(
    runItems.map(async (runItem) => {
      const runId = runIdFromItem(runItem)
      if (!runId) {
        return buildFallbackRunEvidenceDetail("unknown-run", ["Run list item did not include a run id."])
      }
      const encodedRunId = encodeURIComponent(runId)
      const [detailResult, diagnosticsResult, lineageResult] = await Promise.all([
        safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}`),
        safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}/diagnostics`),
        safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}/lineage`)
      ])
      return adaptRunEvidenceDetail({
        runId,
        runListItem: runItem,
        runDetail: detailResult.ok ? detailResult.data : undefined,
        diagnostics: diagnosticsResult.ok ? diagnosticsResult.data : undefined,
        lineage: lineageResult.ok ? lineageResult.data : undefined,
        notices: [
          ...noticesForResults([
            ["detail", detailResult],
            ["diagnostics", diagnosticsResult],
            ["lineage", lineageResult]
          ])
        ],
        dataState: stateFromResults([detailResult, diagnosticsResult, lineageResult])
      })
    })
  )

  return adaptEvidenceOverview(details, ["Loaded run evidence from API; missing quality fields are shown as partial evidence."])
}

export async function getRunEvidenceDetail(runIdValue: string, reportIdValue?: string): Promise<StudioRunEvidenceDetail> {
  const decodedRunId = decodeURIComponent(runIdValue)
  const encodedRunId = encodeURIComponent(decodedRunId)
  const [detailResult, eventsResult, diagnosticsResult, lineageResult] = await Promise.all([
    safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}`),
    safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}/events?limit=100`),
    safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}/diagnostics`),
    safeApiGet<unknown>(`/api/v1/runs/${encodedRunId}/lineage`)
  ])

  if (!detailResult.ok && !diagnosticsResult.ok && !lineageResult.ok) {
    return buildFallbackRunEvidenceDetail(decodedRunId, noticesForResults([
      ["detail", detailResult],
      ["events", eventsResult],
      ["diagnostics", diagnosticsResult],
      ["lineage", lineageResult]
    ]))
  }

  const reportId = reportIdValue ?? reportIdFromDetail(detailResult.ok ? detailResult.data : undefined)
  const reportQualityResult = reportId
    ? await safeApiGet<unknown>(`/api/v1/reports/${encodeURIComponent(reportId)}/quality`)
    : undefined

  return adaptRunEvidenceDetail({
    runId: decodedRunId,
    reportId,
    runDetail: detailResult.ok ? detailResult.data : undefined,
    events: eventsResult.ok ? eventsResult.data : undefined,
    diagnostics: diagnosticsResult.ok ? diagnosticsResult.data : undefined,
    lineage: lineageResult.ok ? lineageResult.data : undefined,
    reportQuality: reportQualityResult?.ok ? reportQualityResult.data : undefined,
    notices: [
      ...noticesForResults([
        ["detail", detailResult],
        ["events", eventsResult],
        ["diagnostics", diagnosticsResult],
        ["lineage", lineageResult],
        ...(reportQualityResult ? [["report quality", reportQualityResult] as const] : [])
      ]),
      ...(!reportId ? ["No report id was available for report quality lookup."] : [])
    ],
    dataState: stateFromResults([
      detailResult,
      eventsResult,
      diagnosticsResult,
      lineageResult,
      ...(reportQualityResult ? [reportQualityResult] : [])
    ])
  })
}

function runIdFromItem(item: ApiRunListItem): string | undefined {
  return item.run_id ?? item.id ?? undefined
}

function reportIdFromDetail(detail: unknown): string | undefined {
  const root = record(detail)
  const manifest = record(root?.manifest)
  const output = record(manifest?.output)
  return stringValue(root?.report_id) ?? stringValue(manifest?.report_id) ?? stringValue(output?.report_id)
}

function noticesForResults(results: Array<readonly [string, SafeApiResult<unknown> | undefined]>): string[] {
  return results.flatMap(([name, result]) => {
    if (!result || result.ok) return []
    const requestId = result.requestId ? ` requestId=${result.requestId}` : ""
    return [`${name} API unavailable: ${result.errorMessage}.${requestId}`]
  })
}

function noticeFromResult(name: string, result: SafeApiResult<unknown>): string {
  if (result.ok) return `${name} API returned no evidence runs.`
  const requestId = result.requestId ? ` requestId=${result.requestId}` : ""
  return `${name} API unavailable: ${result.errorMessage}.${requestId}`
}

function stateFromResults(results: Array<SafeApiResult<unknown> | undefined>) {
  const actual = results.filter((result): result is SafeApiResult<unknown> => Boolean(result))
  if (!actual.length) return "fallback" as const
  if (actual.every((result) => !result.ok)) return "fallback" as const
  if (actual.some((result) => !result.ok)) return "partial" as const
  return "ready" as const
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length ? value : undefined
}
