import { Activity, Clock3, Database, ShieldCheck } from "lucide-react"
import type { ComponentType } from "react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { DashboardDataState, DashboardOverview, TopStory } from "@/types/dashboard"

const stateLabels: Record<DashboardDataState, string> = {
  ready: "数据已就绪",
  partial: "部分数据",
  empty: "暂无数据",
  fallback: "Showing local fallback"
}

const stateVariants: Record<DashboardDataState, "success" | "accent" | "warning" | "muted"> = {
  ready: "success",
  partial: "accent",
  empty: "muted",
  fallback: "warning"
}

const boardLabels: Record<TopStory["board"], string> = {
  news: "AI 新闻",
  paper: "论文雷达",
  project: "项目雷达",
  community: "社区脉搏"
}

export function DashboardStateNotice({ overview }: { overview: DashboardOverview }) {
  const notices = overview.dataState === "fallback" && !overview.notices?.includes("Showing local fallback")
    ? ["Showing local fallback", ...(overview.notices ?? [])]
    : overview.notices ?? []

  if (!notices.length && overview.dataState === "ready") {
    return null
  }

  return (
    <Card className="border-accent/25 bg-accent/5 p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={stateVariants[overview.dataState]}>{stateLabels[overview.dataState]}</Badge>
            {overview.dataState === "partial" ? <Badge variant="warning">趋势归因可能不完整</Badge> : null}
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{stateDescription(overview.dataState)}</p>
        </div>
        {notices.length ? (
          <ul className="min-w-0 space-y-1 text-xs leading-5 text-muted-foreground md:max-w-xl">
            {notices.slice(0, 4).map((notice) => (
              <li key={notice} className="break-words">
                {notice}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  )
}

export function DashboardFreshnessBar({ overview }: { overview: DashboardOverview }) {
  const boards = visibleBoards(overview.topStories)
  return (
    <Card className="grid gap-3 p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
      <FreshnessItem
        icon={Clock3}
        label="数据新鲜度"
        value={overview.generatedAt ? formatDateTime(overview.generatedAt) : "暂无时间戳"}
      />
      <FreshnessItem icon={ShieldCheck} label="质量状态" value={qualityLabel(overview.quality.status)} />
      <FreshnessItem icon={Database} label="可用板块" value={boards.length ? boards.map((board) => boardLabels[board]).join(" / ") : "等待产物"} />
      <FreshnessItem icon={Activity} label="推荐路径" value={`${overview.brief.readingPath.length} 条`} />
    </Card>
  )
}

function FreshnessItem({
  icon: Icon,
  label,
  value
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  value: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-md bg-secondary/40 px-3 py-2">
      <Icon className="h-4 w-4 shrink-0 text-accent" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="truncate font-medium text-foreground">{value}</p>
      </div>
    </div>
  )
}

function stateDescription(state: DashboardDataState) {
  if (state === "fallback") {
    return "当前没有可用的后端或本地产物，页面正在使用显式本地 fallback 数据。"
  }
  if (state === "partial") {
    return "当前已从可用板块产物生成首页，但部分板块缺失，趋势和阅读路径会保留来源说明。"
  }
  if (state === "empty") {
    return "当前没有可展示的 cross-board intelligence 内容。"
  }
  return "首页正在展示真实 cross-board intelligence 数据。"
}

function visibleBoards(stories: TopStory[]) {
  return [...new Set(stories.map((story) => story.board))]
}

function qualityLabel(status: DashboardOverview["quality"]["status"]) {
  if (status === "passed") return "通过"
  if (status === "review") return "需复核"
  if (status === "failed") return "未通过"
  return "未知"
}

function formatDateTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date)
}
