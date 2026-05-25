import { AlertTriangle } from "lucide-react"
import type { StudioFallbackNotice as StudioFallbackNoticeProps } from "@/types/studio"

export function StudioFallbackNotice({
  title = "Fallback data active",
  message,
  requestId,
  error,
  action
}: StudioFallbackNoticeProps) {
  const resolvedRequestId = requestId ?? error?.requestId

  return (
    <section className="rounded-md border border-warning/30 bg-warning/10 p-4 text-sm">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-warning">{title}</p>
          <p className="mt-1 leading-6 text-foreground">{message}</p>
          {resolvedRequestId ? (
            <p className="mt-2 font-mono text-xs text-muted-foreground">request_id={resolvedRequestId}</p>
          ) : null}
          {action ? <div className="mt-3">{action}</div> : null}
        </div>
      </div>
    </section>
  )
}
