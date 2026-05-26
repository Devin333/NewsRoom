"use client"

import { RefreshCcw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { PageHeader } from "@/components/layout/page-header"
import { DashboardFreshnessBar, DashboardStateNotice } from "@/features/dashboard/components/dashboard-state-panels"
import { IntelligenceBrief } from "@/features/dashboard/components/intelligence-brief"
import { MetricsStrip } from "@/features/dashboard/components/metrics-strip"
import { RightInsightPanel } from "@/features/dashboard/components/right-insight-panel"
import { TechRadarPreview } from "@/features/dashboard/components/tech-radar-preview"
import { TopStories } from "@/features/dashboard/components/top-stories"
import { TrendingTopicsPreview } from "@/features/dashboard/components/trending-topics-preview"
import { useDashboardOverview } from "@/features/dashboard/hooks/use-dashboard-overview"
import type { DashboardOverview } from "@/types/dashboard"

export function DashboardHomePage() {
  const { data, error, isError, isLoading, refetch } = useDashboardOverview()

  if (isLoading) {
    return (
      <div className="space-y-6">
        <DashboardHeader />
        <PageSkeleton />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="space-y-6">
        <DashboardHeader />
        <ErrorState
          title="首页情报加载失败"
          message={error instanceof Error ? error.message : "暂时无法加载首页情报。"}
          onRetry={() => void refetch()}
        />
      </div>
    )
  }

  if (!data || data.dataState === "empty") {
    return (
      <div className="space-y-6">
        <DashboardHeader overview={data} />
        <EmptyState
          title="暂无 cross-board 情报"
          description="后端和本地产物中还没有可展示的首页情报内容。"
          action={
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCcw className="h-4 w-4" />
              刷新
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <DashboardHeader overview={data} />
      <DashboardStateNotice overview={data} />
      <DashboardFreshnessBar overview={data} />
      <MetricsStrip overview={data} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <IntelligenceBrief brief={data.brief} />
          <TopStories stories={data.topStories} />
          <TrendingTopicsPreview topics={data.trendingTopics} />
          <TechRadarPreview radar={data.techRadar} />
        </div>
        <RightInsightPanel overview={data} />
      </div>
    </div>
  )
}

function DashboardHeader({ overview }: { overview?: DashboardOverview | null }) {
  return (
    <PageHeader
      eyebrow="首页 / Cross-board Intelligence"
      title="今日情报"
      description="汇总 AI 新闻、项目雷达、论文雷达与社区脉搏，给出跨板块摘要、趋势归因和推荐阅读路径。"
      actions={
        overview ? (
          <>
            <Badge variant={overview.dataState === "fallback" ? "warning" : overview.dataState === "partial" ? "accent" : "success"}>
              {stateLabel(overview.dataState)}
            </Badge>
            <Badge variant="muted">{overview.generatedAt ? `更新 ${formatDate(overview.generatedAt)}` : "暂无时间戳"}</Badge>
          </>
        ) : null
      }
    />
  )
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}

function stateLabel(state: DashboardOverview["dataState"]) {
  if (state === "fallback") return "本地 fallback"
  if (state === "partial") return "部分数据"
  if (state === "empty") return "暂无数据"
  return "已就绪"
}
