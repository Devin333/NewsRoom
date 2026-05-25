"use client"

import Link from "next/link"
import { ExternalLink } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { ReviewRiskBadge } from "@/features/studio/review/components/review-risk-badge"
import { StudioTableFrame } from "@/features/studio/shared/components/studio-dashboard"
import type { StudioReviewItem } from "@/types/review"

const statusVariant: Record<StudioReviewItem["status"], BadgeProps["variant"]> = {
  pending: "info",
  approved: "success",
  rejected: "danger",
  modified: "warning",
  expired: "muted"
}

export function ReviewQueueTable({ items }: { items: StudioReviewItem[] }) {
  if (!items.length) {
    return <EmptyState title="No review items" description="The current filter has no approvals, blocked runs, or fallback report items." />
  }

  return (
    <StudioTableFrame>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-52">Approval id</TableHead>
              <TableHead className="min-w-44">Requested action</TableHead>
              <TableHead className="min-w-28">Risk</TableHead>
              <TableHead className="min-w-28">Status</TableHead>
              <TableHead className="min-w-40">Run id</TableHead>
              <TableHead className="min-w-40">Report id</TableHead>
              <TableHead className="min-w-36">Requested by</TableHead>
              <TableHead className="min-w-40">Requested at</TableHead>
              <TableHead className="min-w-40">Expires at</TableHead>
              <TableHead className="min-w-64">Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.approvalId} className={item.riskLevel === "critical" ? "bg-danger/5" : undefined}>
                <TableCell className="font-medium">
                  <Link className="inline-flex max-w-52 items-center gap-2 truncate text-primary hover:underline" href={`/studio/review/${encodeURIComponent(item.approvalId)}`}>
                    <span className="truncate">{item.approvalId}</span>
                    <ExternalLink className="size-3.5 shrink-0" />
                  </Link>
                </TableCell>
                <TableCell className="max-w-48 truncate">{item.requestedAction}</TableCell>
                <TableCell>
                  <ReviewRiskBadge riskLevel={item.riskLevel} />
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant[item.status]}>{item.status}</Badge>
                </TableCell>
                <TableCell>{item.runId ? <ResourceLink href={`/studio/runs/${encodeURIComponent(item.runId)}`} label={item.runId} /> : <MutedDash />}</TableCell>
                <TableCell>{item.reportId ? <ResourceLink href={`/reports/${encodeURIComponent(item.reportId)}`} label={item.reportId} /> : <MutedDash />}</TableCell>
                <TableCell className="max-w-36 truncate">{item.requestedBy ?? <MutedDash />}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(item.requestedAt)}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{formatDateTime(item.expiresAt)}</TableCell>
                <TableCell className="max-w-72 truncate text-muted-foreground">{item.reason ?? <MutedDash />}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </StudioTableFrame>
  )
}

function ResourceLink({ href, label }: { href: string; label: string }) {
  return (
    <Link className="inline-flex max-w-40 items-center gap-1 truncate text-primary hover:underline" href={href}>
      <span className="truncate">{label}</span>
      <ExternalLink className="size-3 shrink-0" />
    </Link>
  )
}

function MutedDash() {
  return <span className="text-muted-foreground">-</span>
}

function formatDateTime(value: string | undefined): string {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}
