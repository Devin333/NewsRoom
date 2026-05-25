import { AlertTriangle, CheckCircle2, Database, Gauge, RadioTower, Timer } from "lucide-react"
import { StudioMetricCard, StudioMetricGrid } from "@/features/studio/shared/components/studio-dashboard"
import { calculateSourceMetrics } from "@/features/sources/hooks/use-sources"
import { formatDurationMs, formatNumber } from "@/lib/format"
import type { Source } from "@/types/source"

export function SourceMetrics({ sources }: { sources: Source[] }) {
  const metrics = calculateSourceMetrics(sources)

  return (
    <StudioMetricGrid className="xl:grid-cols-6 2xl:grid-cols-6">
      <StudioMetricCard label="Sources" value={formatNumber(metrics.total)} detail={`${formatNumber(metrics.enabled)} enabled`} icon={Database} tone="accent" />
      <StudioMetricCard label="Healthy" value={formatNumber(metrics.healthy)} detail="Available sources" icon={CheckCircle2} tone="success" />
      <StudioMetricCard label="Failed" value={formatNumber(metrics.failed)} detail="Needs review" icon={AlertTriangle} tone={metrics.failed ? "danger" : "success"} />
      <StudioMetricCard label="Collected 24h" value={formatNumber(metrics.collected)} detail="Source items" icon={RadioTower} />
      <StudioMetricCard label="Errors 24h" value={formatNumber(metrics.errors)} detail="Source errors" icon={Gauge} tone={metrics.errors ? "warning" : "success"} />
      <StudioMetricCard label="Avg latency" value={formatDurationMs(metrics.avgLatency)} detail="Per source run" icon={Timer} />
    </StudioMetricGrid>
  )
}
