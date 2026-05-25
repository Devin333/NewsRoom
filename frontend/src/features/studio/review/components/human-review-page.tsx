"use client"

import { AlertTriangle, History, Search, ShieldCheck } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ReviewHistoryPanel } from "@/features/studio/review/components/review-history-panel"
import { ReviewQueueTable } from "@/features/studio/review/components/review-queue-table"
import { useReviewQueue, type ReviewQueueFilter } from "@/features/studio/review/hooks/use-review-queue"
import {
  StudioMetricCard,
  StudioMetricGrid,
  StudioNotice,
  StudioPageHeader,
  StudioToolbar
} from "@/features/studio/shared/components/studio-dashboard"
import type { StudioReviewItem, StudioReviewQueue } from "@/types/review"

const filters: { value: ReviewQueueFilter; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "high-risk", label: "High risk" },
  { value: "blocked", label: "Blocked runs" },
  { value: "history", label: "History" },
  { value: "all", label: "All" }
]

export function HumanReviewPage({ queue }: { queue: StudioReviewQueue }) {
  const { filter, setFilter, query, setQuery, metrics, filteredItems } = useReviewQueue(queue.items)

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Governance"
        title="Human Review"
        description="Pending approvals, high-risk operations, blocked runs, and recorded human decisions."
      />

      {queue.notices.length ? (
        <StudioNotice tone="warning" title="Review data notice">
          {queue.notices.map((notice) => (
            <p key={notice}>{notice}</p>
          ))}
        </StudioNotice>
      ) : null}

      <ReviewMetrics items={queue.items} pending={metrics.pending} highRisk={metrics.highRisk} blocked={metrics.blocked} history={metrics.history} />

      <StudioToolbar>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {filters.map((item) => (
              <Button
                key={item.value}
                onClick={() => setFilter(item.value)}
                size="sm"
                type="button"
                variant={filter === item.value ? "default" : "outline"}
              >
                {item.label}
              </Button>
            ))}
          </div>
          <label className="relative lg:w-96">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search review queue"
              className="pl-9"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search approval, run, report, action"
              value={query}
            />
          </label>
        </div>
      </StudioToolbar>

      {queue.items.length ? <ReviewQueueTable items={filteredItems} /> : <EmptyState title="No review queue" description="No approvals or blocked runs were returned." />}

      <ReviewHistoryPanel items={queue.items} title="Approval history" />
    </main>
  )
}

function ReviewMetrics({
  items,
  pending,
  highRisk,
  blocked,
  history
}: {
  items: StudioReviewItem[]
  pending: number
  highRisk: number
  blocked: number
  history: number
}) {
  const critical = items.filter((item) => item.riskLevel === "critical").length
  return (
    <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
      <StudioMetricCard icon={ShieldCheck} label="Pending" value={pending} detail="Awaiting decision" tone="info" />
      <StudioMetricCard icon={AlertTriangle} label="High risk" value={highRisk} detail={`${critical} critical`} tone={highRisk ? "warning" : "neutral"} />
      <StudioMetricCard icon={AlertTriangle} label="Blocked runs" value={blocked} detail="Workflow recovery" tone={blocked ? "danger" : "success"} />
      <StudioMetricCard icon={History} label="History" value={history} detail="Completed decisions" />
    </StudioMetricGrid>
  )
}
