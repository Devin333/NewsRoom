import type { BadgeProps } from "@/components/ui/badge"
import type { AgentRunStatus, StepStatus } from "@/types/agent"
import type { CredibilityLevel } from "@/types/common"
import type { QualityResultStatus } from "@/types/quality"
import type { SourceHealthStatus } from "@/types/source"
import type { TopicTrend } from "@/types/topic"

export type BadgeVariant = NonNullable<BadgeProps["variant"]>

export const sourceHealthStatusVariants: Record<SourceHealthStatus, BadgeVariant> = {
  healthy: "success",
  degraded: "warning",
  failed: "danger",
  down: "danger",
  cooling_down: "warning",
  disabled: "muted",
}

export const qualityStatusVariants: Record<QualityResultStatus, BadgeVariant> = {
  passed: "success",
  warning: "warning",
  failed: "danger",
  review_required: "info",
}

export const agentRunStatusVariants: Record<AgentRunStatus, BadgeVariant> = {
  pending: "muted",
  running: "info",
  success: "success",
  succeeded: "success",
  failed: "danger",
  cancelled: "muted",
  partially_failed: "warning",
  blocked: "warning",
  waiting_for_human: "warning",
}

export const stepStatusVariants: Record<StepStatus, BadgeVariant> = {
  pending: "muted",
  running: "info",
  success: "success",
  failed: "danger",
  skipped: "muted",
  blocked: "warning",
  cancelled: "muted",
}

export const credibilityVariants: Record<CredibilityLevel, BadgeVariant> = {
  high: "success",
  medium: "warning",
  low: "danger",
}

export const topicTrendVariants: Record<TopicTrend, BadgeVariant> = {
  rising: "info",
  stable: "success",
  falling: "warning",
}

export function getStatusVariant(status: string): BadgeVariant {
  const normalized = status.toLowerCase()
  const known: Record<string, BadgeVariant> = {
    ok: "success",
    healthy: "success",
    success: "success",
    succeeded: "success",
    passed: "success",
    approved: "success",
    published: "success",
    reviewed: "success",
    running: "info",
    queued: "info",
    accepted: "info",
    generated: "info",
    review_required: "info",
    review: "warning",
    warning: "warning",
    waiting_for_human: "warning",
    degraded: "warning",
    blocked: "warning",
    needs_changes: "warning",
    partially_failed: "warning",
    failed: "danger",
    down: "danger",
    rejected: "danger",
    unavailable: "danger",
    cooling_down: "warning",
    disabled: "muted",
    cancelled: "muted",
    pending: "muted",
    skipped: "muted",
    draft: "muted",
  }
  return known[normalized] ?? "default"
}
