import type { CredibilityLevel } from "@/types/common"
import { Badge } from "@/components/ui/badge"

const credibilityMap: Record<CredibilityLevel, { label: string; variant: "success" | "warning" | "danger" }> = {
  high: { label: "高可信", variant: "success" },
  medium: { label: "中可信", variant: "warning" },
  low: { label: "低可信", variant: "danger" }
}

export function CredibilityBadge({ level, value }: { level?: CredibilityLevel; value?: CredibilityLevel }) {
  const resolvedLevel = level ?? value ?? "medium"
  const config = credibilityMap[resolvedLevel]
  return <Badge variant={config.variant}>{config.label}</Badge>
}
