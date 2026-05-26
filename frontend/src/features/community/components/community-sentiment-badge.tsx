import type { ComponentProps } from "react"
import { Badge } from "@/components/common/badge"
import { communitySentimentLabel } from "@/lib/community/community-filters"
import type { CommunityTopicSentiment } from "@/types/community"

const sentimentTone: Record<CommunityTopicSentiment, ComponentProps<typeof Badge>["tone"]> = {
  positive: "success",
  negative: "danger",
  mixed: "warning",
  controversial: "warning",
  neutral: "info",
  unknown: "neutral"
}

export function CommunitySentimentBadge({ sentiment }: { sentiment: CommunityTopicSentiment }) {
  return <Badge tone={sentimentTone[sentiment]}>{communitySentimentLabel(sentiment)}</Badge>
}
