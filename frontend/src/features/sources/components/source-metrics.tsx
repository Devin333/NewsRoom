import { AlertTriangle, CheckCircle2, Database, Gauge, RadioTower, Timer } from "lucide-react"
import { StudioMetricCard, StudioMetricGrid } from "@/features/studio/shared/components/studio-dashboard"
import { calculateSourceMetrics } from "@/features/sources/hooks/use-sources"
import { formatDurationMs, formatNumber } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { Source } from "@/types/source"

export function SourceMetrics({ sources }: { sources: Source[] }) {
  const { t } = useI18n()
  const metrics = calculateSourceMetrics(sources)

  return (
    <StudioMetricGrid className="xl:grid-cols-6 2xl:grid-cols-6">
      <StudioMetricCard label={t("studio.sources.total")} value={formatNumber(metrics.total)} detail={t("studio.sources.enabledDetail", { count: formatNumber(metrics.enabled) })} icon={Database} tone="accent" />
      <StudioMetricCard label={t("studio.sources.healthy")} value={formatNumber(metrics.healthy)} detail={t("studio.sources.available")} icon={CheckCircle2} tone="success" />
      <StudioMetricCard label={t("studio.sources.failed")} value={formatNumber(metrics.failed)} detail={t("studio.sources.needsReview")} icon={AlertTriangle} tone={metrics.failed ? "danger" : "success"} />
      <StudioMetricCard label={t("studio.sources.collected24h")} value={formatNumber(metrics.collected)} detail={t("studio.sources.sourceItems")} icon={RadioTower} />
      <StudioMetricCard label={t("studio.sources.errors24h")} value={formatNumber(metrics.errors)} detail={t("studio.sources.sourceErrors")} icon={Gauge} tone={metrics.errors ? "warning" : "success"} />
      <StudioMetricCard label={t("studio.sources.avgLatency")} value={formatDurationMs(metrics.avgLatency)} detail={t("studio.sources.perRun")} icon={Timer} />
    </StudioMetricGrid>
  )
}
