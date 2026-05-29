import { AlertCircle, Database, Loader2 } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { Badge } from "@/components/ui/badge"
import type { ProjectListResult } from "@/types/projects"

const EMPTY_DESCRIPTION = "当前没有真实 Project Radar 数据。系统不会用假项目数据填充页面，请先完成 project_radar 运行或接入可用 artifact。"

export function ProjectLoadingState({ title = "正在读取 Project Radar" }: { title?: string }) {
  return (
    <div className="flex min-h-64 items-center justify-center rounded-md border border-[#d8dee7] bg-white p-8 dark:border-border dark:bg-card">
      <div className="text-center">
        <Loader2 className="mx-auto size-7 animate-spin text-primary" />
        <p className="mt-3 text-sm font-semibold text-[#202124] dark:text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">正在请求真实 Projects API。</p>
      </div>
    </div>
  )
}

export function ProjectErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return <ErrorState title="Projects 加载失败" message={message ?? "真实 Project Radar API 暂时不可用。"} onRetry={onRetry} />
}

export function ProjectEmptyState({ title = "没有真实 Project Radar 数据" }: { title?: string }) {
  return <EmptyState title={title} description={EMPTY_DESCRIPTION} />
}

export function ProjectDegradedNotice({ result }: { result: ProjectListResult }) {
  if (result.dataState === "ready" && result.notices.length === 0) return null

  const latestNotice = result.notices[result.notices.length - 1]
  const text =
    result.dataState === "empty"
      ? EMPTY_DESCRIPTION
      : latestNotice ?? "当前 Project Radar 数据不完整，只展示真实 API 或 artifact 中可解析的项目记录。"

  return (
    <div className="flex flex-col gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-950 sm:flex-row sm:items-start dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
      <AlertCircle className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold">数据状态</p>
          <Badge variant={result.dataState === "empty" ? "muted" : "warning"}>{result.dataState}</Badge>
          <Badge variant="muted">{result.source}</Badge>
        </div>
        <p className="mt-1 text-sm leading-6">{text}</p>
      </div>
    </div>
  )
}

export function ProjectSourceLine({ result }: { result: ProjectListResult }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-[#667085] dark:text-muted-foreground">
      <Database className="size-3.5" />
      <span>数据源：{result.source}</span>
      {result.sourceRunId ? <span>Run：{result.sourceRunId}</span> : null}
      {result.generatedAt ? <span>生成：{result.generatedAt}</span> : null}
    </div>
  )
}
