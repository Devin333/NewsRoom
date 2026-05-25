"use client"

import { useMemo } from "react"
import type { RunLogItem } from "@/types/agent"

export function useRunEvents(events: RunLogItem[], stepId?: string) {
  const data = useMemo(() => (stepId ? events.filter((event) => event.stepId === stepId) : events), [events, stepId])
  return { data, isLoading: false, isError: false, refetch: () => undefined }
}
