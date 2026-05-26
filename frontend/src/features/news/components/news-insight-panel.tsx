import { FileText, LinkIcon, ShieldCheck } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/common/badge"
import { CredibilityBadge } from "@/components/common/credibility-badge"
import { HeatScoreBadge } from "@/components/common/heat-score-badge"
import { QualityBadge } from "@/components/common/quality-badge"
import { ScoreMeter } from "@/components/common/score-meter"
import { SourceBadge } from "@/components/common/source-badge"
import { StatusBadge } from "@/components/common/status-badge"
import { formatDateTime } from "@/lib/format"
import type { EvidenceItem } from "@/types/evidence"
import type { NewsItem } from "@/types/news"
import type { Report } from "@/types/report"
import type { Topic } from "@/types/topic"

export function NewsInsightPanel({
  news,
  evidence,
  topic,
  reports,
}: {
  news: NewsItem
  evidence: EvidenceItem[]
  topic?: Topic
  reports: Report[]
}) {
  return (
    <aside className="space-y-4">
      <PanelCard title="评分">
        <div className="space-y-4">
          <OptionalScoreMeter label="热度" value={news.heatScore} />
          <OptionalScoreMeter label="质量" value={news.qualityScore} />
          <div className="flex flex-wrap gap-2">
            {typeof news.heatScore === "number" ? <HeatScoreBadge value={news.heatScore} /> : <Badge tone="neutral">热度 N/A</Badge>}
            {typeof news.qualityScore === "number" ? <QualityBadge value={news.qualityScore} /> : <Badge tone="neutral">质量 N/A</Badge>}
            <CredibilityBadge value={news.credibility} />
          </div>
        </div>
      </PanelCard>

      <PanelCard title="来源信息">
        <div className="space-y-3">
          <SourceBadge name={news.sourceName} type={news.sourceType} />
          <p className="text-sm text-muted-foreground">发布于 {formatDateTime(news.publishedAt)}</p>
          <p className="text-sm text-muted-foreground">采集于 {formatDateTime(news.collectedAt)}</p>
        </div>
      </PanelCard>

      <PanelCard title="相关主题">
        {topic ? (
          <Link href={`/topics/${topic.id}`} className="block rounded-md border border-border p-3 hover:bg-secondary">
            <p className="text-sm font-medium text-foreground">{topic.name}</p>
            <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{topic.summary}</p>
          </Link>
        ) : news.topicId && news.topicName ? (
          <div className="rounded-md border border-border p-3">
            <p className="text-sm font-medium text-foreground">{news.topicName}</p>
            <p className="mt-2 text-sm text-muted-foreground">来自 AI News board 的主题关联。</p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">这条新闻暂未聚类到主题。</p>
        )}
      </PanelCard>

      <PanelCard title="报告链接">
        {reports.length ? (
          <div className="space-y-2">
            {reports.map((report) => (
              <Link key={report.id} href={`/reports/${report.id}`} className="flex gap-2 rounded-md border border-border p-3 hover:bg-secondary">
                <FileText className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                <span className="text-sm text-foreground">{report.title}</span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">暂无报告纳入这条新闻。</p>
        )}
      </PanelCard>

      <PanelCard title="验证状态">
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-success" />
            <StatusBadge status={evidence.length ? "passed" : "review"} />
          </div>
          <p className="text-sm text-muted-foreground">
            {evidence.length ? `已关联 ${evidence.length} 条证据。` : "暂无证据关联，这条新闻应保持复核状态。"}
          </p>
        </div>
      </PanelCard>

      <PanelCard title="原始来源">
        <a href={news.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm text-accent hover:text-foreground">
          打开原文
          <LinkIcon className="h-4 w-4" />
        </a>
      </PanelCard>
    </aside>
  )
}

function PanelCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-4 text-sm font-semibold text-foreground">{title}</h2>
      {children}
    </section>
  )
}

function OptionalScoreMeter({ label, value }: { label: string; value?: number }) {
  if (typeof value !== "number") {
    return (
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>{label}</span>
          <span className="font-medium text-foreground">N/A</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-secondary" />
      </div>
    )
  }
  return <ScoreMeter label={label} value={value} />
}
