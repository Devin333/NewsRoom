"use client"

import Link from "next/link"
import { ArrowRight, Binoculars, Boxes, FlaskConical, Flame, FolderKanban, GitBranch, Search, Sparkles, Star } from "lucide-react"
import type { ComponentType } from "react"
import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  PROJECT_PRODUCT_SECTIONS,
  addProjectWatchlistItem,
  answerProjectLabQuestion,
  fetchProjectProductSection,
  fetchProjectsHome,
  generateProjectLabSolution,
  projectProductSection,
  startProjectLabSession,
} from "@/lib/projects/api"
import { formatScore, labelize } from "@/features/projects/components/project-format"
import { ProjectProductCard } from "@/features/projects/components/project-product-card"
import { ProjectDegradedNotice, ProjectEmptyState, ProjectErrorState, ProjectLoadingState, ProjectSourceLine } from "@/features/projects/components/project-product-state"
import type {
  ProjectProductRoute,
  ProjectProductSection,
  ProjectsApiCaseResult,
  ProjectsApiCollectionResult,
  ProjectsApiHomeResult,
  ProjectsApiListResult,
  ProjectsApiMeta,
  ProjectsApiProject,
  ProjectsApiToolResult,
  ProjectsApiWatchlistResult,
  ProjectsLabSession,
  ProjectsLabSolutionResult,
} from "@/types/projects"

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

export function ProjectsProductPage({ route }: ProjectsProductPageProps) {
  const section = useMemo(() => projectProductSection(route), [route])
  const [query, setQuery] = useState("")
  const queryParams = useMemo(() => ({ q: query.trim() || undefined, limit: route === "home" ? 6 : 18 }), [query, route])

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["projects", "product-v1", route, queryParams],
    queryFn: () =>
      route === "home"
        ? fetchProjectsHome({ limit: queryParams.limit })
        : fetchProjectProductSection(route, { params: queryParams }),
  })

  if (isLoading) return <ProjectLoadingState title={route === "home" ? "Loading Projects home" : `Loading ${section.title}`} />
  if (isError) return <ProjectErrorState message={error instanceof Error ? error.message : undefined} onRetry={() => refetch()} />
  if (!data) return <ProjectEmptyState />

  const meta = getMeta(data)
  return (
    <main className="space-y-9 font-papers-research">
      <ProjectHero section={section} route={route} data={data} query={query} onQueryChange={setQuery} isFetching={isFetching} />
      {meta ? <ProjectDegradedNotice meta={meta} /> : null}
      <RouteContent route={route} data={data} onRefresh={() => void refetch()} />
    </main>
  )
}

function ProjectHero({
  section,
  route,
  data,
  query,
  onQueryChange,
  isFetching,
}: {
  section: ProjectProductSection
  route: ProjectProductRoute
  data: ProductData
  query: string
  onQueryChange: (value: string) => void
  isFetching: boolean
}) {
  const Icon = routeIcons[route]
  const meta = getMeta(data)
  const lead = firstProject(data)

  return (
    <section className="grid gap-8 py-8 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-end">
      <div className="min-w-0">
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <Badge variant="info">Projects API v1</Badge>
          <Badge variant="muted">Real Project Radar data</Badge>
          {isFetching ? <Badge variant="muted">Refreshing</Badge> : null}
        </div>
        <h1 className="max-w-5xl text-5xl font-black leading-none tracking-normal text-[#202124] sm:text-6xl lg:text-7xl dark:text-foreground">
          {section.title}
        </h1>
        <p className="mt-6 max-w-3xl text-base leading-7 text-[#4b5563] dark:text-muted-foreground">{section.description}</p>
        <div className="mt-7 flex flex-wrap gap-2">
          <HeroPill label="Projects" value={projectCount(data)} />
          <HeroPill label="Cases" value={caseCount(data)} />
          <HeroPill label="Collections" value={collectionCount(data)} />
          <HeroPill label="State" value={meta?.data_state ?? "empty"} />
        </div>
        <div className="mt-6 max-w-2xl">
          <label className="sr-only" htmlFor="projects-product-search">
            Search projects
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="projects-product-search"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              className="h-11 rounded-md bg-white pl-9 dark:bg-card"
              placeholder="Search real projects, tools, cases, or module themes"
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
            <p className="text-xs font-semibold uppercase text-[#667085] dark:text-muted-foreground">Current focus</p>
            {lead ? (
              <>
                <h2 className="mt-2 line-clamp-2 text-lg font-semibold text-[#202124] dark:text-foreground">{lead.name}</h2>
                <p className="mt-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">
                  Score {formatScore(lead.hot_score ?? lead.rising_score ?? undefined)} / Sources {lead.source_count}
                </p>
                <Button asChild className="mt-4" size="sm">
                  <Link href={`/projects/${encodeURIComponent(lead.slug)}`}>
                    View project
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </>
            ) : (
              <p className="mt-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">No real Project Radar output is available yet.</p>
            )}
          </div>
        </div>
      </aside>
    </section>
  )
}

