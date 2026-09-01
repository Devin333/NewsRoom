import { AlertCircle, Database, Loader2 } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { ProjectsApiMeta } from "@/types/projects"

// Projects Lab state surfaces reuse global --border, --card, --secondary, and --muted-foreground tokens;
// no Lab-only color token is needed, so light/dark ownership stays in the shared design system.

export function ProjectLoadingState({ title = "Loading Projects" }: { title?: string }) {
  const { t } = useI18n()
  return (
    <div className="flex min-h-64 items-center justify-center rounded-md border border-[#d8dee7] bg-white p-8 dark:border-border dark:bg-card">
      <div className="text-center">
        <Loader2 className="mx-auto size-7 animate-spin text-primary" />
        <p className="mt-3 text-sm font-semibold text-[#202124] dark:text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("projects.state.loadingDescription")}</p>
      </div>
    </div>
  )
}

export function ProjectErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useI18n()
  return <ErrorState title={t("projects.state.errorTitle")} message={message ?? t("projects.state.errorMessage")} onRetry={onRetry} />
}

export function ProjectEmptyState({ title = "No Real Project Radar Data" }: { title?: string }) {
  const { t } = useI18n()
  return <EmptyState title={title === "No Real Project Radar Data" ? t("projects.state.emptyTitle") : title} description={t("projects.state.emptyDescription")} />
}

export function ProjectDegradedNotice({ meta }: { meta: ProjectsApiMeta }) {
  const { t, dataState } = useI18n()
  if (meta.data_state === "ready" && meta.notices.length === 0) return null

  const latestNotice = meta.notices[meta.notices.length - 1]
  const text = meta.data_state === "empty" ? t("projects.state.emptyDescription") : latestNotice ?? t("projects.state.realOnly")

  return (
    <div className="flex flex-col gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-950 sm:flex-row sm:items-start dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
      <AlertCircle className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold">{t("projects.state.dataState")}</p>
          <Badge variant={meta.data_state === "empty" ? "muted" : "warning"}>{dataState(meta.data_state)}</Badge>
          <Badge variant="muted">{meta.source}</Badge>
        </div>
        <p className="mt-1 text-sm leading-6">{text}</p>
      </div>
    </div>
  )
}

export function ProjectSourceLine({ meta }: { meta: ProjectsApiMeta }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-[#667085] dark:text-muted-foreground">
      <Database className="size-3.5" />
      <span>{t("projects.state.source", { source: meta.source })}</span>
      {meta.source_run_id ? <span>{t("projects.state.run", { run: meta.source_run_id })}</span> : null}
      {meta.generated_at ? <span>{t("projects.state.generated", { time: meta.generated_at })}</span> : null}
    </div>
  )
}
