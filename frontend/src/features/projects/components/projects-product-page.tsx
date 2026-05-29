"use client"

import Link from "next/link"
import { ArrowRight, Binoculars, Boxes, FlaskConical, Flame, FolderKanban, GitBranch, Search, Sparkles, Star, Telescope } from "lucide-react"
import type { ComponentType } from "react"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PROJECT_PRODUCT_SECTIONS, fetchProjectProductSection, fetchProjects, projectProductSection } from "@/lib/projects/api"
import { formatCompactNumber, formatDate, formatScore, formatSignedNumber } from "@/features/projects/components/project-format"
import { ProjectProductCard } from "@/features/projects/components/project-product-card"
import { ProjectDegradedNotice, ProjectEmptyState, ProjectErrorState, ProjectLoadingState, ProjectSourceLine } from "@/features/projects/components/project-product-state"
import type { ProjectCategory, ProjectItem, ProjectListParams, ProjectListResult, ProjectProductRoute, ProjectProductSection } from "@/types/projects"

type ProjectsProductPageProps = {
  route: ProjectProductRoute
}

const routeIcons: Record<ProjectProductRoute, ComponentType<{ className?: string }>> = {
  home: GitBranch,
  hot: Flame,
  rising: Sparkles,
  tools: Boxes,
  cases: FolderKanban,
  lab: FlaskConical,
  collections: Binoculars,
  watchlist: Star,
}

const collectionFilters: Array<{ label: string; params: ProjectListParams }> = [
  { label: "Agent", params: { category: "agent_framework", sort: "trending", limit: 12 } },
  { label: "RAG", params: { category: "rag", sort: "trending", limit: 12 } },
  { label: "推理", params: { category: "inference", sort: "activity", limit: 12 } },
  { label: "评测", params: { category: "evaluation", sort: "quality", limit: 12 } },
  { label: "Coding", params: { category: "coding", sort: "growth", limit: 12 } },
]

export function ProjectsProductPage({ route }: ProjectsProductPageProps) {
  const section = useMemo(() => projectProductSection(route), [route])
  const isHome = route === "home"
  const [query, setQuery] = useState("")
  const queryParams = useMemo<ProjectListParams>(() => {
    const trimmed = query.trim()
    return trimmed ? { q: trimmed, sort: "trending", limit: 18 } : section.params
  }, [query, section.params])

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["projects", "product", route, queryParams],
    queryFn: () => (query.trim() ? fetchProjects(queryParams) : fetchProjectProductSection(route, { params: queryParams })),
  })

  if (isLoading) {
    return <ProjectLoadingState title={isHome ? "正在加载 Projects 首页" : `正在加载${section.title}`} />
  }

  if (isError) {
    return <ProjectErrorState message={error instanceof Error ? error.message : undefined} onRetry={() => refetch()} />
  }

  if (!data) {
    return <ProjectEmptyState />
  }

  return (
    <main className="space-y-10 font-papers-research">
      <ProjectHero section={section} route={route} result={data} query={query} onQueryChange={setQuery} isFetching={isFetching} />
      <ProjectDegradedNotice result={data} />
      {isHome ? <ProjectsHome result={data} /> : <ProjectsRouteView route={route} section={section} result={data} query={query} />}
    </main>
  )
}

