import { EmptyState } from "@/components/common/EmptyState"
import { formatDateTime } from "@/lib/format"
import type { RunEvent } from "@/lib/types"

export function RunTimeline({ events }: { events: RunEvent[] }) {
  if (!events.length) {
    return <EmptyState title="No events" message="This run has no event records." />
  }

  return (
    <ol className="space-y-3">
      {events.map((event, index) => (
        <li key={`${event.event_id ?? event.event_type}-${index}`} className="rounded-lg border border-line bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-medium text-ink">{event.event_type}</p>
            <p className="text-xs text-muted">{formatDateTime(event.created_at ?? event.occurred_at)}</p>
          </div>
          {event.step_id ? <p className="mt-1 text-sm text-muted">step={event.step_id}</p> : null}
        </li>
      ))}
    </ol>
  )
}
