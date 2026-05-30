"use client"

import { useEffect, useState } from "react"
import { RunTimeline } from "./RunTimeline"
import type { RunEvents } from "@/lib/types"

export function RunLiveEvents({ runId }: { runId: string }) {
  const [data, setData] = useState<RunEvents | null>(null)

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const res = await fetch(`/api/v1/runs/${runId}/events`, { cache: "no-store" })
        if (res.ok && active) setData(await res.json())
      } catch {}
      if (active) setTimeout(poll, 3000)
    }
    poll()
    return () => { active = false }
  }, [runId])

  if (!data) return <p className="text-sm text-muted">Connecting…</p>
  return <RunTimeline events={data.events ?? []} />
}
