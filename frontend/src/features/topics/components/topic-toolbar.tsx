"use client"

import { useI18n } from "@/lib/i18n/use-i18n"
import type { TopicFilters, TopicTrend } from "@/types/topic"

const trends: TopicTrend[] = ["rising", "stable", "falling"]

export function TopicToolbar({ filters, onChange }: { filters: TopicFilters; onChange: (filters: TopicFilters) => void }) {
  const { locale } = useI18n()
  const categories =
    locale === "zh"
      ? ["开发者工具", "智能体运行时", "模型", "开源", "效率工具", "基础设施", "评估", "工作流"]
      : ["Developer Tools", "Agent Runtime", "Models", "Open Source", "Productivity Tools", "Infrastructure", "Evaluation", "Workflow"]
  const trendLabels: Record<TopicTrend, string> = {
    rising: locale === "zh" ? "上升" : "Rising",
    stable: locale === "zh" ? "稳定" : "Stable",
    falling: locale === "zh" ? "下降" : "Falling"
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 lg:grid-cols-[1.4fr_0.9fr_0.9fr_0.8fr_0.9fr]">
        <input
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          placeholder={locale === "zh" ? "搜索主题、实体、标签..." : "Search topics, entities, tags..."}
          value={filters.keyword ?? ""}
          onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
        />
        <select
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={filters.trend?.[0] ?? ""}
          onChange={(event) => onChange({ ...filters, trend: event.target.value ? [event.target.value as TopicTrend] : [] })}
        >
          <option value="">{locale === "zh" ? "全部趋势" : "All trends"}</option>
          {trends.map((trend) => (
            <option key={trend} value={trend}>
              {trendLabels[trend]}
            </option>
          ))}
        </select>
        <select
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={filters.category?.[0] ?? ""}
          onChange={(event) => onChange({ ...filters, category: event.target.value ? [event.target.value] : [] })}
        >
          <option value="">{locale === "zh" ? "全部分类" : "All categories"}</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>
        <select
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={filters.sort ?? "heatScore"}
          onChange={(event) => onChange({ ...filters, sort: event.target.value as TopicFilters["sort"] })}
        >
          <option value="heatScore">{locale === "zh" ? "热度" : "Heat"}</option>
          <option value="lastSeenAt">{locale === "zh" ? "更新时间" : "Updated time"}</option>
          <option value="itemCount">{locale === "zh" ? "新闻数" : "News count"}</option>
          <option value="qualityScore">{locale === "zh" ? "质量" : "Quality"}</option>
        </select>
        <select
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={filters.viewMode ?? "grid"}
          onChange={(event) => onChange({ ...filters, viewMode: event.target.value as TopicFilters["viewMode"] })}
        >
          <option value="grid">{locale === "zh" ? "网格" : "Grid"}</option>
          <option value="list">{locale === "zh" ? "列表" : "List"}</option>
          <option value="dense">{locale === "zh" ? "紧凑" : "Dense"}</option>
        </select>
      </div>
      <input
        className="mt-3 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
        placeholder={locale === "zh" ? "按实体筛选，例如 OpenAI" : "Filter by entity, for example OpenAI"}
        value={filters.entity ?? ""}
        onChange={(event) => onChange({ ...filters, entity: event.target.value })}
      />
    </div>
  )
}
