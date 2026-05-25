import { StudioFallbackNotice } from "@/features/studio/shared/components/studio-fallback-notice"
import { StudioMetricCard, StudioMetricGrid, StudioPageHeader } from "@/features/studio/shared/components/studio-dashboard"
import { PaperPdfProxyStatsPanel } from "@/features/studio/shared/components/paper-pdf-proxy-stats-panel"
import { StudioSectionCard } from "@/features/studio/shared/components/studio-section-card"
import { studioModuleEntries } from "@/features/studio/shared/lib/studio-navigation"

export default function StudioPage() {
  return (
    <div className="space-y-6">
      <StudioPageHeader
        eyebrow="Operations Studio"
        title="Runtime Dashboard"
        description="Monitor runs, business boards, evidence, quality gates, human review, artifacts, and source health from one operational console."
      />

      <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
        <StudioMetricCard label="Runtime modules" value={studioModuleEntries.length} detail="Active console areas" tone="accent" />
        <StudioMetricCard label="API posture" value="Live first" detail="Fallback is visible" tone="success" />
        <StudioMetricCard label="Write safety" value="Guarded" detail="Fallback disables risky actions" tone="warning" />
        <StudioMetricCard label="Reader Portal" value="Isolated" detail="Studio shell only" />
      </StudioMetricGrid>

      <StudioFallbackNotice message="Studio modules use live /api/v1 endpoints first. When a module cannot reach the API, it must show a visible fallback notice before using deterministic fallback data." />

      <PaperPdfProxyStatsPanel />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" aria-label="Studio module entries">
        {studioModuleEntries.map((entry) => (
          <StudioSectionCard key={entry.href} entry={entry} />
        ))}
      </section>
    </div>
  )
}
