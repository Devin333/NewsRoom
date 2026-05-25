"use client"

import { Badge } from "@/components/common/badge"
import { EmptyState } from "@/components/common/empty-state"
import { JsonPreview } from "@/features/studio/runs/components/json-preview"
import { formatDateTime } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { RunLogItem } from "@/types/agent"

const levelTone = {
  debug: "neutral",
  info: "info",
  warning: "warning",
  error: "danger"
} as const

export function RunEventStream({ events }: { events: RunLogItem[] }) {
  const { t } = useI18n()
  if (!events.length) {
    return <EmptyState title={t("studio.runs.noEvents")} description={t("studio.runs.noEventsDescription")} />
  }

  return (
    <div className="space-y-2">
      {events.map((event) => (
        <article key={event.id} className="rounded-md border border-border bg-secondary/35 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={levelTone[event.level]}>{event.level}</Badge>
              {event.eventType ? <Badge tone="neutral">{event.eventType}</Badge> : null}
            </div>
            <span className="text-xs text-muted-foreground">{formatDateTime(event.timestamp)}</span>
          </div>
          <p className="mt-2 text-sm text-foreground">{event.message}</p>
          {event.stepId ? <p className="mt-1 font-mono text-xs text-muted-foreground">{event.stepId}</p> : null}
          {event.payload ? <div className="mt-3"><JsonPreview label={t("studio.runs.payload")} value={event.payload} /></div> : null}
        </article>
      ))}
    </div>
  )
}