function RouteContent({ route, data, onRefresh }: { route: ProjectProductRoute; data: ProductData; onRefresh: () => void }) {
  if (route === "home") return <ProjectsHome data={data as ProjectsApiHomeResult} />
  if (route === "tools") return <ToolsView data={data as ProjectsApiToolResult} />
  if (route === "cases") return <CasesView data={data as ProjectsApiCaseResult} />
  if (route === "collections") return <CollectionsView data={data as ProjectsApiCollectionResult} />
  if (route === "watchlist") return <WatchlistView data={data as ProjectsApiWatchlistResult} onChanged={onRefresh} />
  if (route === "lab") return <LabView data={data} />
  return <ProjectGrid projects={(data as ProjectsApiListResult).items} meta={(data as ProjectsApiListResult).meta} />
}

function ProjectsHome({ data }: { data: ProjectsApiHomeResult }) {
  const projects = uniqueProjects([...data.hot, ...data.rising, ...data.tools])
  if (!projects.length && !data.cases.length && !data.collections.length) return <ProjectEmptyState />
  return (
    <section className="space-y-8">
      <SectionHeader title="Hot and rising" href="/projects/hot" />
      <ProjectGrid projects={projects.slice(0, 6)} meta={data.meta} />
      <SectionHeader title="Cases and collections" href="/projects/cases" />
      <div className="grid gap-4 lg:grid-cols-2">
        {data.cases.slice(0, 4).map((item) => (
          <SimplePanel key={item.id} title={String(item.title)} subtitle={String(item.module_type)} body={String(item.design_summary ?? item.problem ?? "")} />
        ))}
        {data.collections.slice(0, 4).map((item) => (
          <SimplePanel key={item.id} title={item.title} subtitle={`${item.item_count ?? 0} items`} body={item.description} href={`/projects/collections`} />
        ))}
      </div>
    </section>
  )
}

function ToolsView({ data }: { data: ProjectsApiToolResult }) {
  if (!data.tools.length) return <ProjectEmptyState title="No Real-Derived Tools" />
  return (
    <section className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
      {data.tools.map((tool) => (
        <SimplePanel
          key={tool.project.id}
          title={tool.project.name}
          subtitle={`${labelize(tool.profile.tool_type)} / ${tool.profile.integration_difficulty}`}
          body={tool.fit_reason ?? tool.project.description ?? ""}
          href={`/projects/${tool.project.slug}`}
        />
      ))}
    </section>
  )
}

function CasesView({ data }: { data: ProjectsApiCaseResult }) {
  if (!data.cases.length) return <ProjectEmptyState title="No Real-Derived Cases" />
  return (
    <section className="grid gap-4 lg:grid-cols-2">
      {data.cases.map((item) => (
        <SimplePanel key={item.id} title={item.title} subtitle={`${item.business_domain} / ${item.module_type}`} body={String(item.design_summary ?? item.problem ?? "")} />
      ))}
    </section>
  )
}

function CollectionsView({ data }: { data: ProjectsApiCollectionResult }) {
  if (!data.collections.length) return <ProjectEmptyState title="No Real-Derived Collections" />
  return (
    <section className="grid gap-4 lg:grid-cols-2">
      {data.collections.map((item) => (
        <SimplePanel key={item.id} title={item.title} subtitle={`${item.item_count ?? 0} items`} body={item.description} />
      ))}
    </section>
  )
}

