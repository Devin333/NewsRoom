import Link from "next/link"
import type { ReactNode } from "react"
import { ArrowRight, GitFork, Layers3, Star, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatCompactNumber, formatDate, formatScore, formatSignedNumber, labelize } from "@/features/projects/components/project-format"
import type { ProjectItem } from "@/types/projects"

export function ProjectProductCard({
  project,
  detailHref,
  compact = false,
}: {
  project: ProjectItem
  detailHref?: string
  compact?: boolean
}) {
  const href = detailHref ?? `/projects/${encodeURIComponent(project.slug)}`
  const updatedAt = project.pushedAt ?? project.updatedAt ?? project.lastPushedAt
  const evidenceCount = project.relationCounts.papers + project.relationCounts.news + project.relationCounts.community

  return (
    <article className="flex h-full flex-col rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-[#667085] dark:text-muted-foreground">{project.fullName}</p>
          <h2 className="mt-1 truncate text-lg font-semibold text-[#202124] dark:text-foreground">
            <Link href={href} className="hover:text-primary">
              {project.name}
            </Link>
          </h2>
        </div>
        <Badge variant={project.maturity ? "info" : "muted"}>{project.maturity ? labelize(project.maturity) : "未标注"}</Badge>
      </div>

      <p className={compact ? "mt-3 line-clamp-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground" : "mt-3 line-clamp-3 min-h-[4.5rem] text-sm leading-6 text-[#4b5563] dark:text-muted-foreground"}>
        {project.description}
      </p>

      <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <Signal label="Stars" value={formatCompactNumber(project.stars)} icon={<Star className="size-3.5" />} />
        <Signal label="Forks" value={formatCompactNumber(project.forks)} icon={<GitFork className="size-3.5" />} />
        <Signal label="Delta" value={formatSignedNumber(project.starGrowth7d ?? project.starGrowth24h)} icon={<TrendingUp className="size-3.5" />} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {project.language ? <Badge variant="muted">{project.language}</Badge> : null}
        {updatedAt ? <Badge variant="muted">更新 {formatDate(updatedAt)}</Badge> : null}
        {project.categoryRefs.slice(0, compact ? 1 : 2).map((category) => (
          <Badge key={category.category}>{category.label}</Badge>
        ))}
        {project.topics.slice(0, compact ? 2 : 3).map((topic) => (
          <Badge key={topic} variant="muted">
            {topic}
          </Badge>
        ))}
      </div>

      <div className="mt-auto flex items-center justify-between gap-3 border-t border-[#e5e7eb] pt-4 text-xs text-[#667085] dark:border-border dark:text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Layers3 className="size-3.5" />
          证据 {evidenceCount}
        </span>
        <span>趋势 {formatScore(project.scores.trendScore ?? project.projectMomentum)}</span>
      </div>

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button asChild variant="outline" size="sm">
          <a href={project.repoUrl} target="_blank" rel="noreferrer">
            打开仓库
          </a>
        </Button>
        <Button asChild size="sm">
          <Link href={href}>
            查看详情
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </div>
    </article>
  )
}

function Signal({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <div className="rounded-md border border-[#edf1f5] bg-[#f8fafc] px-2 py-2 dark:border-border dark:bg-background">
      <div className="flex items-center gap-1.5 text-[#667085] dark:text-muted-foreground">
        {icon}
        <span className="font-mono text-[10px] uppercase">{label}</span>
      </div>
      <p className="mt-1 truncate text-sm font-semibold text-[#202124] dark:text-foreground">{value}</p>
    </div>
  )
}
