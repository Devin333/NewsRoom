import { AlertCircle, Database, Loader2 } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { Badge } from "@/components/ui/badge"
import type { ProjectsApiMeta } from "@/types/projects"

const EMPTY_DESCRIPTION =
  "No real Project Radar data is available. Agora Hub will not substitute fake projects, fake cases, or fake stars."

export function ProjectLoadingState({ title = "Loading Projects" }: { title?: string }) {
  return (
    <div className="flex min-h-64 items-center justify-center rounded-md border border-[#d8dee7] bg-white p-8 dark:border-border dark:bg-card">
      <div className="text-center">
        <Loader2 className="mx-auto size-7 animate-spin text-primary" />
        <p className="mt-3 text-sm font-semibold text-[#202124] dark:text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">Reading real Project Radar backed Projects API data.</p>
      </div>
    </div>
  )
}

export function ProjectErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return <ErrorState title="Projects failed to load" message={message ?? "The Projects API is temporarily unavailable."} onRetry={onRetry} />
}

export function ProjectEmptyState({ title = "No Real Project Radar Data" }: { title?: string }) {
  return <EmptyState title={title} description={EMPTY_DESCRIPTION} />
}

export function ProjectDegradedNotice({ meta }: { meta: ProjectsApiMeta }) {
  if (meta.data_state === "ready" && meta.notices.length === 0) return null

  const latestNotice = meta.notices[meta.notices.length - 1]
  const text = meta.data_state === "empty" ? EMPTY_DESCRIPTION : latestNotice ?? "Only parseable real Project Radar data is shown."

  return (
    <div className="flex flex-col gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-950 sm:flex-row sm:items-start dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
      <AlertCircle className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold">Data state</p>
          <Badge variant={meta.data_state === "empty" ? "muted" : "warning"}>{meta.data_state}</Badge>
          <Badge variant="muted">{meta.source}</Badge>
        </div>
        <p className="mt-1 text-sm leading-6">{text}</p>
      </div>
    </div>
  )
}

export function ProjectSourceLine({ meta }: { meta: ProjectsApiMeta }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-[#667085] dark:text-muted-foreground">
      <Database className="size-3.5" />
      <span>Source: {meta.source}</span>
      {meta.source_run_id ? <span>Run: {meta.source_run_id}</span> : null}
      {meta.generated_at ? <span>Generated: {meta.generated_at}</span> : null}
    </div>
  )
}
