"use client"

import { useMemo } from "react"
import { fallbackDetailForRun, studioAgentRunDetails, studioAgentRuns } from "@/features/studio/runs/lib/mock-agent-runs"
import type { StudioRunDetail } from "@/types/agent"

export function useRunDetail(
  runId: string,
  initialData?: StudioRunDetail
): {
  data?: StudioRunDetail
  isLoading: boolean
  isError: boolean
  error?: Error
  refetch: () => void
} {
  const data = useMemo(() => {
    if (initialData) return initialData

    const decoded = decodeURIComponent(runId)
    const exact = studioAgentRunDetails[decoded]
    if (exact) {
      return {
        ...exact,
        run: { ...exact.run, workflowId: exact.run.workflowName, dataState: "fallback", notices: ["当前为 fallback 数据"] },
        events: exact.logs,
        operations: { canCancel: false, canRerunFromStep: false, canSkipStep: false, canResolveBlocked: false },
        dataState: "fallback",
        notices: ["当前为 fallback 数据"]
      } satisfies StudioRunDetail
    }

    const run = studioAgentRuns.find((item) => item.id === decoded)
    if (!run) return undefined
    const fallback = fallbackDetailForRun(run)
    return {
      ...fallback,
      run: { ...fallback.run, workflowId: fallback.run.workflowName, dataState: "fallback", notices: ["当前为 fallback 数据"] },
      events: fallback.logs,
      operations: { canCancel: false, canRerunFromStep: false, canSkipStep: false, canResolveBlocked: false },
      dataState: "fallback",
      notices: ["当前为 fallback 数据"]
    } satisfies StudioRunDetail
  }, [initialData, runId])

  return {
    data,
    isLoading: false,
    isError: !data,
    error: data ? undefined : new Error(`Run ${runId} was not found.`),
    refetch: () => undefined
  }
}
