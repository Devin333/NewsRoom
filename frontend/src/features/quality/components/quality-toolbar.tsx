"use client";

import type { QualityFilters, QualityResultStatus } from "@/types/quality";

const statuses: QualityResultStatus[] = ["passed", "warning", "failed", "review_required"];
const objectTypes: Array<Exclude<QualityFilters["objectType"], "all">> = ["news", "topic", "report", "run"];
const statusLabels: Record<QualityResultStatus, string> = {
  passed: "通过",
  warning: "警告",
  failed: "失败",
  review_required: "需要复核",
};
const objectLabels: Record<Exclude<QualityFilters["objectType"], "all">, string> = {
  news: "新闻",
  topic: "主题",
  report: "报告",
  run: "运行",
};

export function QualityToolbar({ filters, onChange }: { filters: QualityFilters; onChange: (filters: QualityFilters) => void }) {
  return (
    <section className="grid gap-3 rounded-lg border border-border bg-card p-4 lg:grid-cols-[1fr_10rem_12rem_10rem_10rem]">
      <input className="h-10 rounded-md border border-input bg-background px-3 text-sm" placeholder="搜索质量结果" value={filters.keyword} onChange={(event) => onChange({ ...filters, keyword: event.target.value })} />
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.objectType} onChange={(event) => onChange({ ...filters, objectType: event.target.value as QualityFilters["objectType"] })}>
        <option value="all">全部类型</option>
        {objectTypes.map((type) => <option key={type} value={type}>{objectLabels[type]}</option>)}
      </select>
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.status} onChange={(event) => onChange({ ...filters, status: event.target.value as QualityFilters["status"] })}>
        <option value="all">全部状态</option>
        {statuses.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}
      </select>
      <input className="h-10 rounded-md border border-input bg-background px-3 text-sm" type="number" min={0} max={100} value={filters.minScore} onChange={(event) => onChange({ ...filters, minScore: Number(event.target.value) })} />
      <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={filters.review} onChange={(event) => onChange({ ...filters, review: event.target.value as QualityFilters["review"] })}>
        <option value="all">全部复核</option>
        <option value="pending">待处理</option>
        <option value="decided">已决策</option>
      </select>
    </section>
  );
}
