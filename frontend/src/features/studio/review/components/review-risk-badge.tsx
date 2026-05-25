import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { ReviewRiskLevel } from "@/types/review"

const riskConfig: Record<ReviewRiskLevel, { label: string; className: string }> = {
  low: {
    label: "Low",
    className: "border-success/30 bg-success/10 text-success"
  },
  medium: {
    label: "Medium",
    className: "border-info/30 bg-info/10 text-info"
  },
  high: {
    label: "High",
    className: "border-warning/50 bg-warning/15 text-warning"
  },
  critical: {
    label: "Critical",
    className: "border-danger bg-danger/15 text-danger shadow-sm"
  }
}

export function ReviewRiskBadge({ riskLevel }: { riskLevel: ReviewRiskLevel }) {
  const config = riskConfig[riskLevel]
  return (
    <Badge className={cn("uppercase tracking-normal", config.className)} variant="default">
      {config.label}
    </Badge>
  )
}
