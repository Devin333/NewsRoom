"use client"

import Link from "next/link"
import { ArrowRight, Binoculars, Boxes, FlaskConical, Flame, FolderKanban, GitBranch, Search, Sparkles, Star } from "lucide-react"
import type { ComponentType } from "react"
import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useSearchParams } from "next/navigation"
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
  recordProjectInteraction,
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
  const [hasApi, setHasApi] = useState(false)
  const [hasCli, setHasCli] = useState(false)
  const [hasPython, setHasPython] = useState(false)
  const [hasDocker, setHasDocker] = useState(false)
  const [difficulty, setDifficulty] = useState<string>("")

  const filtered = data.tools.filter((tool) => {
    if (hasApi && !tool.profile.has_api) return false
    if (hasCli && !tool.profile.has_cli) return false
    if (hasPython && !tool.profile.has_python_sdk) return false
    if (hasDocker && !tool.profile.has_docker) return false
    if (difficulty && tool.profile.integration_difficulty !== difficulty) return false
    return true
  })

  if (!data.tools.length) return <ProjectEmptyState title="No Real-Derived Tools" />
  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,16rem)_1fr]">
      <div className="rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card h-fit">
        <h3 className="text-sm font-semibold text-[#202124] dark:text-foreground mb-3">Filters</h3>
        <div className="space-y-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={hasApi} onChange={(e) => setHasApi(e.target.checked)} className="rounded" />
            <span className="text-sm text-[#4b5563] dark:text-muted-foreground">Has API</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={hasCli} onChange={(e) => setHasCli(e.target.checked)} className="rounded" />
            <span className="text-sm text-[#4b5563] dark:text-muted-foreground">Has CLI</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={hasPython} onChange={(e) => setHasPython(e.target.checked)} className="rounded" />
            <span className="text-sm text-[#4b5563] dark:text-muted-foreground">Python SDK</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={hasDocker} onChange={(e) => setHasDocker(e.target.checked)} className="rounded" />
            <span className="text-sm text-[#4b5563] dark:text-muted-foreground">Docker</span>
          </label>
          <div className="pt-2 border-t border-[#e5e7eb] dark:border-border">
            <label className="text-xs font-semibold text-[#667085] dark:text-muted-foreground block mb-2">Difficulty</label>
            <select
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
              className="w-full rounded-md border border-input bg-card px-2 py-1 text-sm"
            >
              <option value="">All</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </div>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {filtered.map((tool) => (
          <SimplePanel
            key={tool.project.id}
            title={tool.project.name}
            subtitle={`${labelize(tool.profile.tool_type)} / ${tool.profile.integration_difficulty}`}
            body={tool.fit_reason ?? tool.project.description ?? ""}
            href={`/projects/tools/${encodeURIComponent(tool.project.id)}`}
          />
        ))}
      </div>
    </section>
  )
}

function CasesView({ data }: { data: ProjectsApiCaseResult }) {
  const [q, setQ] = useState("")
  const [domain, setDomain] = useState("")
  const [moduleType, setModuleType] = useState("")
  const [difficulty, setDifficulty] = useState("")

  const domains = Array.from(new Set(data.cases.map((c) => c.business_domain).filter(Boolean)))
  const moduleTypes = Array.from(new Set(data.cases.map((c) => c.module_type).filter(Boolean)))

  const filtered = data.cases.filter((c) => {
    if (q && !`${c.title} ${c.design_summary ?? ""} ${c.problem ?? ""}`.toLowerCase().includes(q.toLowerCase())) return false
    if (domain && c.business_domain !== domain) return false
    if (moduleType && c.module_type !== moduleType) return false
    if (difficulty && (c as any).difficulty !== difficulty) return false
    return true
  })

  if (!data.cases.length) return <ProjectEmptyState title="No Real-Derived Cases" />
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-3 rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
        <div className="relative flex-1 min-w-48">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-9 h-9" placeholder="Search cases" />
        </div>
        <select value={domain} onChange={(e) => setDomain(e.target.value)} className="rounded-md border border-input bg-card px-2 py-1 text-sm">
          <option value="">All domains</option>
          {domains.map((d) => <option key={d} value={d}>{labelize(d)}</option>)}
        </select>
        <select value={moduleType} onChange={(e) => setModuleType(e.target.value)} className="rounded-md border border-input bg-card px-2 py-1 text-sm">
          <option value="">All modules</option>
          {moduleTypes.map((m) => <option key={m} value={m}>{labelize(m)}</option>)}
        </select>
        <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className="rounded-md border border-input bg-card px-2 py-1 text-sm">
          <option value="">All difficulty</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
      </div>
      {!filtered.length ? <ProjectEmptyState title="No matching cases" /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          {filtered.map((item) => (
            <Link key={item.id} href={`/projects/cases/${encodeURIComponent(item.id)}`}>
              <article className="h-full rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm transition-colors hover:border-primary/40 dark:border-border dark:bg-card">
                <div className="flex flex-wrap gap-2 mb-2">
                  <Badge variant="info">{labelize(item.module_type)}</Badge>
                  <Badge variant="muted">{labelize(item.business_domain)}</Badge>
                  {(item as any).difficulty && <Badge variant="muted">{(item as any).difficulty}</Badge>}
                  {(item as any).migration_level && <Badge variant="muted">reuse: {(item as any).migration_level}</Badge>}
                </div>
                <h3 className="text-base font-semibold text-[#202124] dark:text-foreground">{item.title}</h3>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">
                  {String(item.design_summary ?? item.problem ?? "")}
                </p>
                {(item as any).suitable_for?.length > 0 && (
                  <p className="mt-2 text-xs text-[#667085] dark:text-muted-foreground">
                    For: {(item as any).suitable_for.slice(0, 3).join(", ")}
                  </p>
                )}
              </article>
            </Link>
          ))}
        </div>
      )}
    </section>
  )
}

