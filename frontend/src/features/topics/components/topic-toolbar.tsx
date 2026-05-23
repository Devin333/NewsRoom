"use client";

import type { TopicFilters, TopicTrend } from "@/types/topic";

const trends: TopicTrend[] = ["rising", "stable", "falling"];
const categories = ["开发者工具", "Agent 运行时", "模型", "开源", "效率工具", "基础设施", "评估", "工作流"];
const trendLabels: Record<TopicTrend, string> = {
  rising: "上升",
  stable: "稳定",
  falling: "下降",
};

export function TopicToolbar({ filters, onChange }: { filters: TopicFilters; onChange: (filters: TopicFilters) => void }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 lg:grid-cols-[1.4fr_0.9fr_0.9fr_0.8fr_0.9fr]">
        <input
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          placeholder="搜索主题、实体、标签..."
          value={filters.keyword ?? ""}
          onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
        />
        <select
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={filters.trend?.[0] ?? ""}
          onChange={(event) => onChange({ ...filters, trend: event.target.value ? [event.target.value as TopicTrend] : [] })}
        >
          <option value="">全部趋势</option>
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
          <option value="">全部分类</option>
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
          <option value="heatScore">热度</option>
          <option value="lastSeenAt">更新时间</option>
          <option value="itemCount">新闻数</option>
          <option value="qualityScore">质量</option>
        </select>
        <select
          className="rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={filters.viewMode ?? "grid"}
          onChange={(event) => onChange({ ...filters, viewMode: event.target.value as TopicFilters["viewMode"] })}
        >
          <option value="grid">网格</option>
          <option value="list">列表</option>
          <option value="dense">紧凑</option>
        </select>
      </div>
      <input
        className="mt-3 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
        placeholder="按实体筛选，例如 OpenAI"
        value={filters.entity ?? ""}
        onChange={(event) => onChange({ ...filters, entity: event.target.value })}
      />
    </div>
  );
}
