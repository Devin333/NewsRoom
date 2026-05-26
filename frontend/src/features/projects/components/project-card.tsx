import Link from "next/link"
import type { ReactNode } from "react"
import { ExternalLink, GitFork, Star, TrendingUp } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ProjectItem } from "@/types/projects"

export function ProjectCard({ project }: { project: ProjectItem }) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="gap-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="truncate text-lg">
              <Link href={`/projects/${project.slug}`} className="hover:text-primary">
                {project.name}
              </Link>
            </CardTitle>
            {project.owner ? <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{project.owner}</p> : null}
          </div>
          {project.qualityScore !== undefined ? <Badge variant="info">Q {formatScore(project.qualityScore)}</Badge> : null}
        </div>
        <p className="line-clamp-3 min-h-[4.5rem] text-sm leading-6 text-muted-foreground">{project.description}</p>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="grid grid-cols-3 gap-2 text-xs">
          <Metric icon={<Star className="size-3.5" />} label="Stars" value={formatNumber(project.stars)} />
          <Metric icon={<GitFork className="size-3.5" />} label="Forks" value={formatNumber(project.forks)} />
          <Metric icon={<TrendingUp className="size-3.5" />} label="Growth" value={formatNumber(project.starGrowth7d ?? project.starGrowth24h)} />
        </div>

        <div className="flex flex-wrap gap-2">
          {project.language ? <Badge variant="muted">{project.language}</Badge> : null}
          {project.categoryRefs.slice(0, 2).map((category) => (
            <Badge key={category.category} variant="default">
              {category.label}
            </Badge>
          ))}
          {project.tags.slice(0, 3).map((tag) => (
            <Badge key={tag} variant="muted">
              {tag}
            </Badge>
          ))}
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-4">
          <Button asChild variant="outline" size="sm">
            <a href={project.repoUrl} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" />
              GitHub
            </a>
          </Button>
          <Button asChild size="sm">
            <Link href={`/projects/${project.slug}`}>查看详情</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background px-2 py-2">
      <div className="flex items-center gap-1.5 text-muted-foreground">
        {icon}
        <span className="font-mono text-[10px] uppercase">{label}</span>
      </div>
      <p className="mt-1 truncate text-sm font-semibold text-foreground">{value}</p>
    </div>
  )
}

function formatNumber(value: number | undefined): string {
  if (value === undefined) return "-"
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K`
  return String(value)
}

function formatScore(value: number): string {
  return value <= 1 ? `${Math.round(value * 100)}%` : value.toFixed(1)
}
