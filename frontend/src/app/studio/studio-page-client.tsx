"use client"

import { StudioFallbackNotice } from "@/features/studio/shared/components/studio-fallback-notice"
import { StudioMetricCard, StudioMetricGrid, StudioPageHeader } from "@/features/studio/shared/components/studio-dashboard"
import { PaperReaderOpsPanel } from "@/features/studio/shared/components/paper-reader-ops-panel"
import { PaperPdfProxyStatsPanel } from "@/features/studio/shared/components/paper-pdf-proxy-stats-panel"
import { StudioSectionCard } from "@/features/studio/shared/components/studio-section-card"
import { getLocalizedStudioModuleEntries } from "@/features/studio/shared/lib/studio-navigation"
import { useI18n } from "@/lib/i18n/use-i18n"

export function StudioHomePageClient() {
  const { locale, t } = useI18n()
  const moduleEntries = getLocalizedStudioModuleEntries(locale)

  return (
    <div className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.dashboard.eyebrow")}
        title={t("studio.dashboard.title")}
        description={t("studio.dashboard.description")}
      />

      <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
        <StudioMetricCard label={t("studio.dashboard.modules")} value={moduleEntries.length} detail={t("studio.dashboard.modulesDetail")} tone="accent" />
        <StudioMetricCard label={t("studio.dashboard.apiPosture")} value={t("studio.dashboard.liveFirst")} detail={t("studio.dashboard.fallbackVisible")} tone="success" />
        <StudioMetricCard label={t("studio.dashboard.writeSafety")} value={t("studio.dashboard.guarded")} detail={t("studio.dashboard.guardedDetail")} tone="warning" />
        <StudioMetricCard label={t("studio.dashboard.readerPortal")} value={t("studio.dashboard.isolated")} detail={t("studio.dashboard.shellOnly")} />
      </StudioMetricGrid>

      <StudioFallbackNotice message={t("studio.dashboard.fallbackMessage")} />

      <PaperReaderOpsPanel />

      <PaperPdfProxyStatsPanel />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" aria-label={t("studio.dashboard.modules")}>
        {moduleEntries.map((entry) => (
          <StudioSectionCard key={entry.href} entry={entry} />
        ))}
      </section>
    </div>
  )
}
