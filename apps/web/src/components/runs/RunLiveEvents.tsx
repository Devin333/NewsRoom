"use client"

import { useEffect, useMemo, useState } from "react"
import { ErrorState } from "@/components/common/ErrorState"
import { EmptyState } from "@/components/common/EmptyState"
import { RunTimeline } from "@/components/runs/RunTimeline"
import { safeApiGet } from "@/lib/api-client"
import type { RunEvent, RunEvents } from "@/lib/types"

const POLL_MS = 3000

export function RunLiveEvents({ runId, initialEvents }: { runId: string; initialEvents: RunEvent[] }) {
  const [events, setEvents] = useState<RunEvent[]>(initialEvents)
  const [error, setError] = useState<{ message?: string; requestId?: string } | null>(null)
  const encodedRunId = useMemo(() => encodeURIComponent(runId), [runId])

  useEffect(() => {
    let cancelled = false

    async function poll() {
      const response = await safeApiGet<RunEvents>(`/api/v1/runs/${encodedRunId}/events?limit=50`)
      if (cancelled) {
        return
      }
      if (response.ok && response.data) {
        setEvents(response.data.events ?? [])
        setError(null)
      } else {
        setError({ message: response.errorMessage, requestId: response.requestId })
      }
    }

    poll()
    const timer = window.setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [encodedRunId])

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-line bg-white p-3 text-xs text-muted">
        Polling every {POLL_MS / 1000}s from <span className="font-mono text-ink">/api/v1/runs/{runId}/events</span>
      </div>
      {error ? <ErrorState title="Live event refresh failed" message={error.message} requestId={error.requestId} /> : null}
      {events.length ? (
        <RunTimeline events={events} />
      ) : (
        <EmptyState title="No events yet" message="Waiting for run events." />
      )}
    </div>
  )
}
