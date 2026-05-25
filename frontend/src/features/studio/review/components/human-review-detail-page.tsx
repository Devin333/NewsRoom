"use client"

import Link from "next/link"
import { ArrowLeft, ExternalLink } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ReviewDecisionPanel } from "@/features/studio/review/components/review-decision-panel"
import { ReviewHistoryPanel } from "@/features/studio/review/components/review-history-panel"
import { ReviewRiskBadge } from "@/features/studio/review/components/review-risk-badge"
import {
  StudioField,
  StudioFieldGrid,
  StudioNotice,
  StudioPageHeader,
  StudioPanel
} from "@/features/studio/shared/components/studio-dashboard"
import type { StudioReviewDetail, StudioReviewItem } from "@/types/review"

export function HumanReviewDetailPage({ detail }: { detail: StudioReviewDetail }) {
  const { item, notices } = detail

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Human Review"
        title={item.approvalId}
        description={item.requestedAction}
        actions={
          <Button asChild variant="outline">
            <Link href="/studio/review">
              <ArrowLeft className="size-4" />
              Review
            </Link>
          </Button>
        }
        meta={
          <>
            <ReviewRiskBadge riskLevel={item.riskLevel} />
            <Badge variant="info">{item.status}</Badge>
            {item.rawStatus && item.rawStatus !== item.status ? <Badge variant="muted">{item.rawStatus}</Badge> : null}
          </>
        }
      />

      {notices.length || item.notices.length ? (
        <StudioNotice tone="warning" title="Review data notice">
          {[...notices, ...item.notices].map((notice) => (
            <p key={notice}>{notice}</p>
          ))}
        </StudioNotice>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-4">
          <ReviewDetailSummary item={item} />
          <PayloadPreview payload={item.payloadPreview} />
          <ReviewHistoryPanel history={item.history} />
        </div>
        <ReviewDecisionPanel item={item} />
      </section>
    </main>
  )
}

function ReviewDetailSummary({ item }: { item: StudioReviewItem }) {
  return (
    <StudioPanel title="Review summary" description={riskExplanation(item)}>
      <StudioFieldGrid className="md:grid-cols-2">
        <StudioField label="Requested action" value={item.requestedAction} />
        <StudioField label="Requested by" value={item.requestedBy ?? "n/a"} />
        <StudioField label="Requested at" value={formatDateTime(item.requestedAt)} />
        <StudioField label="Expires at" value={formatDateTime(item.expiresAt)} />
        <StudioField label="Run" value={item.runId ? <ResourceLink href={`/studio/runs/${encodeURIComponent(item.runId)}`} label={item.runId} /> : "n/a"} />
        <StudioField label="Report" value={item.reportId ? <ResourceLink href={`/reports/${encodeURIComponent(item.reportId)}`} label={item.reportId} /> : "n/a"} />
      </StudioFieldGrid>
      {item.reason ? (
        <div className="mt-4 rounded-md border border-border bg-background p-3">
          <h2 className="text-sm font-semibold text-foreground">Reason</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.reason}</p>
        </div>
      ) : null}
    </StudioPanel>
  )
}

function PayloadPreview({ payload }: { payload?: Record<string, unknown> }) {
  return (
    <StudioPanel title="Payload preview">
      <pre className="max-h-[34rem] overflow-auto rounded-md bg-muted p-4 text-xs leading-5 text-foreground">
        {JSON.stringify(payload ?? {}, null, 2)}
      </pre>
    </StudioPanel>
  )
}

function ResourceLink({ href, label }: { href: string; label: string }) {
  return (
    <Link className="inline-flex max-w-full items-center gap-1 truncate text-primary hover:underline" href={href}>
      <span className="truncate">{label}</span>
      <ExternalLink className="size-3.5 shrink-0" />
    </Link>
  )
}

function riskExplanation(item: StudioReviewItem): string {
  if (item.riskLevel === "critical") return "Critical risk. Review payload, linked run, and report before allowing workflow continuation."
  if (item.riskLevel === "high") return "High risk. This action can affect publishing, blocked workflow recovery, or external delivery."
  if (item.riskLevel === "medium") return "Medium risk. Human verification is expected before the workflow proceeds."
  return "Low risk. Confirm that the requested action matches the payload and linked artifacts."
}

function formatDateTime(value: string | undefined): string | undefined {
  if (!value) return undefined
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}
