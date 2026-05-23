"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/common/badges";
import { PageHeader } from "@/components/layout/page-header";
import { TechFilterToolbar } from "@/features/tech/components/tech-filter-toolbar";
import { TechRadarGrid } from "@/features/tech/components/tech-radar-grid";
import { useTechItems, type TechFilters } from "@/features/tech/hooks/use-tech-items";
import type { TechItemType } from "@/types/tech";

export function TechPageClient({ fixedType }: { fixedType?: TechItemType }) {
  const [filters, setFilters] = useState<TechFilters>({ type: fixedType });
  const items = useTechItems({ ...filters, type: fixedType ?? filters.type });
  const title = fixedType ? `技术雷达：${techTypeLabels[fixedType]}` : "技术雷达";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="技术情报"
        title={title}
        description="追踪值得工程判断关注的论文、仓库、框架、方法和实践。"
        actions={
          <>
            <Link href="/tech/papers"><Badge tone="accent">论文</Badge></Link>
            <Link href="/tech/repos"><Badge tone="accent">仓库</Badge></Link>
            <Link href="/tech/frameworks"><Badge tone="accent">框架</Badge></Link>
          </>
        }
      />
      <TechFilterToolbar filters={{ ...filters, type: fixedType ?? filters.type }} onChange={setFilters} />
      {!fixedType ? <RadarOverview /> : null}
      <TechRadarGrid items={items.data} />
    </div>
  );
}

function RadarOverview() {
  const sections = [
    ["论文", "具备报告引用价值的研究信号。"],
    ["仓库", "出现采用率或 benchmark 波动的开源项目。"],
    ["框架", "可支撑产品与运行时决策的复用基础。"],
    ["新兴主题", "从单点 demo 进入重复实践的技术项。"],
  ];
  return (
    <section className="grid gap-3 md:grid-cols-4">
      {sections.map(([title, summary]) => (
        <div key={title} className="rounded-lg border border-border bg-card p-4">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{summary}</p>
        </div>
      ))}
    </section>
  );
}

const techTypeLabels: Record<TechItemType, string> = {
  paper: "论文",
  repo: "仓库",
  framework: "框架",
  method: "方法",
  practice: "实践",
};
