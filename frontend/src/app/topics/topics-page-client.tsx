"use client";

import { useState } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { TopicList } from "@/features/topics/components/topic-list";
import { TopicToolbar } from "@/features/topics/components/topic-toolbar";
import { useTopicList } from "@/features/topics/hooks/use-topic-list";
import type { TopicFilters } from "@/types/topic";

export function TopicsPageClient() {
  const [filters, setFilters] = useState<TopicFilters>({ sort: "heatScore", viewMode: "grid" });
  const topics = useTopicList(filters);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="主题情报"
        title="主题"
        description="由新闻、数据源、证据和智能体分析综合形成的事件簇与趋势对象。"
      />
      <TopicToolbar filters={filters} onChange={setFilters} />
      <TopicList topics={topics.data} viewMode={filters.viewMode ?? "grid"} />
    </div>
  );
}
