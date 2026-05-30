import { formatDateTime } from "@/lib/format"
import type { RunEvent } from "@/lib/types"

export function RunTimeline({ events }: { events: RunEvent[] }) {
  if (!events.length) return <p className="text-sm text-muted">No events yet.</p>
  return (
    <ol className="space-y-0">
      {events.map((ev, i) => (
        <li key={ev.event_id ?? i} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="mt-1.5 h-2 w-2 rounded-full bg-line ring-2 ring-white" />
            {i < events.length - 1 && <div className="w-px flex-1 bg-line" />}
          </div>
          <div className="pb-4">
            <p className="text-sm font-medium text-ink">{ev.event_type}</p>
            <div className="mt-0.5 flex items-center gap-3 text-xs text-muted">
              {ev.step_id && <span className="font-mono">{ev.step_id}</span>}
              <span>{formatDateTime(ev.occurred_at ?? ev.created_at ?? "")}</span>
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}
