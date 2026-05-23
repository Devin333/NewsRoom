"use client";

import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { EntityMemoryView } from "@/features/memory/components/entity-memory-view";
import { MemoryFilterPanel } from "@/features/memory/components/memory-filter-panel";
import { MemoryResultList } from "@/features/memory/components/memory-result-list";
import { MemorySearchBar } from "@/features/memory/components/memory-search-bar";
import { MemoryTimelineView } from "@/features/memory/components/memory-timeline-view";
import { MemoryViewTabs } from "@/features/memory/components/memory-view-tabs";
import { TopicHistoryView } from "@/features/memory/components/topic-history-view";
import { useMemorySearch } from "@/features/memory/hooks/use-memory-search";
import type { MemoryItem, MemoryViewMode } from "@/types/memory";

export function MemoryPageClient() {
  const { allItems, results, filters, setFilters, viewMode, setViewMode } = useMemorySearch();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="记忆运行时"
        title="记忆"
        description="检索 NewsRoom 运行中使用的长期记忆、证据、实体、主题历史和智能体笔记。"
      />
      <MemorySearchBar filters={filters} onChange={setFilters} />
      <div className="grid gap-6 xl:grid-cols-[18rem_minmax(0,1fr)]">
        <MemoryFilterPanel filters={filters} onChange={setFilters} />
        <section className="min-w-0 space-y-4">
          <MemoryViewTabs value={viewMode} onChange={setViewMode} />
          {renderMemoryView(viewMode, results)}
        </section>
      </div>
      <p className="text-xs text-muted-foreground">
        已显示 {results.length} / {allItems.length} 条保留记忆记录。
      </p>
    </div>
  );
}

function renderMemoryView(viewMode: MemoryViewMode, items: MemoryItem[]) {
  if (viewMode === "evidence") {
    return <MemoryResultList items={items.filter((item) => item.type === "evidence")} />;
  }

  if (viewMode === "entity") {
    if (!items.some((item) => item.entityNames?.length)) {
      return <EmptyState title="暂无实体记忆" description="调整筛选条件以包含关联实体的记忆。" />;
    }
    return <EntityMemoryView items={items} />;
  }

  if (viewMode === "topic") {
    if (!items.some((item) => item.topicIds?.length)) {
      return <EmptyState title="暂无主题历史" description="调整筛选条件以包含关联主题历史的记忆。" />;
    }
    return <TopicHistoryView items={items} />;
  }

  if (viewMode === "timeline") {
    if (!items.length) {
      return <EmptyState title="暂无记忆时间线" description="调整筛选条件以恢复按时间排列的记忆记录。" />;
    }
    return <MemoryTimelineView items={items} />;
  }

  return <MemoryResultList items={items} />;
}
