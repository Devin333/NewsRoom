"use client"

import Link from "next/link"
import { ArrowLeft, ExternalLink } from "lucide-react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  explainProjectCase,
  fetchProjectCaseDetail,
  fetchProjectCollectionDetail,
  fetchProjectLabSession,
  fetchProjectToolDetail,
  fetchProjectV1Detail,
  mapProjectCaseToContext,
  saveProjectLabSession,
} from "@/lib/projects/api"
import type { ProjectsApiCollection, ProjectsApiProjectDetail, ProjectsApiTool } from "@/types/projects"
import { ProjectEmptyState, ProjectErrorState, ProjectLoadingState, ProjectSourceLine } from "@/features/projects/components/project-product-state"
import { formatScore, labelize } from "@/features/projects/components/project-format"

export function ProjectV1DetailPage({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ["projects", "v1-detail", projectId],
    queryFn: () => fetchProjectV1Detail(projectId),
  })
  if (query.isLoading) return <ProjectLoadingState title="Loading Project" />
  if (query.isError) return <ProjectErrorState message={query.error instanceof Error ? query.error.message : undefined} onRetry={() => query.refetch()} />
  if (!query.data) return <ProjectEmptyState />
  return <ProjectV1Detail data={query.data} />
}

export function ProjectToolDetailPage({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: ["projects", "tool-detail", projectId],
    queryFn: () => fetchProjectToolDetail(projectId),
  })
  if (query.isLoading) return <ProjectLoadingState title="Loading Tool" />
  if (query.isError) return <ProjectErrorState message={query.error instanceof Error ? query.error.message : undefined} onRetry={() => query.refetch()} />
  if (!query.data) return <ProjectEmptyState />
  return <ToolDetail tool={query.data} />
}

export function ProjectCaseDetailPage({ caseId }: { caseId: string }) {
  const [context, setContext] = useState("")
  const detail = useQuery({
    queryKey: ["projects", "case-detail", caseId],
    queryFn: () => fetchProjectCaseDetail(caseId),
  })
  const explain = useMutation({
    mutationFn: () => explainProjectCase(caseId, { style: "migration", user_context: context.trim() || undefined }),
  })
  const mapping = useMutation({
    mutationFn: () => mapProjectCaseToContext(caseId, { user_context: context.trim(), constraints: [] }),
  })

  if (detail.isLoading) return <ProjectLoadingState title="Loading Case" />
  if (detail.isError) return <ProjectErrorState message={detail.error instanceof Error ? detail.error.message : undefined} onRetry={() => detail.refetch()} />
  if (!detail.data) return <ProjectEmptyState />
  const item = detail.data
  return (
    <main className="space-y-6 font-papers-research">
      <BackLink href="/projects/cases" label="Cases" />
      <Header title={item.title} eyebrow={`${item.business_domain} / ${item.module_type}`} body={String(item.design_summary ?? item.problem ?? "")} />
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-4">
          <Panel title="Problem" body={String(item.problem ?? "")} />
          <JsonPanel title="Components" value={item.components ?? []} />
          <JsonPanel title="Patterns" value={item.patterns ?? []} />
        </div>
        <aside className="space-y-3 rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
          <h2 className="text-base font-semibold text-[#202124] dark:text-foreground">Apply Context</h2>
          <textarea
            value={context}
            onChange={(event) => setContext(event.target.value)}
            className="min-h-28 w-full rounded-md border border-input bg-card px-3 py-2 text-sm"
            placeholder="Target module context"
          />
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => explain.mutate()} disabled={explain.isPending}>
              Explain
            </Button>
            <Button type="button" onClick={() => mapping.mutate()} disabled={!context.trim() || mapping.isPending}>
              Map
            </Button>
          </div>
          {explain.data ? <Panel title="Explanation" body={explain.data.summary} /> : null}
          {mapping.data ? <JsonPanel title={`Fit ${formatScore(mapping.data.fit_score)}`} value={mapping.data} /> : null}
        </aside>
      </section>
    </main>
  )
}

export function ProjectCollectionDetailPage({ slug }: { slug: string }) {
  const query = useQuery({
    queryKey: ["projects", "collection-detail", slug],
    queryFn: () => fetchProjectCollectionDetail(slug),
  })
  if (query.isLoading) return <ProjectLoadingState title="Loading Collection" />
  if (query.isError) return <ProjectErrorState message={query.error instanceof Error ? query.error.message : undefined} onRetry={() => query.refetch()} />
  if (!query.data) return <ProjectEmptyState />
  return <CollectionDetail collection={query.data} />
}

