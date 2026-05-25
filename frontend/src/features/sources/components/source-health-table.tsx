"use client"

import { EmptyState } from "@/components/common/empty-state"
import { SourceHealthBadge } from "@/components/common/source-health-badge"
import { StudioTableFrame } from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime, formatDurationMs, formatNumber, titleCase } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
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
  const { t } = useI18n()
  if (!sources.length) {
    return <EmptyState title={t("studio.sources.noMatching")} description={t("studio.sources.noMatchingDescription")} />
  }

  if (sources.every((source) => !source.enabled)) {
    return <EmptyState title={t("studio.sources.allDisabled")} description={t("studio.sources.allDisabledDescription")} />
  }

  return (
    <StudioTableFrame>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1120px] border-collapse text-left text-sm">
          <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">{t("studio.sources.source")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.type")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.enabled")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.health")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.lastRun")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.lastSuccess")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.errors24h")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.collected24h")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.avgLatency")}</th>
              <th className="px-4 py-3 font-medium">{t("studio.sources.profile")}</th>
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
                <td className="px-4 py-3 text-muted-foreground">{source.enabled ? t("studio.sources.enabledValue") : t("studio.sources.disabledValue")}</td>
                <td className="px-4 py-3"><SourceHealthBadge status={source.healthStatus} /></td>
                <td className="px-4 py-3 text-muted-foreground">{formatDateTime(source.lastRunAt)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatDateTime(source.lastSuccessAt)}</td>
                <td className={cn("px-4 py-3", source.errorCount24h ? "font-semibold text-warning" : "text-muted-foreground")}>{formatNumber(source.errorCount24h)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatNumber(source.collectedCount24h)}</td>
                <td className="px-4 py-3 text-muted-foreground">{formatDurationMs(source.avgLatencyMs)}</td>
                <td className="max-w-48 truncate px-4 py-3 text-muted-foreground">{source.configProfile ?? t("studio.sources.none")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </StudioTableFrame>
  )
}
