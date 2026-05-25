"use client"

import { EmptyState } from "@/components/common/empty-state"
import { SourceHealthBadge } from "@/components/common/source-health-badge"
import { StudioTableFrame } from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime, formatDurationMs, formatNumber, titleCase } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Source } from "@/types/source"

export function SourceHealthTable({
  sources,
  selectedSourceId,
  onSelectSource
}: {
  sources: Source[]
  selectedSourceId?: string
  onSelectSource: (sourceId: string) => void
}) {
  if (!sources.length) {
    return <EmptyState title="No matching sources" description="Adjust source search, type, health, or enabled filters." />
  }

  if (sources.every((source) => !source.enabled)) {
    return <EmptyState title="All sources are disabled" description="Runtime collection will not produce new evidence until sources are enabled." />
  }

  return (
    <StudioTableFrame>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1120px] border-collapse text-left text-sm">
          <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium">Enabled</th>
              <th className="px-4 py-3 font-medium">Health</th>
              <th className="px-4 py-3 font-medium">Last run</th>
              <th className="px-4 py-3 font-medium">Last success</th>
              <th className="px-4 py-3 font-medium">Errors 24h</th>
              <th className="px-4 py-3 font-medium">Collected 24h</th>
              <th className="px-4 py-3 font-medium">Avg latency</th>
              <th className="px-4 py-3 font-medium">Profile</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr
                key={source.id}
                className={cn(
                  "cursor-pointer border-b border-border/70 last:border-b-0 hover:bg-secondary/50",
                  selectedSourceId === source.id && "bg-secondary/60"
                )}
                onClick={() => onSelectSource(source.id)}
              >
                <td className="px-4 py-3">
                  <p className="truncate font-medium text-foreground">{source.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{source.id}</p>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{titleCase(source.type)}</td>
                <td className="px-4 py-3 text-muted-foreground">{source.enabled ? "Enabled" : "Disabled"}</td>
                <td className="px-4 py-3"><SourceHealthBadge status={source.healthStatus} /></td>
                <td className="px-4 py-3 text-muted-foreground">{formatDateTime(source.lastRunAt)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatDateTime(source.lastSuccessAt)}</td>
                <td className={cn("px-4 py-3", source.errorCount24h ? "font-semibold text-warning" : "text-muted-foreground")}>{formatNumber(source.errorCount24h)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatNumber(source.collectedCount24h)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatDurationMs(source.avgLatencyMs)}</td>
                <td className="max-w-48 truncate px-4 py-3 text-muted-foreground">{source.configProfile ?? "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </StudioTableFrame>
  )
}
