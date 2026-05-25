"use client"

import { Badge } from "@/components/ui/badge"
import { StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import type { ReviewHistoryEvent, StudioReviewItem } from "@/types/review"

export function ReviewHistoryPanel({
  history,
  items,
  title = "Operation history"
}: {
  history?: ReviewHistoryEvent[]
  items?: StudioReviewItem[]
  title?: string
}) {
  const events = history ?? eventsFromItems(items ?? [])

  return (
    <StudioPanel title={title} actions={<Badge variant="muted">{events.length}</Badge>} contentClassName="space-y-3">
      {events.length ? (
        events.map((event) => (
          <div key={event.id} className="rounded-md border border-border bg-background p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="default">{event.type}</Badge>
              {event.status ? <span className="text-xs text-muted-foreground">{event.status}</span> : null}
              {event.actor ? <span className="text-xs text-muted-foreground">by {event.actor}</span> : null}
              {event.at ? <span className="text-xs text-muted-foreground">{formatDateTime(event.at)}</span> : null}
            </div>
            {event.reason ? <p className="mt-2 text-sm leading-6 text-muted-foreground">{event.reason}</p> : null}
            {event.modifications && Object.keys(event.modifications).length ? (
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs text-foreground">
                {JSON.stringify(event.modifications, null, 2)}
              </pre>
            ) : null}
          </div>
        ))
      ) : (
        <p className="text-sm text-muted-foreground">No recorded decisions yet.</p>
      )}
    </StudioPanel>
  )
}

function eventsFromItems(items: StudioReviewItem[]): ReviewHistoryEvent[] {
  return items
    .filter((item) => item.status !== "pending")
    .flatMap((item) =>
      item.history?.length
        ? item.history
        : [
            {
              id: `${item.approvalId}:status`,
              type: item.status,
              at: item.requestedAt,
              reason: item.reason,
              status: item.rawStatus ?? item.status
            }
          ]
    )
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}
