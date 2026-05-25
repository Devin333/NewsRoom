"use client"

import { useMemo } from "react"
import type { AgentRunFilters, StudioRunListItem } from "@/types/agent"

export function useRunList(
  filters: AgentRunFilters = {},
  runs: StudioRunListItem[]
): {
  data: StudioRunListItem[]
  isLoading: boolean
  isError: boolean
  error?: Error
  refetch: () => void
} {
  const data = useMemo(() => filterRunList(runs, filters), [filters, runs])
  return { data, isLoading: false, isError: false, refetch: () => undefined }
}

export function filterRunList(runs: StudioRunListItem[], filters: AgentRunFilters): StudioRunListItem[] {
  const keyword = filters.keyword?.trim().toLowerCase()

  return runs
    .filter((run) => {
      if (!keyword) return true
      return [run.id, run.agentName, run.workflowName, run.workflowId, run.profile, run.status]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(keyword)
    })
    .filter((run) => (!filters.agentName?.length ? true : filters.agentName.includes(run.agentName)))
    .filter((run) => (!filters.workflowId?.length ? true : filters.workflowId.includes(run.workflowId ?? run.workflowName ?? "")))
    .filter((run) => (!filters.status?.length ? true : filters.status.includes(run.status)))
    .filter((run) => (!filters.profile?.length ? true : filters.profile.includes(run.profile)))
    .filter((run) => (!filters.hasError ? true : run.errorCount > 0 || run.status === "failed"))
    .filter((run) => (filters.minQualityScore === undefined ? true : (run.qualityScore ?? 0) >= filters.minQualityScore))
    .filter((run) => inDateRange(run.startedAt, filters.dateRange))
    .sort((a, b) => compareRuns(a, b, filters.sort))
}

function inDateRange(startedAt: string, dateRange?: AgentRunFilters["dateRange"]): boolean {
  if (!dateRange || dateRange === "custom") return true
  const started = new Date(startedAt).getTime()
  if (Number.isNaN(started)) return true
  const now = Date.now()
  const windows = {
    today: 24 * 60 * 60 * 1000,
    week: 7 * 24 * 60 * 60 * 1000,
    month: 30 * 24 * 60 * 60 * 1000
  }
  return now - started <= windows[dateRange]
}

function compareRuns(a: StudioRunListItem, b: StudioRunListItem, sort: AgentRunFilters["sort"]): number {
  if (sort === "durationMs") return (b.durationMs ?? 0) - (a.durationMs ?? 0)
  if (sort === "qualityScore") return (b.qualityScore ?? 0) - (a.qualityScore ?? 0)
  if (sort === "errorCount") return b.errorCount - a.errorCount
  return new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
}
