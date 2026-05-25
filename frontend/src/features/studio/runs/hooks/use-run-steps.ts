"use client"

import { useMemo } from "react"
import type { AgentStep } from "@/types/agent"

export function useRunSteps(steps: AgentStep[], status?: AgentStep["status"]) {
  const data = useMemo(() => (status ? steps.filter((step) => step.status === status) : steps), [status, steps])
  return { data, isLoading: false, isError: false, refetch: () => undefined }
}
