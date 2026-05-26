import type { ComponentProps } from "react"
import { Badge } from "@/components/common/badge"
import { communitySentimentLabel } from "@/lib/community/community-filters"
import type { CommunitySentiment } from "@/types/community"

const sentimentTone: Record<CommunitySentiment, ComponentProps<typeof Badge>["tone"]> = {
  positive: "success",
  negative: "danger",
  mixed: "warning",
  neutral: "info",
  unknown: "neutral"
}

export function CommunitySentimentBadge({ sentiment }: { sentiment: CommunitySentiment }) {
  return <Badge tone={sentimentTone[sentiment]}>{communitySentimentLabel(sentiment)}</Badge>
}
