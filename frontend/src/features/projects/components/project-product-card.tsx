import Link from "next/link"
import type { ReactNode } from "react"
import { ArrowRight, GitFork, Layers3, Star, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatCompactNumber, formatDate, formatScore, labelize } from "@/features/projects/components/project-format"
import type { ProjectsApiProject } from "@/types/projects"

export function ProjectProductCard({
  project,
  compact = false,
}: {
  project: ProjectsApiProject
  compact?: boolean
}) {
  const href = `/projects/${encodeURIComponent(project.slug)}`
  const stars = numberMetric(project.metric_summary.github_stars)
  const forks = numberMetric(project.metric_summary.github_forks)
  const delta = numberMetric(project.metric_summary.stars_delta_7d)
  const score = project.hot_score ?? project.rising_score

  return (
    <article className="flex h-full flex-col rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-[#667085] dark:text-muted-foreground">{project.github_url ?? project.canonical_url ?? project.id}</p>
          <h2 className="mt-1 truncate text-lg font-semibold text-[#202124] dark:text-foreground">
            <Link href={href} className="hover:text-primary">
              {project.name}
            </Link>
          </h2>
        </div>
        <Badge variant={project.project_type ? "info" : "muted"}>{labelize(project.project_type)}</Badge>
      </div>

      <p className={compact ? "mt-3 line-clamp-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground" : "mt-3 line-clamp-3 min-h-[4.5rem] text-sm leading-6 text-[#4b5563] dark:text-muted-foreground"}>
        {project.description ?? project.tagline ?? "No description was available in the real Project Radar artifact."}
      </p>

      <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <Signal label="Stars" value={formatCompactNumber(stars)} icon={<Star className="size-3.5" />} />
        <Signal label="Forks" value={formatCompactNumber(forks)} icon={<GitFork className="size-3.5" />} />
        <Signal label="Delta" value={formatCompactNumber(delta)} icon={<TrendingUp className="size-3.5" />} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {project.category ? <Badge>{labelize(project.category)}</Badge> : null}
        {project.updated_at ? <Badge variant="muted">Updated {formatDate(project.updated_at)}</Badge> : null}
        {project.tags.slice(0, compact ? 2 : 4).map((tag) => (
          <Badge key={tag} variant="muted">
            {labelize(tag)}
          </Badge>
        ))}
      </div>

      <div className="mt-auto flex items-center justify-between gap-3 border-t border-[#e5e7eb] pt-4 text-xs text-[#667085] dark:border-border dark:text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Layers3 className="size-3.5" />
          {project.source_count} sources
        </span>
        <span>Score {formatScore(score ?? undefined)}</span>
      </div>

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button asChild variant="outline" size="sm" disabled={!project.github_url}>
          <a href={project.github_url ?? project.canonical_url ?? href} target="_blank" rel="noreferrer">
            Open source
          </a>
        </Button>
        <Button asChild size="sm">
          <Link href={href}>
            View detail
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

function numberMetric(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}
