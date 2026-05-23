"use client";

import type { MemoryFilters } from "@/types/memory";

export function MemorySearchBar({ filters, onChange }: { filters: MemoryFilters; onChange: (filters: MemoryFilters) => void }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <input
        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
        placeholder="搜索记忆、证据、实体、主题或智能体笔记"
        value={filters.keyword ?? ""}
        onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
      />
    </div>
  );
}
