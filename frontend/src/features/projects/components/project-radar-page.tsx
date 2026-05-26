"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { PageHeader } from "@/components/layout/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { ProjectCard } from "@/features/projects/components/project-card"
import { ProjectFilterPanel } from "@/features/projects/components/project-filter-panel"
import { ProjectToolbar } from "@/features/projects/components/project-toolbar"
import { fetchProjects } from "@/lib/projects/api"
import type { ProjectListParams, ProjectListResult, ProjectSort } from "@/types/projects"

const SORT_TABS: Array<{ value: ProjectSort; label: string }> = [
  { value: "trending", label: "趋势" },
  { value: "newest", label: "最新" },
  { value: "stars", label: "Stars" },
  { value: "growth", label: "增长" },
  { value: "quality", label: "质量" },
]

export function ProjectRadarPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const [data, setData] = useState<ProjectListResult | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const filters = useMemo(() => filtersFromSearchParams(searchParams), [searchParams])

  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    setError(null)
    fetchProjects(filters, { signal: controller.signal })
      .then((result) => setData(result))
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(requestError instanceof Error ? requestError.message : "项目雷达请求失败")
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      })
    return () => controller.abort()
  }, [filters])

  function setFilters(patch: Partial<ProjectListParams>) {
    const next = { ...filters, ...patch }
    const query = filtersToSearchParams(next).toString()
    router.replace(query ? `/projects?${query}` : "/projects", { scroll: false })
  }

  if (isLoading && !data) {
    return <PageSkeleton />
  }

  if (error && !data) {
    return <ErrorState title="项目雷达加载失败" message={error} onRetry={() => setFilters({})} />
  }

  if (!data) {
    return <EmptyState title="项目雷达为空" description="还没有可展示的 project_radar 数据。" />
  }

  const totalPages = Math.max(1, Math.ceil(data.page.total / data.page.pageSize))

  return (
    <main className="space-y-8">
      <PageHeader
        eyebrow="Project Radar"
        title="项目雷达"
        description="追踪正在升温的 AI 工程项目、框架、工具与代码实现。"
        actions={
          <Badge variant={data.dataState === "ready" ? "success" : data.dataState === "empty" ? "muted" : "warning"}>
            {data.source === "backend" ? "Backend" : data.source === "artifact" ? "Artifact" : "Empty"}
          </Badge>
        }
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {data.metrics.map((metric) => (
          <Card key={metric.label}>
            <CardContent className="p-4">
              <p className="font-mono text-[11px] uppercase text-muted-foreground">{metric.label}</p>
              <p className="mt-2 text-2xl font-semibold text-foreground">{metric.value}</p>
              {metric.hint ? <p className="mt-1 text-xs text-muted-foreground">{metric.hint}</p> : null}
            </CardContent>
          </Card>
        ))}
      </section>

      {data.notices.length ? (
        <div className="rounded-md border border-warning/30 bg-warning/10 px-4 py-3 text-sm leading-6 text-foreground">
          {data.notices.join(" ")}
        </div>
      ) : null}

      <div className="grid gap-8 xl:grid-cols-[14rem_minmax(0,1fr)]">
        <div className="hidden xl:block">
          <ProjectFilterPanel filters={filters} options={data.options} onChange={setFilters} />
        </div>

        <section className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center gap-2 border-b border-border pb-4">
            {SORT_TABS.map((tab) => (
              <button
                key={tab.value}
                type="button"
                onClick={() => setFilters({ sort: tab.value, page: 1 })}
                className={
                  (filters.sort ?? "trending") === tab.value
                    ? "rounded-md bg-foreground px-3 py-2 text-xs font-semibold text-background"
                    : "rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                }
              >
                {tab.label}
              </button>
            ))}
          </div>

          <ProjectToolbar filters={filters} onChange={setFilters} onToggleFilters={() => setMobileFiltersOpen((value) => !value)} />

          <div className={mobileFiltersOpen ? "block xl:hidden" : "hidden"}>
            <ProjectFilterPanel filters={filters} options={data.options} onChange={setFilters} />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              显示 {data.items.length} / {data.page.total}
            </span>
            <span>
              第 {data.page.page} / {totalPages} 页
            </span>
          </div>

          {isLoading ? <p className="text-sm text-muted-foreground">正在更新项目列表...</p> : null}
          {error ? <ErrorState title="项目列表刷新失败" message={error} /> : null}

          {data.items.length ? (
            <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
              {data.items.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </div>
          ) : (
            <EmptyState
              title={data.allItems.length ? "没有匹配的项目" : "项目雷达为空"}
              description={data.allItems.length ? "可以换一个搜索词或清空筛选条件。" : "当前没有合法 GitHub 仓库项目可展示。"}
              action={
                data.allItems.length ? (
                  <Button type="button" variant="outline" onClick={() => setFilters({ q: undefined, category: undefined, source: undefined, language: undefined, page: 1 })}>
                    清空筛选
                  </Button>
                ) : null
              }
            />
          )}

          <div className="flex items-center justify-between gap-3">
            <Button type="button" variant="outline" disabled={data.page.page <= 1} onClick={() => setFilters({ page: data.page.page - 1 })}>
              上一页
            </Button>
            <Button type="button" variant="outline" disabled={!data.page.hasNext} onClick={() => setFilters({ page: data.page.page + 1 })}>
              下一页
            </Button>
          </div>
        </section>
      </div>
    </main>
  )
}

function filtersFromSearchParams(searchParams: Pick<URLSearchParams, "get">): ProjectListParams {
  return {
    q: searchParams.get("q") ?? undefined,
    category: searchParams.get("category") as ProjectListParams["category"],
    sort: searchParams.get("sort") as ProjectListParams["sort"],
    source: searchParams.get("source") as ProjectListParams["source"],
    language: searchParams.get("language") as ProjectListParams["language"],
    page: numberParam(searchParams.get("page")),
  }
}

function filtersToSearchParams(filters: ProjectListParams): URLSearchParams {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "" || (key === "page" && value === 1) || (key === "sort" && value === "trending")) {
      continue
    }
    params.set(key, String(value))
  }
  return params
}

function numberParam(value: string | null): number | undefined {
  if (!value) return undefined
  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}