function WatchlistView({ data, onChanged }: { data: ProjectsApiWatchlistResult; onChanged: () => void }) {
  const [projectId, setProjectId] = useState("")
  const [reason, setReason] = useState("")
  const [priority, setPriority] = useState<"low" | "medium" | "high">("medium")
  const addWatch = useMutation({
    mutationFn: () =>
      addProjectWatchlistItem({
        project_id: projectId.trim(),
        watch_reason: reason.trim(),
        priority,
      }),
    onSuccess: () => {
      setProjectId("")
      setReason("")
      setPriority("medium")
      onChanged()
    },
  })

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,24rem)_1fr]">
      <form
        className="space-y-3 rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card"
        onSubmit={(event) => {
          event.preventDefault()
          if (!projectId.trim() || !reason.trim()) return
          addWatch.mutate()
        }}
      >
        <h2 className="text-base font-semibold text-[#202124] dark:text-foreground">Add Watchlist Item</h2>
        <Input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="Real project id" />
        <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Watch reason" />
        <select
          value={priority}
          onChange={(event) => setPriority(event.target.value as "low" | "medium" | "high")}
          className="h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
        >
          <option value="low">Low priority</option>
          <option value="medium">Medium priority</option>
          <option value="high">High priority</option>
        </select>
        <Button type="submit" disabled={!projectId.trim() || !reason.trim() || addWatch.isPending}>
          {addWatch.isPending ? "Saving" : "Watch Project"}
        </Button>
        {addWatch.isError ? <p className="text-sm text-destructive">{addWatch.error instanceof Error ? addWatch.error.message : "Watchlist update failed"}</p> : null}
      </form>
      <div className="grid gap-4 lg:grid-cols-2">
        {data.items.length ? (
          data.items.map((item) => (
            <SimplePanel key={item.id} title={item.project_id} subtitle={`${item.priority} / ${item.status}`} body={item.watch_reason} />
          ))
        ) : (
          <ProjectEmptyState title="No Watchlist Items" />
        )}
      </div>
    </section>
  )
}

function LabView({ data }: { data: ProductData }) {
  const meta = getMeta(data)
  const [problem, setProblem] = useState("")
  const [answer, setAnswer] = useState("")
  const [session, setSession] = useState<ProjectsLabSession | null>(null)
  const [solution, setSolution] = useState<ProjectsLabSolutionResult | null>(null)
  const selectedCaseIds = useMemo(() => ("cases" in data ? data.cases.slice(0, 3).map((item) => item.id) : []), [data])
  const activeQuestion = session?.questions.find((question) => question.answered_value === undefined || question.answered_value === null)

  const startSession = useMutation({
    mutationFn: () =>
      startProjectLabSession({
        user_problem: problem.trim(),
        selected_case_ids: selectedCaseIds,
      }),
    onSuccess: (result) => {
      setSession(result.session)
      setSolution(null)
      setAnswer("")
    },
  })
  const answerQuestion = useMutation({
    mutationFn: () => {
      if (!session || !activeQuestion) throw new Error("No active Lab question")
      return answerProjectLabQuestion(session.id, { question_id: activeQuestion.id, answer: answer.trim() })
    },
    onSuccess: (result) => {
      setSession(result.session)
      setAnswer("")
    },
  })
  const generateSolution = useMutation({
    mutationFn: () => {
      if (!session) throw new Error("No active Lab session")
      return generateProjectLabSolution(session.id)
    },
    onSuccess: (result) => {
      setSession(result.session)
      setSolution(result)
    },
  })

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,28rem)_1fr]">
      <form
        className="space-y-3 rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card"
        onSubmit={(event) => {
          event.preventDefault()
          if (!problem.trim()) return
          startSession.mutate()
        }}
      >
        <h2 className="text-base font-semibold text-[#202124] dark:text-foreground">Start Lab Session</h2>
        {meta ? <ProjectSourceLine meta={meta} /> : null}
        <textarea
          value={problem}
          onChange={(event) => setProblem(event.target.value)}
          className="min-h-28 w-full rounded-md border border-input bg-card px-3 py-2 text-sm"
          placeholder="Describe the module or product problem"
        />
        <Button type="submit" disabled={!problem.trim() || startSession.isPending}>
          {startSession.isPending ? "Starting" : "Start Session"}
        </Button>
        {startSession.isError ? <p className="text-sm text-destructive">{startSession.error instanceof Error ? startSession.error.message : "Lab session failed"}</p> : null}
      </form>
      <div className="space-y-4 rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
        <h2 className="text-base font-semibold text-[#202124] dark:text-foreground">Session Workspace</h2>
        {session ? (
          <>
            <div className="rounded-md bg-secondary/60 p-3 text-sm">
              <p className="font-medium text-[#202124] dark:text-foreground">{session.current_stage}</p>
              <p className="mt-1 text-muted-foreground">{session.user_problem}</p>
            </div>
            {activeQuestion ? (
              <div className="space-y-3">
                <p className="text-sm font-medium text-[#202124] dark:text-foreground">{activeQuestion.question}</p>
                <Input value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="Answer clarification" />
                <Button
                  type="button"
                  variant="outline"
                  disabled={!answer.trim() || answerQuestion.isPending}
                  onClick={() => answerQuestion.mutate()}
                >
                  {answerQuestion.isPending ? "Saving Answer" : "Answer"}
                </Button>
              </div>
            ) : null}
            <Button type="button" disabled={generateSolution.isPending} onClick={() => generateSolution.mutate()}>
              {generateSolution.isPending ? "Generating" : "Generate Solution"}
            </Button>
            {answerQuestion.isError ? <p className="text-sm text-destructive">{answerQuestion.error instanceof Error ? answerQuestion.error.message : "Answer failed"}</p> : null}
            {generateSolution.isError ? <p className="text-sm text-destructive">{generateSolution.error instanceof Error ? generateSolution.error.message : "Solution failed"}</p> : null}
            {solution ? (
              <pre className="max-h-72 overflow-auto rounded-md bg-[#111827] p-3 text-xs text-white">{JSON.stringify(solution.solution, null, 2)}</pre>
            ) : null}
          </>
        ) : (
          <p className="text-sm leading-6 text-muted-foreground">No active Lab session yet.</p>
        )}
      </div>
    </section>
  )
}

