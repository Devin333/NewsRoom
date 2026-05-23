"use client"

import { useMemo } from "react"
import { fallbackDetailForRun, studioAgentRunDetails, studioAgentRuns } from "@/features/studio/runs/lib/mock-agent-runs"
import type { AgentRunDetail } from "@/types/agent"

export function useAgentRunDetail(runId: string, initialData?: AgentRunDetail): {
  data?: AgentRunDetail
  isLoading: boolean
  isError: boolean
  error?: Error
  refetch: () => void
} {
  const data = useMemo(() => {
    if (initialData) return initialData

    const decoded = decodeURIComponent(runId)
    const exact = studioAgentRunDetails[decoded]
    if (exact) return exact
    const run = studioAgentRuns.find((item) => item.id === decoded)
    return run ? fallbackDetailForRun(run) : undefined
  }, [initialData, runId])

  return {
    data,
    isLoading: false,
    isError: !data,
    error: data ? undefined : new Error(`Agent run ${runId} was not found.`),
    refetch: () => undefined
  }
}
