import type { AgentRunStatus, StepStatus } from "@/types/agent"
import type { ReportStatus } from "@/types/report"
import type { SourceHealthStatus } from "@/types/source"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { getStatusVariant } from "@/lib/constants/status-variants"

type StatusValue = AgentRunStatus | StepStatus | ReportStatus | SourceHealthStatus | string

const statusMap: Record<string, { label: string; variant: BadgeProps["variant"] }> = {
  pending: { label: "待处理", variant: "muted" },
  running: { label: "运行中", variant: "info" },
  success: { label: "成功", variant: "success" },
  passed: { label: "通过", variant: "success" },
  failed: { label: "失败", variant: "danger" },
  cancelled: { label: "已取消", variant: "muted" },
  partially_failed: { label: "部分失败", variant: "warning" },
  skipped: { label: "已跳过", variant: "muted" },
  draft: { label: "草稿", variant: "muted" },
  generated: { label: "已生成", variant: "info" },
  reviewed: { label: "已复核", variant: "success" },
  published: { label: "已发布", variant: "success" },
  healthy: { label: "健康", variant: "success" },
  degraded: { label: "降级", variant: "warning" },
  review: { label: "复核", variant: "warning" },
  review_required: { label: "需要复核", variant: "info" },
  warning: { label: "警告", variant: "warning" },
  disabled: { label: "已停用", variant: "muted" },
  analyzed: { label: "已分析", variant: "info" }
}

export function StatusBadge({ status }: { status: StatusValue }) {
  const raw = String(status)
  const config = statusMap[raw] ?? { label: raw, variant: getStatusVariant(raw) as BadgeProps["variant"] }
  return <Badge variant={config.variant}>{config.label}</Badge>
}
