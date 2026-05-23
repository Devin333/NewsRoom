import { Badge } from "@/components/ui/badge"
import { sourceHealthStatusVariants } from "@/lib/constants/status-variants"
import { titleCase } from "@/lib/format"
import type { SourceHealthStatus } from "@/types/source"

export function SourceHealthBadge({ status }: { status: SourceHealthStatus }) {
  return <Badge variant={sourceHealthStatusVariants[status]}>{titleCase(status)}</Badge>
}
