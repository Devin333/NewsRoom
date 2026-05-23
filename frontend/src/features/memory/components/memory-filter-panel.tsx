"use client";

import type { MemoryFilters, MemoryItem } from "@/types/memory";

const memoryTypes: MemoryItem["type"][] = ["news", "topic", "evidence", "entity", "report", "agent_note"];
const confidences: NonNullable<MemoryItem["confidence"]>[] = ["high", "medium", "low"];

export function MemoryFilterPanel({ filters, onChange }: { filters: MemoryFilters; onChange: (filters: MemoryFilters) => void }) {
  return (
    <aside className="space-y-5 rounded-lg border border-border bg-card p-4">
      <FilterGroup title="记忆类型">
        {memoryTypes.map((type) => (
          <label key={type} className="flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={filters.memoryType?.includes(type) ?? false} onChange={() => toggleArray(filters, onChange, "memoryType", type)} />
            {labelMemoryType(type)}
          </label>
        ))}
      </FilterGroup>
      <FilterGroup title="可信度">
        {confidences.map((confidence) => (
          <label key={confidence} className="flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={filters.confidence?.includes(confidence) ?? false} onChange={() => toggleArray(filters, onChange, "confidence", confidence)} />
            {labelConfidence(confidence)}
          </label>
        ))}
      </FilterGroup>
      <FilterGroup title="实体">
        <input className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm" placeholder="实体名称" value={filters.entity ?? ""} onChange={(event) => onChange({ ...filters, entity: event.target.value })} />
      </FilterGroup>
      <FilterGroup title="主题">
        <input className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm" placeholder="主题 ID" value={filters.topicId ?? ""} onChange={(event) => onChange({ ...filters, topicId: event.target.value })} />
      </FilterGroup>
    </aside>
  );
}

function labelMemoryType(type: MemoryItem["type"]) {
  const labels: Record<MemoryItem["type"], string> = {
    news: "新闻",
    topic: "主题",
    evidence: "证据",
    entity: "实体",
    report: "报告",
    agent_note: "智能体笔记",
  }
  return labels[type]
}

function labelConfidence(confidence: NonNullable<MemoryItem["confidence"]>) {
  return confidence === "high" ? "高" : confidence === "medium" ? "中" : "低"
}

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium uppercase text-muted-foreground">{title}</p>
      {children}
    </div>
  );
}

function toggleArray<K extends "memoryType" | "confidence">(filters: MemoryFilters, onChange: (filters: MemoryFilters) => void, key: K, value: NonNullable<MemoryFilters[K]>[number]) {
  const current = (filters[key] ?? []) as string[];
  const next = current.includes(value as string) ? current.filter((item) => item !== value) : [...current, value as string];
  onChange({ ...filters, [key]: next } as MemoryFilters);
}