function CollectionsView({ data }: { data: ProjectsApiCollectionResult }) {
  const searchParams = useSearchParams()
  const [q, setQ] = useState("")
  const [tag, setTag] = useState(searchParams.get("tag") ?? "")

  const allTags = Array.from(new Set(data.collections.flatMap((c) => (c as any).tags ?? []).filter(Boolean)))

  const filtered = data.collections.filter((c) => {
    if (q && !`${c.title} ${c.description}`.toLowerCase().includes(q.toLowerCase())) return false
    if (tag && !((c as any).tags ?? []).includes(tag)) return false
    return true
  })

  if (!data.collections.length) return <ProjectEmptyState title="No Real-Derived Collections" />
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-3 rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
        <div className="relative flex-1 min-w-48">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-9 h-9" placeholder="Search collections" />
        </div>
        {allTags.length > 0 && (
          <select value={tag} onChange={(e) => setTag(e.target.value)} className="rounded-md border border-input bg-card px-2 py-1 text-sm">
            <option value="">All tags</option>
            {allTags.map((t) => <option key={t} value={t}>{labelize(t)}</option>)}
          </select>
        )}
      </div>
      {!filtered.length ? <ProjectEmptyState title="No matching collections" /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          {filtered.map((item) => (
            <Link key={item.id} href={`/projects/collections/${encodeURIComponent(item.slug)}`}>
              <article className="h-full rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm transition-colors hover:border-primary/40 dark:border-border dark:bg-card">
                <div className="flex flex-wrap gap-2 mb-2">
                  {(item as any).collection_type && <Badge variant="info">{labelize((item as any).collection_type)}</Badge>}
                  <Badge variant="muted">{item.item_count ?? 0} items</Badge>
                  {((item as any).tags ?? []).slice(0, 3).map((t: string) => (
                    <Badge key={t} variant="muted">{labelize(t)}</Badge>
                  ))}
                </div>
                <h3 className="text-base font-semibold text-[#202124] dark:text-foreground">{item.title}</h3>
                <p className="mt-2 line-clamp-3 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">{item.description}</p>
                {(item as any).learning_goals?.length > 0 && (
                  <p className="mt-2 text-xs text-[#667085] dark:text-muted-foreground">
                    Goals: {(item as any).learning_goals.slice(0, 2).join("; ")}
                  </p>
                )}
              </article>
            </Link>
          ))}
        </div>
      )}
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
      void recordProjectInteraction({
        event_type: "watch_added",
        target_type: "project",
        target_id: projectId.trim(),
        action_value: priority,
      })
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
          data.items.map((item) => <WatchItemCard key={item.id} item={item} />)
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
      void recordProjectInteraction({
        event_type: "lab_started",
        target_type: "lab_session",
        target_id: result.session.id,
        query_text: problem.trim(),
      })
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
      void recordProjectInteraction({
        event_type: "question_answered",
        target_type: "lab_session",
        target_id: session?.id,
        action_value: activeQuestion?.id,
      })
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
      void recordProjectInteraction({
        event_type: "solution_generated",
        target_type: "lab_session",
        target_id: session?.id,
      })
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
            <LabGraph graph={(session as any).graph_state} />
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
              <div className="space-y-3">
                <Button asChild variant="outline" size="sm">
                  <Link href={`/projects/lab/${encodeURIComponent(solution.session.id)}`}>Open Session Detail</Link>
                </Button>
                <pre className="max-h-72 overflow-auto rounded-md bg-[#111827] p-3 text-xs text-white">{JSON.stringify(solution.solution, null, 2)}</pre>
              </div>
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

