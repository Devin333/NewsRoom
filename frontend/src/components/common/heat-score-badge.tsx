import { Badge } from "@/components/ui/badge"

export function HeatScoreBadge({ score, value }: { score?: number; value?: number }) {
  const resolvedScore = score ?? value ?? 0
  const variant = resolvedScore >= 80 ? "accent" : resolvedScore >= 60 ? "info" : "muted"
  return <Badge variant={variant}>热度 {Math.round(resolvedScore)}</Badge>
}
