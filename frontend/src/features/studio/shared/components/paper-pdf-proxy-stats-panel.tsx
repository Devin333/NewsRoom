"use client"

import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, Ban, Clock3, FileText, Gauge } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ApiRequestError } from "@/lib/api/client"
import { queryKeys } from "@/lib/query/query-keys"
import { fetchPaperPdfProxyStats } from "@/features/studio/shared/api/pdf-proxy-stats-api"
import {
  StudioEmptyBlock,
  StudioMetricCard,
  StudioMetricGrid,
  StudioNotice,
  StudioPanel,
} from "@/features/studio/shared/components/studio-dashboard"
import type { PaperPdfProxyStats } from "@/types/studio"

export function PaperPdfProxyStatsPanel({ windowHours = 24 }: { windowHours?: number }) {
  const { data, error, isError, isLoading } = useQuery({
    queryKey: queryKeys.studio.pdfProxyStats(windowHours),
    queryFn: () => fetchPaperPdfProxyStats(windowHours),
    retry: false,
    staleTime: 30_000
  })

  if (isLoading) {
    return (
      <StudioPanel title="Paper Reader PDF Proxy" description="Loading PDF proxy request statistics.">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="h-24 animate-pulse rounded-md border border-border bg-secondary/50" />
          ))}
        </div>
      </StudioPanel>
    )
  }

  if (isError) {
    return (
      <StudioNotice tone="danger" title="PDF proxy stats unavailable">
        <p>{error instanceof Error ? error.message : "PDF proxy stats request failed."}</p>
        {error instanceof ApiRequestError && error.requestId ? (
          <p className="mt-1 font-mono text-xs">requestId={error.requestId}</p>
        ) : null}
      </StudioNotice>
    )
  }

  if (!data || data.dataState === "empty") {
    return (
      <StudioPanel title="Paper Reader PDF Proxy" description={`${windowHours}h request window`}>
        <StudioEmptyBlock
          title="No PDF proxy events"
          description="Open a paper PDF or thumbnail through the Reader to populate proxy statistics."
        />
      </StudioPanel>
    )
  }

  return (
    <StudioPanel
      title="Paper Reader PDF Proxy"
      description={`${data.windowHours}h request window ending ${formatDateTime(data.windowEndedAt)}`}
      actions={<Badge variant={data.dataState === "ready" ? "success" : "warning"}>{data.dataState}</Badge>}
    >
      <PdfProxyStatsContent stats={data} />
    </StudioPanel>
  )
}

function PdfProxyStatsContent({ stats }: { stats: PaperPdfProxyStats }) {
  const topError = Object.entries(stats.errorsByCode).sort(([, left], [, right]) => right - left)[0]
  const topHost = stats.topHosts[0]
  return (
    <div className="space-y-4">
      {stats.dataState === "partial" || stats.notices.length ? (
        <StudioNotice tone={stats.dataState === "partial" ? "warning" : "info"} title="PDF proxy stats notice">
          <div className="space-y-1">
            {stats.notices.map((notice) => (
              <p key={notice}>{notice}</p>
            ))}
          </div>
        </StudioNotice>
      ) : null}

      <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
        <StudioMetricCard label="Requests" value={stats.totalRequests} detail={`${stats.successCount} streamed`} icon={FileText} tone="accent" />
        <StudioMetricCard label="Errors" value={stats.errorCount} detail={topError ? `${topError[0]} (${topError[1]})` : "No errors"} icon={AlertTriangle} tone={stats.errorCount ? "warning" : "success"} />
        <StudioMetricCard label="Timeouts" value={stats.timeoutCount} detail={`${stats.oversizedCount} oversized`} icon={Clock3} tone={stats.timeoutCount ? "danger" : "neutral"} />
        <StudioMetricCard label="Blocked" value={stats.blockedCount} detail={topHost ? topHost.host : "No host data"} icon={Ban} tone={stats.blockedCount ? "danger" : "neutral"} />
      </StudioMetricGrid>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="rounded-md border border-border bg-background p-3">
          <div className="mb-2 flex items-center gap-2">
            <Gauge className="size-4 text-accent" />
            <h3 className="text-sm font-semibold text-foreground">Top hosts</h3>
          </div>
          <div className="space-y-2">
            {stats.topHosts.length ? (
              stats.topHosts.map((host) => (
                <div key={host.host} className="flex items-center justify-between gap-3 rounded-md bg-secondary/40 px-3 py-2 text-sm">
                  <span className="truncate font-medium text-foreground">{host.host}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {host.requestCount} req / {host.errorCount} err
                  </span>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No host data in this window.</p>
            )}
          </div>
        </div>

        <div className="rounded-md border border-border bg-background p-3">
          <h3 className="text-sm font-semibold text-foreground">Recent errors</h3>
          <div className="mt-2 space-y-2">
            {stats.recentErrors.length ? (
              stats.recentErrors.map((item) => (
                <div key={`${item.timestamp}-${item.code}-${item.path}`} className="rounded-md bg-secondary/40 px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-warning">{item.code}</span>
                    <span className="text-muted-foreground">{formatDateTime(item.timestamp)}</span>
                  </div>
                  <p className="mt-1 truncate text-muted-foreground">{[item.host, item.path].filter(Boolean).join("")}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No recent proxy errors.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
