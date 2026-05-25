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
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioReviewItem, StudioReviewQueue } from "@/types/review"

const filters: { value: ReviewQueueFilter; labelKey: string }[] = [
  { value: "pending", labelKey: "studio.review.pending" },
  { value: "high-risk", labelKey: "studio.review.highRiskLabel" },
  { value: "blocked", labelKey: "studio.review.blockedRuns" },
  { value: "history", labelKey: "studio.review.history" },
  { value: "all", labelKey: "studio.review.all" }
]

export function HumanReviewPage({ queue }: { queue: StudioReviewQueue }) {
  const { t } = useI18n()
  const { filter, setFilter, query, setQuery, metrics, filteredItems } = useReviewQueue(queue.items)

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.nav.governance")}
        title={t("studio.module.humanReview.title")}
        description={t("studio.module.humanReview.description")}
      />

      {queue.notices.length ? (
        <StudioNotice tone="warning" title={t("studio.review.dataNotice")}>
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
                {t(item.labelKey)}
              </Button>
            ))}
          </div>
          <label className="relative lg:w-96">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label={t("studio.review.searchLabel")}
              className="pl-9"
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("studio.review.searchPlaceholder")}
              value={query}
            />
          </label>
        </div>
      </StudioToolbar>

      {queue.items.length ? <ReviewQueueTable items={filteredItems} /> : <EmptyState title={t("studio.review.noQueue")} description={t("studio.review.noQueueDescription")} />}

      <ReviewHistoryPanel items={queue.items} title={t("studio.review.approvalHistory")} />
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
  const { t } = useI18n()
  const critical = items.filter((item) => item.riskLevel === "critical").length
  return (
    <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
      <StudioMetricCard icon={ShieldCheck} label={t("studio.review.pending")} value={pending} detail={t("studio.review.awaitingDecision")} tone="info" />
      <StudioMetricCard icon={AlertTriangle} label={t("studio.review.highRiskLabel")} value={highRisk} detail={t("studio.review.criticalCount", { count: critical })} tone={highRisk ? "warning" : "neutral"} />
      <StudioMetricCard icon={AlertTriangle} label={t("studio.review.blockedRuns")} value={blocked} detail={t("studio.review.workflowRecovery")} tone={blocked ? "danger" : "success"} />
      <StudioMetricCard icon={History} label={t("studio.review.history")} value={history} detail={t("studio.review.completedDecisions")} />
    </StudioMetricGrid>
  )
}