function WatchItemCard({ item }: { item: ProjectsApiWatchlistItem }) {
  const signals: any[] = (item as any).signals ?? []
  const pc = item.priority === "high" ? "text-red-600" : item.priority === "medium" ? "text-amber-600" : "text-[#667085]"
  return (
    <article className="rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-[#667085]">{item.project_id}</p>
          <p className="mt-1 text-sm font-semibold text-[#202124] dark:text-foreground">{item.watch_reason}</p>
        </div>
        <span className={`shrink-0 text-xs font-semibold ${pc}`}>{item.priority}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge variant={item.status === "active" ? "info" : "muted"}>{item.status}</Badge>
        {((item as any).watch_topics ?? []).map((t: string) => <Badge key={t} variant="muted">{t}</Badge>)}
      </div>
      {(item as any).last_change_summary && (
        <p className="mt-2 text-xs text-[#4b5563] dark:text-muted-foreground">{(item as any).last_change_summary}</p>
      )}
      {signals.length > 0 && (
        <div className="mt-3 border-t border-[#e5e7eb] pt-3 dark:border-border">
          <p className="mb-2 text-xs font-semibold text-[#667085]">Signals</p>
          <div className="space-y-2">
            {signals.map((s: any, i: number) => (
              <div key={i} className="flex items-start gap-2">
                <span className={`mt-1 size-2 shrink-0 rounded-full ${s.severity === "high" ? "bg-red-500" : s.severity === "medium" ? "bg-amber-400" : "bg-[#d1d5db]"}`} />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-[#202124] dark:text-foreground">{s.title}</p>
                  <p className="text-xs text-[#667085]">{s.summary}</p>
                  {s.source_url && <a href={s.source_url} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline">source ↗</a>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </article>
  )
}

const NODE_COLORS: Record<string, string> = {
  user_problem: "#0f172a", case: "#2563eb", solution: "#16a34a",
  question: "#d97706", feedback: "#7c3aed", pattern: "#0891b2", component: "#be185d",
}

function LabGraph({ graph }: { graph?: any }) {
  if (!graph?.nodes?.length) return null
  const nodes: any[] = graph.nodes
  const edges: any[] = graph.edges ?? []
  const focused: string[] = graph.focused_node_ids ?? []
  const cx = 200, cy = 120, r = 90
  const pos: Record<string, { x: number; y: number }> = {}
  nodes.forEach((n: any, i: number) => {
    const a = (2 * Math.PI * i) / nodes.length - Math.PI / 2
    pos[n.id] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }
  })
  return (
    <div className="rounded-md border border-[#e5e7eb] bg-[#f8fafc] p-2 dark:border-border dark:bg-background">
      <p className="mb-1 text-xs font-semibold text-[#667085]">Graph — {nodes.length} nodes, {edges.length} edges</p>
      <svg viewBox="0 0 400 240" className="w-full" style={{ maxHeight: 200 }}>
        {edges.map((e: any, i: number) => {
          const s = pos[e.source_id], t = pos[e.target_id]
          return s && t ? <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="#d1d5db" strokeWidth={1.5} /> : null
        })}
        {nodes.map((n: any) => {
          const p = pos[n.id]; if (!p) return null
          const color = NODE_COLORS[n.node_type] ?? "#6b7280"
          return (
            <g key={n.id}>
              <circle cx={p.x} cy={p.y} r={focused.includes(n.id) ? 10 : 7} fill={color} opacity={focused.includes(n.id) ? 1 : 0.7} />
              <text x={p.x} y={p.y + 18} textAnchor="middle" fontSize={8} fill="#374151">{n.title.slice(0, 14)}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
