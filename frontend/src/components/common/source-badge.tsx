import type { SourceType } from "@/types/common"
import { Badge } from "@/components/ui/badge"

const sourceLabels: Record<SourceType, string> = {
  official_blog: "官方",
  rss: "RSS",
  atom: "Atom",
  github: "GitHub",
  hackernews: "Hacker News",
  reddit: "Reddit",
  arxiv: "arXiv",
  lobsters: "Lobsters",
  stackoverflow: "StackOverflow",
  devto: "dev.to",
  medium: "Medium",
  html: "HTML",
  web_page: "网页",
  manual: "手动",
  media: "媒体",
  custom: "自定义"
}

export function SourceBadge({ type, name }: { type: SourceType; name?: string }) {
  return <Badge variant="default">{name ?? sourceLabels[type]}</Badge>
}
