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

export default function DashboardPage() {
  const { data, isLoading, isError, error, refetch } = useDashboardOverview()

  if (isLoading) {
    return <PageSkeleton />
  }

  if (isError) {
    return <ErrorState message={error instanceof Error ? error.message : "仪表盘数据加载失败。"} onRetry={() => refetch()} />
  }

  if (!data) {
    return <EmptyState title="暂无仪表盘总览" description="mock 仪表盘总览当前不可用。" />
  }

  return (
    <main className="space-y-6">
      <PageHeader
        eyebrow="读者门户"
        title="情报仪表盘"
        description="用于跟踪 AI 技术新闻、趋势信号、来源健康和智能体运行质量的日常工作台。"
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