function ProjectHero({
  section,
  route,
  result,
  query,
  onQueryChange,
  isFetching,
}: {
  section: ProjectProductSection
  route: ProjectProductRoute
  result: ProjectListResult
  query: string
  onQueryChange: (value: string) => void
  isFetching: boolean
}) {
  const Icon = routeIcons[route]
  const topProject = result.allFiltered[0] ?? result.items[0]

  return (
    <section className="grid gap-8 py-8 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-end">
      <div className="min-w-0">
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <Badge variant="info">Project Radar</Badge>
          <Badge variant="muted">真实 API</Badge>
          {isFetching ? <Badge variant="muted">刷新中</Badge> : null}
        </div>
        <h1 className="max-w-5xl text-5xl font-black leading-none tracking-normal text-[#202124] sm:text-6xl lg:text-7xl dark:text-foreground">
          {route === "home" ? "Projects" : section.title}
        </h1>
        <p className="mt-6 max-w-3xl text-base leading-7 text-[#4b5563] dark:text-muted-foreground">{section.description}</p>
        <div className="mt-7 flex flex-wrap gap-2">
          <HeroPill label="可见项目" value={result.allFiltered.length} />
          <HeroPill label="总项目" value={result.allItems.length} />
          <HeroPill label="状态" value={result.dataState} />
          <HeroPill label="来源" value={result.source} />
        </div>
        <div className="mt-6 max-w-2xl">
          <label className="sr-only" htmlFor="projects-product-search">
            搜索项目
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="projects-product-search"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              className="h-11 rounded-md bg-white pl-9 dark:bg-card"
              placeholder="搜索真实仓库、作者、主题或工程问题"
            />
          </div>
        </div>
      </div>

      <aside className="rounded-md border border-[#d8dee7] bg-white p-5 shadow-sm dark:border-border dark:bg-card">
        <div className="flex items-start gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-md bg-[#0f172a] text-white dark:bg-primary">
            <Icon className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase text-[#667085] dark:text-muted-foreground">当前焦点</p>
            {topProject ? (
              <>
                <h2 className="mt-2 line-clamp-2 text-lg font-semibold text-[#202124] dark:text-foreground">{topProject.fullName}</h2>
                <p className="mt-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">
                  趋势 {formatScore(topProject.scores.trendScore ?? topProject.projectMomentum)} · Star {formatCompactNumber(topProject.stars)}
                </p>
                <Button asChild className="mt-4" size="sm">
                  <Link href={`/projects/${encodeURIComponent(topProject.slug)}`}>
                    查看项目
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </>
            ) : (
              <p className="mt-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">没有真实 Project Radar 数据可展示。</p>
            )}
          </div>
        </div>
      </aside>
    </section>
  )
}

function ProjectsHome({ result }: { result: ProjectListResult }) {
  if (!result.allItems.length) return <ProjectEmptyState />

  const hot = topBy(result.allItems, (project) => project.scores.trendScore ?? project.projectMomentum ?? 0).slice(0, 3)
  const rising = topBy(result.allItems, (project) => project.starGrowth7d ?? project.starGrowth24h ?? 0).slice(0, 4)
  const evidence = topBy(result.allItems, evidenceScore).slice(0, 5)

  return (
    <>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {result.metrics.map((metric) => (
          <div key={metric.label} className="rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
            <p className="text-xs font-semibold uppercase text-[#667085] dark:text-muted-foreground">{metric.label}</p>
            <p className="mt-2 text-3xl font-semibold text-[#202124] dark:text-foreground">{metric.value}</p>
            {metric.hint ? <p className="mt-1 text-sm text-muted-foreground">{metric.hint}</p> : null}
          </div>
        ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        {PROJECT_PRODUCT_SECTIONS.map((item) => (
          <Link key={item.id} href={item.href} className="group rounded-md border border-[#d8dee7] bg-white p-5 shadow-sm transition-colors hover:border-primary/60 dark:border-border dark:bg-card">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-[#202124] dark:text-foreground">{item.title}</h2>
                <p className="mt-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">{item.description}</p>
              </div>
              <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </div>
          </Link>
        ))}
      </section>

      <section className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0 space-y-4">
          <SectionHeader title="热门项目" description="真实 Project Radar 中趋势分最高的项目。" href="/projects/hot" />
          <div className="grid gap-4 lg:grid-cols-3">
            {hot.map((project) => (
              <ProjectProductCard key={project.id} project={project} compact />
            ))}
          </div>
        </div>
        <aside className="space-y-4">
          <SectionHeader title="证据关注" description="按论文、新闻和社区引用数量排序。" href="/projects/cases" />
          <div className="rounded-md border border-[#d8dee7] bg-white dark:border-border dark:bg-card">
            {evidence.map((project) => (
              <CompactProjectRow key={project.id} project={project} />
            ))}
          </div>
        </aside>
      </section>

      <section className="space-y-4">
        <SectionHeader title="增长观察" description="Star delta 或 velocity 正在抬升的项目。" href="/projects/rising" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {rising.map((project) => (
            <ProjectProductCard key={project.id} project={project} compact />
          ))}
        </div>
      </section>

      <ProjectSourceLine result={result} />
    </>
  )
}

function ProjectsRouteView({
  route,
  section,
  result,
  query,
}: {
  route: ProjectProductRoute
  section: ProjectProductSection
  result: ProjectListResult
  query: string
}) {
  if (!result.allItems.length) return <ProjectEmptyState />

  const items = routeItems(route, result)
  const visible = query.trim() ? result.items : items

  if (route === "collections") {
    return <ProjectCollections result={result} />
  }

  if (!visible.length) {
    return <ProjectEmptyState title="当前筛选没有真实 Project Radar 数据" />
  }

  return (
    <>
      <section className="flex flex-col gap-3 border-y border-[#d8dee7] py-4 sm:flex-row sm:items-center sm:justify-between dark:border-border">
        <div>
          <h2 className="text-xl font-semibold text-[#202124] dark:text-foreground">{section.title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">展示 {visible.length} 个真实项目记录。</p>
        </div>
        <Button asChild variant="outline">
          <Link href="/tech/repos">打开兼容雷达页</Link>
        </Button>
      </section>

      {route === "cases" ? <ProjectCaseList projects={visible} /> : null}
      {route === "watchlist" ? <ProjectWatchlist projects={visible} /> : null}
      {route !== "cases" && route !== "watchlist" ? (
        <section className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {visible.map((project) => (
            <ProjectProductCard key={project.id} project={project} />
          ))}
        </section>
      ) : null}

      <ProjectSourceLine result={result} />
    </>
  )
}

function ProjectCollections({ result }: { result: ProjectListResult }) {
  return (
    <>
      <section className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {collectionFilters.map((collection) => {
          const projects = filterCollection(result.allItems, collection.params).slice(0, 4)
          return (
            <article key={collection.label} className="rounded-md border border-[#d8dee7] bg-white p-5 shadow-sm dark:border-border dark:bg-card">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-[#202124] dark:text-foreground">{collection.label}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">真实记录 {projects.length} 个</p>
                </div>
                <Telescope className="size-5 text-muted-foreground" />
              </div>
              {projects.length ? (
                <div className="mt-4 space-y-3">
                  {projects.map((project) => (
                    <CompactProjectRow key={project.id} project={project} />
                  ))}
                </div>
              ) : (
                <p className="mt-4 text-sm leading-6 text-muted-foreground">这个集合下没有真实 Project Radar 数据。</p>
              )}
            </article>
          )
        })}
      </section>
      <ProjectSourceLine result={result} />
    </>
  )
}

function ProjectCaseList({ projects }: { projects: ProjectItem[] }) {
  return (
    <section className="space-y-4">
      {projects.map((project) => (
        <article key={project.id} className="rounded-md border border-[#d8dee7] bg-white p-5 shadow-sm dark:border-border dark:bg-card">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_16rem]">
            <div className="min-w-0">
              <p className="font-mono text-xs text-[#667085] dark:text-muted-foreground">{project.fullName}</p>
              <h2 className="mt-1 text-xl font-semibold text-[#202124] dark:text-foreground">
                <Link href={`/projects/${encodeURIComponent(project.slug)}`} className="hover:text-primary">
                  {project.name}
                </Link>
              </h2>
              <p className="mt-3 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">
                {project.whyItMatters ?? project.problemSolved ?? project.description}
              </p>
            </div>
            <div className="grid gap-2 text-sm">
              <CaseMetric label="论文" value={project.relationCounts.papers} />
              <CaseMetric label="新闻" value={project.relationCounts.news} />
              <CaseMetric label="社区" value={project.relationCounts.community} />
            </div>
          </div>
        </article>
      ))}
    </section>
  )
}

function ProjectWatchlist({ projects }: { projects: ProjectItem[] }) {
  return (
    <section className="rounded-md border border-[#d8dee7] bg-white dark:border-border dark:bg-card">
      {projects.map((project, index) => (
        <div key={project.id} className="grid gap-4 border-b border-[#e5e7eb] p-4 last:border-0 lg:grid-cols-[3rem_minmax(0,1fr)_18rem] dark:border-border">
          <span className="flex size-9 items-center justify-center rounded-md bg-[#f1f5f9] text-sm font-semibold text-[#202124] dark:bg-background dark:text-foreground">
            {index + 1}
          </span>
          <div className="min-w-0">
            <Link href={`/projects/${encodeURIComponent(project.slug)}`} className="font-semibold text-[#202124] hover:text-primary dark:text-foreground">
              {project.fullName}
            </Link>
            <p className="mt-1 line-clamp-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">{project.description}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="muted">Star {formatCompactNumber(project.stars)}</Badge>
            <Badge variant="muted">Delta {formatSignedNumber(project.starGrowth7d ?? project.starGrowth24h)}</Badge>
            <Badge variant="info">质量 {formatScore(project.qualityScore ?? project.scores.qualityScore)}</Badge>
          </div>
        </div>
      ))}
    </section>
  )
}

function CompactProjectRow({ project }: { project: ProjectItem }) {
  return (
    <Link href={`/projects/${encodeURIComponent(project.slug)}`} className="block border-b border-[#e5e7eb] px-4 py-3 last:border-0 hover:bg-[#f8fafc] dark:border-border dark:hover:bg-background">
      <span className="block truncate text-sm font-semibold text-[#202124] dark:text-foreground">{project.fullName}</span>
      <span className="mt-1 block truncate text-xs text-muted-foreground">
        Star {formatCompactNumber(project.stars)} · Delta {formatSignedNumber(project.starGrowth7d ?? project.starGrowth24h)} · 更新 {formatDate(project.pushedAt ?? project.updatedAt)}
      </span>
    </Link>
  )
}

function SectionHeader({ title, description, href }: { title: string; description: string; href: string }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-2xl font-semibold text-[#202124] dark:text-foreground">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">{description}</p>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link href={href}>
          查看全部
          <ArrowRight className="size-4" />
        </Link>
      </Button>
    </div>
  )
}

function HeroPill({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-md border border-[#d8dee7] bg-white px-3 py-1 text-xs text-[#4b5563] shadow-sm dark:border-border dark:bg-card dark:text-muted-foreground">
      <span className="font-medium text-[#202124] dark:text-foreground">{label}</span>
      {value}
    </span>
  )
}

function CaseMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-[#edf1f5] bg-[#f8fafc] px-3 py-2 dark:border-border dark:bg-background">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold text-[#202124] dark:text-foreground">{value}</span>
    </div>
  )
}

function routeItems(route: ProjectProductRoute, result: ProjectListResult): ProjectItem[] {
  if (route === "hot") return topBy(result.allFiltered, (project) => project.scores.trendScore ?? project.projectMomentum ?? 0).slice(0, 18)
  if (route === "rising") return topBy(result.allFiltered, (project) => project.starGrowth7d ?? project.starGrowth24h ?? 0).slice(0, 18)
  if (route === "tools") return result.allFiltered.filter((project) => project.sources?.includes("github") ?? Boolean(project.repoUrl)).slice(0, 18)
  if (route === "cases") return topBy(result.allFiltered, evidenceScore).slice(0, 18)
  if (route === "lab") return topBy(result.allFiltered, (project) => Date.parse(project.firstSeenAt ?? project.createdAt ?? project.updatedAt ?? "") || 0).slice(0, 18)
  if (route === "watchlist") {
    return topBy(result.allFiltered, (project) => (project.qualityScore ?? project.scores.qualityScore ?? 0) + evidenceScore(project) + (project.scores.activityScore ?? 0)).slice(0, 24)
  }
  return result.items
}

function filterCollection(items: ProjectItem[], params: ProjectListParams) {
  return topBy(
    items.filter((project) => {
      if (params.category && !project.categories.includes(params.category as ProjectCategory)) return false
      return true
    }),
    (project) => project.scores.trendScore ?? project.projectMomentum ?? project.stars ?? 0
  )
}

function topBy(items: ProjectItem[], score: (project: ProjectItem) => number): ProjectItem[] {
  return [...items].sort((left, right) => score(right) - score(left))
}

function evidenceScore(project: ProjectItem): number {
  return project.relationCounts.papers * 3 + project.relationCounts.news * 2 + project.relationCounts.community
}
