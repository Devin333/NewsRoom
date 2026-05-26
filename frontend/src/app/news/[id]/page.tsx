"use client"

import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { AgentExplanationCard } from "@/features/news/components/agent-explanation-card"
import { AISummaryPanel } from "@/features/news/components/ai-summary-panel"
import { KeyFactsList } from "@/features/news/components/key-facts-list"
import { NewsDetailHeader } from "@/features/news/components/news-detail-header"
import { NewsEvidenceList } from "@/features/news/components/news-evidence-list"
import { NewsInsightPanel } from "@/features/news/components/news-insight-panel"
import { useNewsDetail } from "@/features/news/hooks/use-news-detail"

export default function NewsDetailPage({ params }: { params: { id: string } }) {
  const { data, isLoading, isError, error, refetch } = useNewsDetail(params.id)

  if (isLoading) {
    return <PageSkeleton />
  }

  if (isError) {
    return <ErrorState message={error instanceof Error ? error.message : "新闻详情加载失败。"} onRetry={() => refetch()} />
  }

  if (!data?.news) {
    return (
      <EmptyState
        title="未找到新闻"
        description="这个新闻 ID 不在当前 AI News 数据集中。"
        action={
          <Link href="/news" className="rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary">
            返回新闻
          </Link>
        }
      />
    )
  }

  return (
    <main className="space-y-6">
      {data.dataState === "fallback" ? (
        <div className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-muted-foreground">
          <Badge tone="warning">Fallback</Badge>
          <span className="ml-2">当前详情来自显式备用数据。</span>
        </div>
      ) : null}

      <NewsDetailHeader news={data.news} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <AISummaryPanel summary={data.news.detailedSummary} whyItMatters={data.news.whyItMatters} />
          <KeyFactsList facts={data.news.keyFacts} />
          <NewsEvidenceList evidence={data.evidence} />
          <section className="rounded-lg border border-border bg-card p-5">
            <h2 className="text-lg font-semibold text-foreground">相关时间线预览</h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              完整时间线会在主题和 Studio 工作区中展开，这里保留当前新闻与证据、后续事件的连接入口。
            </p>
          </section>
          <AgentExplanationCard items={data.news.agentExplanation} />
        </div>
        <NewsInsightPanel news={data.news} evidence={data.evidence} topic={data.topic} reports={data.reports} />
      </div>
    </main>
  )
}
