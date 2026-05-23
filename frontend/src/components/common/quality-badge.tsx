import { Badge } from "@/components/ui/badge"

export function QualityBadge({ score, value }: { score?: number; value?: number }) {
  const resolvedScore = score ?? value ?? 0
  const variant = resolvedScore >= 85 ? "success" : resolvedScore >= 70 ? "warning" : "danger"
  const label = resolvedScore >= 85 ? "高质量" : resolvedScore >= 70 ? "需复核" : "低质量"
  return (
    <Badge variant={variant}>
      {label} {Math.round(resolvedScore)}
    </Badge>
  )
}
