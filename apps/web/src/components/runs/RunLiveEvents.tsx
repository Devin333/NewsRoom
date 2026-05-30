"use client"

import { useEffect, useRef, useState } from "react"
import { RunTimeline } from "./RunTimeline"
import type { RunEvent } from "@/lib/types"

export function RunLiveEvents({ runId }: { runId: string }) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    // 先拉一次历史事件
    fetch(`/api/v1/runs/${runId}/events`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setEvents(d?.data?.events ?? d?.events ?? []))
      .catch(() => {})

    // 再开 SSE 流
    const es = new EventSource(`/api/v1/runs/${runId}/events/stream`)
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onmessage = (e) => {
      try {
        const ev: RunEvent = JSON.parse(e.data)
        setEvents((prev) => {
          if (prev.some((p) => p.event_id && p.event_id === ev.event_id)) return prev
          return [...prev, ev]
        })
      } catch {}
    }
    es.onerror = () => {
      setConnected(false)
      es.close()
    }

    return () => { es.close() }
  }, [runId])

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-good animate-pulse" : "bg-subtle"}`} />
        <span className="text-xs text-muted">{connected ? "Live" : "Connecting…"}</span>
      </div>
      <RunTimeline events={events} />
    </div>
  )
}
