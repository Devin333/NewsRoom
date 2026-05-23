"use client";

import { useMemo, useState } from "react";
import { sources } from "@/lib/mock-data";
import type { Source, SourceFilters } from "@/types/source";

const initialFilters: SourceFilters = {
  keyword: "",
  type: "all",
  healthStatus: "all",
  enabled: "all",
};

export function useSources() {
  const [filters, setFilters] = useState<SourceFilters>(initialFilters);
  const [selectedSourceId, setSelectedSourceId] = useState(sources[0]?.id);

  const filteredSources = useMemo(() => {
    return filterSources(sources, filters);
  }, [filters]);

  return {
    allSources: sources,
    sources: filteredSources,
    filters,
    setFilters,
    selectedSource: filteredSources.find((source) => source.id === selectedSourceId) ?? filteredSources[0],
    setSelectedSourceId,
  };
}

export function filterSources(sourceItems: Source[], filters: SourceFilters) {
  return sourceItems.filter((source) => {
    const keyword = filters.keyword.trim().toLowerCase();
    const matchesKeyword =
      !keyword ||
      source.name.toLowerCase().includes(keyword) ||
      source.id.toLowerCase().includes(keyword) ||
      source.configProfile?.toLowerCase().includes(keyword);
    const matchesType = filters.type === "all" || source.type === filters.type;
    const matchesHealth = filters.healthStatus === "all" || source.healthStatus === filters.healthStatus;
    const matchesEnabled =
      filters.enabled === "all" ||
      (filters.enabled === "enabled" && source.enabled) ||
      (filters.enabled === "disabled" && !source.enabled);
    return matchesKeyword && matchesType && matchesHealth && matchesEnabled;
  });
}

export function calculateSourceMetrics(sourceItems: Source[]) {
  const enabled = sourceItems.filter((source) => source.enabled).length;
  const healthy = sourceItems.filter((source) => source.healthStatus === "healthy").length;
  const failed = sourceItems.filter((source) => source.healthStatus === "failed").length;
  const collected = sourceItems.reduce((total, source) => total + source.collectedCount24h, 0);
  const errors = sourceItems.reduce((total, source) => total + source.errorCount24h, 0);
  const latencySources = sourceItems.filter((source) => source.avgLatencyMs !== undefined);
  const avgLatency = latencySources.reduce((total, source) => total + (source.avgLatencyMs ?? 0), 0) / Math.max(latencySources.length, 1);
  return { total: sourceItems.length, enabled, healthy, failed, collected, errors, avgLatency };
}
