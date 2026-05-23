"use client";

import type { TechFilters } from "@/features/tech/hooks/use-tech-items";
import type { TechItemType, TechMaturity } from "@/types/tech";

const types: TechItemType[] = ["paper", "repo", "framework", "method", "practice"];
const maturities: TechMaturity[] = ["experimental", "emerging", "stable", "mature"];
const typeLabels: Record<TechItemType, string> = {
  paper: "论文",
  repo: "仓库",
  framework: "框架",
  method: "方法",
  practice: "实践",
};
const maturityLabels: Record<TechMaturity, string> = {
  experimental: "实验",
  emerging: "新兴",
  stable: "稳定",
  mature: "成熟",
};

export function TechFilterToolbar({ filters, onChange }: { filters: TechFilters; onChange: (filters: TechFilters) => void }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="grid gap-3 md:grid-cols-[1fr_0.5fr_0.5fr]">
        <input
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          placeholder="搜索技术、主题、标签..."
          value={filters.keyword ?? ""}
          onChange={(event) => onChange({ ...filters, keyword: event.target.value })}
        />
        <select className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={filters.type ?? ""} onChange={(event) => onChange({ ...filters, type: (event.target.value || undefined) as TechItemType | undefined })}>
          <option value="">全部类型</option>
          {types.map((type) => <option key={type} value={type}>{typeLabels[type]}</option>)}
        </select>
        <select className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={filters.maturity ?? ""} onChange={(event) => onChange({ ...filters, maturity: (event.target.value || undefined) as TechMaturity | undefined })}>
          <option value="">全部成熟度</option>
          {maturities.map((maturity) => <option key={maturity} value={maturity}>{maturityLabels[maturity]}</option>)}
        </select>
      </div>
    </div>
  );
}
