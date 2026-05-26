import Link from "next/link"
import type { ReactNode } from "react"
import { ArrowLeft, ExternalLink, GitFork, Star, TrendingUp } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { PageHeader } from "@/components/layout/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { EvidenceRef, ProjectItem, RelatedCommunityRef, RelatedNewsRef, RelatedPaperRef } from "@/types/projects"

export function ProjectDetailPanel({ project }: { project: ProjectItem }) {
  return (
    <main className="space-y-8">
      <PageHeader
        eyebrow="Project Radar"
        title={project.name}
        description={project.description}
        actions={
          <>
            <Button asChild variant="outline">
              <Link href="/projects">
                <ArrowLeft className="size-4" />
                返回项目流
              </Link>
            </Button>
            <Button asChild>
              <a href={project.repoUrl} target="_blank" rel="noreferrer">
                <ExternalLink className="size-4" />
                GitHub
              </a>
            </Button>
          </>
        }
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric label="Stars" value={formatNumber(project.stars)} icon={<Star className="size-4" />} />
        <Metric label="Forks" value={formatNumber(project.forks)} icon={<GitFork className="size-4" />} />
        <Metric label="Watchers" value={formatNumber(project.watchers)} />
        <Metric label="Growth" value={formatNumber(project.starGrowth7d ?? project.starGrowth24h)} icon={<TrendingUp className="size-4" />} />
        <Metric label="Momentum" value={formatScore(project.projectMomentum)} />
      </section>

      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>工程判断</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5 text-sm leading-6 text-muted-foreground">
              <TextBlock title="解决的问题" value={project.problemSolved ?? project.description} />
              <TextBlock title="为什么值得关注" value={project.whyItMatters ?? "暂无额外说明，先以项目描述和证据来源为准。"} />
            </CardContent>
          </Card>

          <ReferenceList title="相关论文" items={project.relatedPapers ?? []} />
          <ReferenceList title="相关新闻" items={project.relatedNews ?? []} />
          <ReferenceList title="社区讨论" items={project.relatedCommunityTopics ?? []} />
          <EvidenceList refs={project.sourceRefs ?? []} />
        </section>

        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>项目资料</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <Fact label="仓库" value={project.repoUrl} href={project.repoUrl} />
              <Fact label="主页" value={project.homepageUrl} href={project.homepageUrl} />
              <Fact label="Owner" value={project.owner} />
              <Fact label="语言" value={project.language} />
              <Fact label="License" value={project.license} />
              <Fact label="最近 Push" value={formatDate(project.lastPushedAt)} />
              <Fact label="首次发现" value={formatDate(project.firstSeenAt)} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>标签</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {project.categoryRefs.map((category) => (
                <Badge key={category.category}>{category.label}</Badge>
              ))}
              {project.tags.map((tag) => (
                <Badge key={tag} variant="muted">
                  {tag}
                </Badge>
              ))}
              {!project.categoryRefs.length && !project.tags.length ? <p className="text-sm text-muted-foreground">暂无标签</p> : null}
            </CardContent>
          </Card>
        </aside>
      </div>
    </main>
  )
}

function Metric({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {icon}
          <span className="font-mono uppercase">{label}</span>
        </div>
        <p className="mt-2 text-2xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  )
}

function TextBlock({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      <p className="mt-1">{value}</p>
    </div>
  )
}

function ReferenceList({
  title,
  items,
}: {
  title: string
  items: Array<RelatedPaperRef | RelatedNewsRef | RelatedCommunityRef>
}) {
  if (!items.length) {
    return <EmptyState title={`${title}为空`} description="当前 artifact 没有提供这一组关联数据。" />
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="divide-y divide-border p-0">
        {items.map((item) => (
          <a
            key={`${item.title}-${item.url ?? item.id ?? ""}`}
            href={item.url ?? "#"}
            target={item.url ? "_blank" : undefined}
            rel={item.url ? "noreferrer" : undefined}
            className="block px-4 py-3 text-sm hover:bg-secondary"
          >
            <span className="font-medium text-foreground">{item.title}</span>
            {"sourceName" in item && item.sourceName ? <span className="ml-2 text-muted-foreground">{item.sourceName}</span> : null}
          </a>
        ))}
      </CardContent>
    </Card>
  )
}

function EvidenceList({ refs }: { refs: EvidenceRef[] }) {
  if (!refs.length) {
    return <EmptyState title="证据为空" description="当前项目没有可展示的 evidence refs。" />
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Evidence refs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {refs.map((ref) => (
          <a
            key={`${ref.id ?? ""}-${ref.url ?? ref.sourceUrl ?? ""}`}
            href={ref.url ?? ref.sourceUrl ?? "#"}
            target={ref.url || ref.sourceUrl ? "_blank" : undefined}
            rel={ref.url || ref.sourceUrl ? "noreferrer" : undefined}
            className="block rounded-md border border-border p-3 text-sm hover:bg-secondary"
          >
            <span className="font-medium text-foreground">{ref.title ?? ref.sourceName ?? ref.url ?? ref.sourceUrl ?? "Evidence"}</span>
            <span className="mt-1 block text-xs text-muted-foreground">{ref.sourceType ?? ref.reliability ?? "source"}</span>
          </a>
        ))}
      </CardContent>
    </Card>
  )
}

function Fact({ label, value, href }: { label: string; value?: string; href?: string }) {
  if (!value) return null
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border pb-3 last:border-0 last:pb-0">
      <span className="text-muted-foreground">{label}</span>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer" className="min-w-0 truncate text-right text-primary hover:underline">
          {value}
        </a>
      ) : (
        <span className="min-w-0 truncate text-right text-foreground">{value}</span>
      )}
    </div>
  )
}

function formatNumber(value: number | undefined): string {
  if (value === undefined) return "-"
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K`
  return String(value)
}

function formatScore(value: number | undefined): string {
  if (value === undefined) return "-"
  return value <= 1 ? `${Math.round(value * 100)}%` : value.toFixed(1)
}

function formatDate(value: string | undefined): string | undefined {
  if (!value) return undefined
  const time = Date.parse(value)
  if (!Number.isFinite(time)) return value
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(time)
}
