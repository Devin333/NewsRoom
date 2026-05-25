import { AlertTriangle, CheckCircle2, CircleHelp, ShieldAlert, ShieldCheck } from "lucide-react"
import {
  StudioMetricCard,
  StudioMetricGrid,
  StudioPanel
} from "@/features/studio/shared/components/studio-dashboard"
import type { StudioQualityDashboard, StudioQualityStatus } from "@/types/quality"

const statusConfig: Record<StudioQualityStatus, { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral"; icon: React.ComponentType<{ className?: string }> }> = {
  passed: { label: "Passed", tone: "success", icon: ShieldCheck },
  warning: { label: "Warning", tone: "warning", icon: AlertTriangle },
  failed: { label: "Failed", tone: "danger", icon: ShieldAlert },
  review_required: { label: "Review required", tone: "info", icon: CheckCircle2 },
  unknown: { label: "Unknown", tone: "neutral", icon: CircleHelp }
}

export function QualityStatusBoard({ dashboard }: { dashboard: StudioQualityDashboard }) {
  return (
    <StudioMetricGrid className="xl:grid-cols-5 2xl:grid-cols-5">
      {(Object.keys(statusConfig) as StudioQualityStatus[]).map((status) => {
        const config = statusConfig[status]
        return (
          <StudioMetricCard
            key={status}
            label={config.label}
            value={dashboard.counts[status]}
            detail="Reports in gate"
            icon={config.icon}
            tone={config.tone}
          />
        )
      })}
    </StudioMetricGrid>
  )
}

export function QualityMetricBoard({ dashboard }: { dashboard: StudioQualityDashboard }) {
  const metrics = [
    ["Citation coverage", dashboard.metrics.citationCoverage === undefined ? "n/a" : `${dashboard.metrics.citationCoverage}%`],
    ["Source freshness", dashboard.metrics.sourceFreshness === undefined ? "n/a" : `${dashboard.metrics.sourceFreshness}%`],
    ["Duplicate rate", dashboard.metrics.duplicateRate === undefined ? "n/a" : `${dashboard.metrics.duplicateRate}%`],
    ["Unsupported claims", String(dashboard.metrics.unsupportedClaims)]
  ]

  return (
    <StudioPanel title="Gate metrics" description="Aggregated report quality signals across the current catalog.">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-md border border-border bg-secondary/30 p-3">
            <p className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">{label}</p>
            <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
          </div>
        ))}
      </div>
    </StudioPanel>
  )
}
