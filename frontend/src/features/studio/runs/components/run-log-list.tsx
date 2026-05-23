import { Badge } from "@/components/common/badge"
import { EmptyState } from "@/components/common/empty-state"
import { formatDateTime } from "@/lib/format"
import type { RunLogItem } from "@/types/agent"

const levelTone = {
  debug: "neutral",
  info: "info",
  warning: "warning",
  error: "danger"
} as const

export function RunLogList({ logs }: { logs: RunLogItem[] }) {
  if (!logs.length) return <EmptyState title="暂无日志" description="这次运行没有日志条目。" />

  return (
    <div className="space-y-2">
      {logs.map((log) => (
        <div key={log.id} className="rounded-md border border-border bg-secondary/35 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Badge tone={levelTone[log.level]}>{log.level}</Badge>
            <span className="text-xs text-muted-foreground">{formatDateTime(log.timestamp)}</span>
          </div>
          <p className="mt-2 text-sm text-foreground">{log.message}</p>
          {log.stepId ? <p className="mt-1 font-mono text-xs text-muted-foreground">{log.stepId}</p> : null}
        </div>
      ))}
    </div>
  )
}
