import Link from "next/link"
import type { ReactNode } from "react"
import { Clock3, ExternalLink, GitFork, Layers3, MessageSquare, Newspaper, Star, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { ProjectItem } from "@/types/projects"

export function ProjectCard({ project, detailHref }: { project: ProjectItem; detailHref?: string }) {
  const href = detailHref ?? `/tech/repos?project=${encodeURIComponent(project.slug)}`
  const updatedAt = project.pushedAt ?? project.updatedAt ?? project.lastPushedAt

  return (
    <Card className="flex h-full flex-col border-[#dbe3dc] bg-white/85 shadow-sm dark:border-border dark:bg-card">
      <CardContent className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="truncate font-mono text-xs text-[#334155]/55 dark:text-muted-foreground">{project.fullName}</p>
            <h2 className="mt-1 truncate text-lg font-semibold text-[#334155] dark:text-foreground">
              <Link href={href} className="hover:text-emerald-700">
                {project.name}
              </Link>
            </h2>
          </div>
          <Badge variant={project.maturity ? "info" : "muted"}>{project.maturity ? maturityLabel(project.maturity) : "Maturity unavailable"}</Badge>
        </div>

        <p className="line-clamp-3 min-h-[4.5rem] text-sm leading-6 text-[#334155]/68 dark:text-muted-foreground">{project.description}</p>

        <div className="grid grid-cols-3 gap-2 text-xs">
          <Metric icon={<Star className="size-3.5" />} label="Stars" value={formatCompactNumber(project.stars)} />
          <Metric icon={<GitFork className="size-3.5" />} label="Forks" value={formatCompactNumber(project.forks)} />
          <Metric icon={<TrendingUp className="size-3.5" />} label="Delta" value={formatSignedNumber(project.starGrowth7d ?? project.starGrowth24h)} />
        </div>

        <div className="flex flex-wrap gap-2">
          {project.language ? <Badge variant="muted">{project.language}</Badge> : null}
          {updatedAt ? (
            <Badge variant="muted">
              <Clock3 className="mr-1 size-3" />
              {formatDate(updatedAt)}
            </Badge>
          ) : null}
          {project.categoryRefs.slice(0, 2).map((category) => (
            <Badge key={category.category}>{category.label}</Badge>
          ))}
          {project.topics.slice(0, 3).map((topic) => (
            <Badge key={topic} variant="muted">
              {topic}
            </Badge>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-2 text-xs">
          <RelationMetric icon={<Layers3 className="size-3.5" />} label="Papers" value={project.relationCounts.papers} />
          <RelationMetric icon={<Newspaper className="size-3.5" />} label="News" value={project.relationCounts.news} />
          <RelationMetric icon={<MessageSquare className="size-3.5" />} label="Community" value={project.relationCounts.community} />
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-[#d8dfd8] pt-4 dark:border-border">
          <Button asChild variant="outline" size="sm">
            <a href={project.repoUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
              Open repo
            </a>
          </Button>
          <Button asChild size="sm">
            <Link href={href}>View detail</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md border border-[#edf1ed] bg-[#f7f9f6] px-2 py-2 dark:border-border dark:bg-background">
      <div className="flex items-center gap-1.5 text-[#334155]/55 dark:text-muted-foreground">
        {icon}
        <span className="font-mono text-[10px] uppercase">{label}</span>
      </div>
      <p className="mt-1 truncate text-sm font-semibold text-[#334155] dark:text-foreground">{value}</p>
    </div>
  )
}

function RelationMetric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-[#edf1ed] bg-white px-2 py-1.5 text-[#334155]/65 dark:border-border dark:bg-background dark:text-muted-foreground">
      {icon}
      <span className="font-semibold text-[#334155] dark:text-foreground">{value}</span>
      <span>{label}</span>
    </div>
  )
}

function formatCompactNumber(value: number | undefined): string {
  if (value === undefined) return "-"
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K`
  return String(value)
}

function formatSignedNumber(value: number | undefined): string {
  if (value === undefined) return "-"
  if (value > 0) return `+${formatCompactNumber(value)}`
  return formatCompactNumber(value)
}

function formatDate(value: string): string {
  const time = Date.parse(value)
  if (!Number.isFinite(time)) return value
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(time)
}

function maturityLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())
}
