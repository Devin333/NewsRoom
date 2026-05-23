"use client"

import { useMemo } from "react"
import { studioAgentRuns } from "@/features/studio/runs/lib/mock-agent-runs"
import { filterRunsForTest } from "@/features/studio/runs/lib/run-test-utils"
import type { AgentRun, AgentRunFilters } from "@/types/agent"

export function useAgentRuns(filters: AgentRunFilters = {}, runs: AgentRun[] = studioAgentRuns): {
  data: AgentRun[]
  isLoading: boolean
  isError: boolean
  error?: Error
  refetch: () => void
} {
  const data = useMemo(() => filterRunsForTest(runs, filters), [filters, runs])
  return { data, isLoading: false, isError: false, refetch: () => undefined }
}
