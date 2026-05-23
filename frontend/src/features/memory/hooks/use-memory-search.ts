"use client";

import { useMemo, useState } from "react";
import { memoryItems } from "@/lib/mock-data";
import type { MemoryFilters, MemoryItem, MemoryViewMode } from "@/types/memory";

const initialFilters: MemoryFilters = {
  keyword: "",
  memoryType: [],
  confidence: [],
  dateRange: "month",
};

export function useMemorySearch() {
  const [filters, setFilters] = useState<MemoryFilters>(initialFilters);
  const [viewMode, setViewMode] = useState<MemoryViewMode>("list");

  const results = useMemo(() => filterMemoryItems(memoryItems, filters), [filters]);

  return {
    allItems: memoryItems,
    results,
    filters,
    setFilters,
    viewMode,
    setViewMode,
  };
}

export function filterMemoryItems(items: MemoryItem[], filters: MemoryFilters) {
  const keyword = filters.keyword?.trim().toLowerCase();
  return items.filter((item) => {
    const text = [item.title, item.summary, item.content, item.type, ...(item.tags ?? []), ...(item.entityNames ?? []), ...(item.topicIds ?? [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    const matchesKeyword = !keyword || text.includes(keyword);
    const matchesType = !filters.memoryType?.length || filters.memoryType.includes(item.type);
    const matchesConfidence = !filters.confidence?.length || (item.confidence ? filters.confidence.includes(item.confidence) : false);
    const matchesEntity = !filters.entity || item.entityNames?.some((entity) => entity.toLowerCase().includes(filters.entity!.toLowerCase()));
    const matchesTopic = !filters.topicId || item.topicIds?.includes(filters.topicId);
    const matchesSource = !filters.sourceType?.length || (item.sourceType ? filters.sourceType.includes(item.sourceType) : false);
    return matchesKeyword && matchesType && matchesConfidence && matchesEntity && matchesTopic && matchesSource;
  });
}
