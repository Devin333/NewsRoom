"use client"

import { RefreshCcw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
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
          title="Dashboard overview failed"
          message={error instanceof Error ? error.message : "Unable to load dashboard overview."}
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
          title="No cross-board intelligence yet"
          description="No backend or local cross-board output currently has displayable content."
          action={
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCcw className="h-4 w-4" />
              Refresh
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <DashboardHeader overview={data} />
      <DashboardNotices overview={data} />
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
      eyebrow="Home / Intelligence Brief"
      title="Cross-board Intelligence"
      description="Daily synthesis across AI news, project radar, paper radar, and community pulse."
      actions={
        overview ? (
          <>
            <Badge variant={overview.dataState === "fallback" ? "warning" : overview.dataState === "partial" ? "accent" : "success"}>
              {overview.dataState}
            </Badge>
            <Badge variant="muted">{overview.generatedAt ? `Fresh ${formatDate(overview.generatedAt)}` : "No timestamp"}</Badge>
          </>
        ) : null
      }
    />
  )
}

function DashboardNotices({ overview }: { overview: DashboardOverview }) {
  const notices = overview.dataState === "fallback" && !overview.notices?.includes("Showing local fallback")
    ? ["Showing local fallback", ...(overview.notices ?? [])]
    : overview.notices ?? []

  if (!notices.length && overview.dataState !== "partial") {
    return null
  }

  return (
    <Card className="flex flex-col gap-3 p-4 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={overview.dataState === "fallback" ? "warning" : "accent"}>
          {overview.dataState === "fallback" ? "Showing local fallback" : "Partial data"}
        </Badge>
        {notices.slice(0, 3).map((notice) => (
          <span key={notice}>{notice}</span>
        ))}
      </div>
    </Card>
  )
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}
