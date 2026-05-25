"use client"

import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { PageHeader } from "@/components/layout/page-header"
import { IntelligenceBrief } from "@/features/dashboard/components/intelligence-brief"
import { MetricsStrip } from "@/features/dashboard/components/metrics-strip"
import { RightInsightPanel } from "@/features/dashboard/components/right-insight-panel"
import { TechRadarPreview } from "@/features/dashboard/components/tech-radar-preview"
import { TopStories } from "@/features/dashboard/components/top-stories"
import { TrendingTopicsPreview } from "@/features/dashboard/components/trending-topics-preview"
import { useDashboardOverview } from "@/features/dashboard/hooks/use-dashboard-overview"
import { useI18n } from "@/lib/i18n/use-i18n"

export default function DashboardPage() {
  const { t } = useI18n()
  const { data, isLoading, isError, error, refetch } = useDashboardOverview()

  if (isLoading) {
    return <PageSkeleton />
  }

  if (isError) {
    return <ErrorState message={error instanceof Error ? error.message : t("portal.home.loadError")} onRetry={() => refetch()} />
  }

  if (!data) {
    return <EmptyState title={t("portal.home.emptyTitle")} description={t("portal.home.emptyDescription")} />
  }

  return (
    <main className="space-y-6">
      <PageHeader
        eyebrow={t("portal.home.eyebrow")}
        title={t("portal.home.title")}
        description={t("portal.home.description")}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <MetricsStrip overview={data} />
          <IntelligenceBrief brief={data.brief} />
          <TopStories stories={data.topStories} />
          <TrendingTopicsPreview topics={data.trendingTopics} />
          <TechRadarPreview radar={data.techRadar} />
        </div>
        <RightInsightPanel overview={data} />
      </div>
    </main>
  )
}
