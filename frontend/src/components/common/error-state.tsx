"use client"

import { AlertTriangle, RefreshCcw } from "lucide-react"
import { Button } from "@/components/ui/button"

export type ErrorStateProps = {
  title?: string
  message?: string
  onRetry?: () => void
}

export function ErrorState({ title = "出现错误", message, onRetry }: ErrorStateProps) {
  return (
    <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-danger">{title}</p>
          {message ? <p className="mt-1 leading-6 text-foreground">{message}</p> : null}
          {onRetry ? (
            <Button className="mt-3" variant="outline" size="sm" onClick={onRetry}>
              <RefreshCcw className="size-4" />
              重试
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
