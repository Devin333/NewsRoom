"use client"

import { useMemo } from "react"
import { studioAgentRuns } from "@/features/studio/runs/lib/mock-agent-runs"
import type { StudioOverview } from "@/types/agent"

export function useStudioOverview(initialData?: StudioOverview): {
  data?: StudioOverview
  isLoading: boolean
  isError: boolean
  error?: Error
  refetch: () => void
} {
  const data = useMemo(() => {
    if (initialData) return initialData

    const activeRuns = studioAgentRuns.filter((run) => run.status === "running").length
    const failedRuns24h = studioAgentRuns.filter((run) => run.errorCount > 0 || run.status === "failed" || run.status === "partially_failed").length
    const completedRuns24h = studioAgentRuns.filter((run) => run.status === "success" || run.status === "succeeded").length
    const durationValues = studioAgentRuns.map((run) => run.durationMs).filter((value): value is number => value !== undefined)
    const qualityValues = studioAgentRuns.map((run) => run.qualityScore).filter((value): value is number => value !== undefined)

    return {
      activeRuns,
      failedRuns24h,
      completedRuns24h,
      avgDurationMs: average(durationValues),
      avgQualityScore: average(qualityValues),
      artifactsGenerated24h: studioAgentRuns.reduce((total, run) => total + run.artifactCount, 0),
      qualityReviewRequired: studioAgentRuns.filter((run) => run.status === "partially_failed" || (run.qualityScore ?? 100) < 75).length,
      latestRuns: studioAgentRuns.slice(0, 6)
    } satisfies StudioOverview
  }, [initialData])

  return { data, isLoading: false, isError: false, refetch: () => undefined }
}

function average(values: number[]): number | undefined {
  if (!values.length) return undefined
  return Math.round(values.reduce((total, value) => total + value, 0) / values.length)
}