export function ProjectLabSessionPage({ sessionId }: { sessionId: string }) {
  const query = useQuery({
    queryKey: ["projects", "lab-session", sessionId],
    queryFn: () => fetchProjectLabSession(sessionId),
  })
  const save = useMutation({
    mutationFn: () => saveProjectLabSession(sessionId, { status: "saved", note: "Saved from Projects Lab detail." }),
    onSuccess: () => query.refetch(),
  })
  if (query.isLoading) return <ProjectLoadingState title="Loading Lab Session" />
  if (query.isError) return <ProjectErrorState message={query.error instanceof Error ? query.error.message : undefined} onRetry={() => query.refetch()} />
  if (!query.data) return <ProjectEmptyState />
  const session = query.data.session
  return (
    <main className="space-y-6 font-papers-research">
      <BackLink href="/projects/lab" label="Lab" />
      <Header title="Lab Session" eyebrow={session.current_stage} body={session.user_problem} />
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
          Save Session
        </Button>
      </div>
      <section className="grid gap-4 lg:grid-cols-2">
        <JsonPanel title="Requirement Profile" value={session.requirement_profile ?? {}} />
        <JsonPanel title="Graph" value={session.graph_state ?? {}} />
        <JsonPanel title="Questions" value={session.questions} />
        <JsonPanel title="Solution" value={session.solution_json ?? session.generated_solution ?? {}} />
      </section>
    </main>
  )
}

function ProjectV1Detail({ data }: { data: ProjectsApiProjectDetail }) {
  const project = data.project
  return (
    <main className="space-y-6 font-papers-research">
      <BackLink href="/projects" label="Projects" />
      <Header title={project.name} eyebrow={project.project_type} body={project.description ?? project.tagline ?? ""} />
      <ProjectSourceLine meta={data.meta} />
      <section className="grid gap-4 lg:grid-cols-3">
        <Panel title="Hot score" body={formatScore(project.hot_score ?? undefined)} />
        <Panel title="Rising score" body={formatScore(project.rising_score ?? undefined)} />
        <Panel title="Sources" body={String(project.source_count)} />
      </section>
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-4">
          <JsonPanel title="Capabilities" value={data.capabilities} />
          <JsonPanel title="Cases" value={data.cases} />
          <JsonPanel title="Metrics" value={data.metrics} />
        </div>
        <aside className="space-y-4">
          <LinkPanel project={project} />
          <JsonPanel title="Watch" value={data.watch_status ?? { status: "not_watched" }} />
          <JsonPanel title="Recommended Actions" value={data.recommended_actions ?? []} />
        </aside>
      </section>
    </main>
  )
}

function ToolDetail({ tool }: { tool: ProjectsApiTool }) {
  return (
    <main className="space-y-6 font-papers-research">
      <BackLink href="/projects/tools" label="Tools" />
      <Header title={tool.project.name} eyebrow={tool.profile.tool_type} body={tool.fit_reason ?? tool.project.description ?? ""} />
      <section className="grid gap-4 lg:grid-cols-2">
        <JsonPanel title="Integration Profile" value={tool.profile} />
        <JsonPanel title="Capabilities" value={tool.capabilities} />
      </section>
    </main>
  )
}

function CollectionDetail({ collection }: { collection: ProjectsApiCollection }) {
  return (
    <main className="space-y-6 font-papers-research">
      <BackLink href="/projects/collections" label="Collections" />
      <Header title={collection.title} eyebrow={`${collection.item_count ?? 0} items`} body={collection.description} />
      <JsonPanel title="Sections" value={collection.sections ?? []} />
    </main>
  )
}

function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Button asChild variant="outline" size="sm">
      <Link href={href}>
        <ArrowLeft className="size-4" />
        {label}
      </Link>
    </Button>
  )
}

function Header({ title, eyebrow, body }: { title: string; eyebrow: string; body: string }) {
  return (
    <header className="space-y-4 py-6">
      <p className="text-xs font-semibold uppercase text-[#667085] dark:text-muted-foreground">{labelize(eyebrow)}</p>
      <h1 className="max-w-5xl text-4xl font-black leading-tight tracking-normal text-[#202124] sm:text-5xl dark:text-foreground">{title}</h1>
      {body ? <p className="max-w-3xl text-base leading-7 text-[#4b5563] dark:text-muted-foreground">{body}</p> : null}
    </header>
  )
}

function LinkPanel({ project }: { project: ProjectsApiProjectDetail["project"] }) {
  const url = project.github_url ?? project.website_url ?? project.canonical_url
  return (
    <div className="rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
      <h2 className="text-base font-semibold text-[#202124] dark:text-foreground">Links</h2>
      {url ? (
        <Button asChild className="mt-3" size="sm">
          <a href={url} target="_blank" rel="noreferrer">
            Open Source
            <ExternalLink className="size-4" />
          </a>
        </Button>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">No public URL in the current artifact.</p>
      )}
    </div>
  )
}

function Panel({ title, body }: { title: string; body: string }) {
  return (
    <section className="rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
      <h2 className="text-sm font-semibold text-[#202124] dark:text-foreground">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-[#4b5563] dark:text-muted-foreground">{body || "Unavailable"}</p>
    </section>
  )
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="rounded-md border border-[#d8dee7] bg-white p-4 shadow-sm dark:border-border dark:bg-card">
      <h2 className="text-sm font-semibold text-[#202124] dark:text-foreground">{title}</h2>
      <pre className="mt-3 max-h-96 overflow-auto rounded-md bg-[#111827] p-3 text-xs leading-5 text-white">{JSON.stringify(value, null, 2)}</pre>
    </section>
  )
}