function ProjectGrid({ projects, meta }: { projects: ProjectsApiProject[]; meta: ProjectsApiMeta }) {
  if (!projects.length) return <ProjectEmptyState />
  return (
    <section className="space-y-4">
      <ProjectSourceLine meta={meta} />
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {projects.map((project) => (
          <ProjectProductCard key={project.id} project={project} />
        ))}
      </div>
    </section>
  )
}

function SectionHeader({ title, href }: { title: string; href: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <h2 className="text-xl font-semibold text-[#202124] dark:text-foreground">{title}</h2>
      <Button asChild variant="outline" size="sm">
        <Link href={href}>
          Open
          <ArrowRight className="size-4" />
        </Link>
      </Button>
    </div>
  )
}

function SimplePanel({ title, subtitle, body, href }: { title: string; subtitle: string; body: string; href?: string }) {
  const content = (
    <article className="h-full rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm transition-colors hover:border-primary/40 dark:border-border dark:bg-card">
      <p className="text-xs font-semibold uppercase text-[#667085] dark:text-muted-foreground">{subtitle}</p>
      <h3 className="mt-2 text-base font-semibold text-[#202124] dark:text-foreground">{title}</h3>
      <p className="mt-2 line-clamp-3 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">{body || "No additional text was available from the real Project Radar artifact."}</p>
    </article>
  )
  return href ? <Link href={href}>{content}</Link> : content
}

function HeroPill({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[#dbe5dd] bg-white/90 px-3 py-1 text-xs text-[#334155]/70 shadow-sm dark:border-border dark:bg-card dark:text-muted-foreground">
      <span className="font-medium text-[#334155] dark:text-foreground">{label}</span>
      {value}
    </span>
  )
}

type ProductData =
  | ProjectsApiHomeResult
  | ProjectsApiListResult
  | ProjectsApiToolResult
  | ProjectsApiCaseResult
  | ProjectsApiCollectionResult
  | ProjectsApiWatchlistResult

function getMeta(data: ProductData): ProjectsApiMeta | undefined {
  return "meta" in data ? data.meta : undefined
}

function firstProject(data: ProductData): ProjectsApiProject | undefined {
  if ("hot" in data) return data.hot[0] ?? data.rising[0] ?? data.tools[0]
  if ("page" in data && "items" in data) return data.items[0]
  if ("tools" in data) return data.tools[0]?.project
  return undefined
}

function projectCount(data: ProductData): number {
  if ("hot" in data) return uniqueProjects([...data.hot, ...data.rising, ...data.tools]).length
  if ("page" in data && "items" in data) return data.page.total
  if ("tools" in data) return data.tools.length
  return 0
}

function caseCount(data: ProductData): number {
  if ("cases" in data) return data.cases.length
  return 0
}

function collectionCount(data: ProductData): number {
  if ("collections" in data) return data.collections.length
  return 0
}

function uniqueProjects(projects: ProjectsApiProject[]): ProjectsApiProject[] {
  const seen = new Set<string>()
  const result: ProjectsApiProject[] = []
  for (const project of projects) {
    if (seen.has(project.id)) continue
    seen.add(project.id)
    result.push(project)
  }
  return result
}
