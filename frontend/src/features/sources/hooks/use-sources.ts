"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api/client";
import { sources as mockSources } from "@/lib/mock-data";
import { queryKeys } from "@/lib/query/query-keys";
import type { Source, SourceFilters } from "@/types/source";
import type { SourceType } from "@/types/common";

const initialFilters: SourceFilters = {
  keyword: "",
  type: "all",
  healthStatus: "all",
  enabled: "all",
};

export function useSources() {
  const [filters, setFilters] = useState<SourceFilters>(initialFilters);
  const [selectedSourceId, setSelectedSourceId] = useState<string | undefined>();

  const sourcesQuery = useQuery({
    queryKey: queryKeys.studio.sources,
    queryFn: fetchSources,
  });

  const sourceItems = sourcesQuery.data?.length ? sourcesQuery.data : mockSources;

  useEffect(() => {
    if (!selectedSourceId && sourceItems[0]?.id) {
      setSelectedSourceId(sourceItems[0].id);
    }
  }, [selectedSourceId, sourceItems]);

  const selectedBaseSource = sourceItems.find((source) => source.id === selectedSourceId) ?? sourceItems[0];

  const previewQuery = useQuery({
    queryKey: queryKeys.studio.sourcePreview(selectedBaseSource?.id ?? ""),
    queryFn: () => fetchSourcePreview(selectedBaseSource!.id),
    enabled: Boolean(selectedBaseSource?.id && sourcesQuery.data?.length),
    retry: false,
    staleTime: 30_000,
  });

  const allSources = useMemo(() => {
    if (!selectedBaseSource || !previewQuery.data) {
      return sourceItems;
    }
    return sourceItems.map((source) => (source.id === selectedBaseSource.id ? mergePreview(source, previewQuery.data) : source));
  }, [previewQuery.data, selectedBaseSource, sourceItems]);

  const filteredSources = useMemo(() => {
    return filterSources(allSources, filters);
  }, [allSources, filters]);

  const selectedSource = filteredSources.find((source) => source.id === selectedSourceId) ?? filteredSources[0];

  return {
    allSources,
    sources: filteredSources,
    filters,
    setFilters,
    selectedSource,
    setSelectedSourceId,
    isLoading: sourcesQuery.isLoading,
    isFetchingPreview: previewQuery.isFetching,
    error: sourcesQuery.error ?? previewQuery.error,
    isUsingMockFallback: !sourcesQuery.data?.length,
    refetch: sourcesQuery.refetch,
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
  const failed = sourceItems.filter((source) => source.healthStatus === "failed" || source.healthStatus === "down").length;
  const collected = sourceItems.reduce((total, source) => total + source.collectedCount24h, 0);
  const errors = sourceItems.reduce((total, source) => total + source.errorCount24h, 0);
  const latencySources = sourceItems.filter((source) => source.avgLatencyMs !== undefined);
  const avgLatency = latencySources.reduce((total, source) => total + (source.avgLatencyMs ?? 0), 0) / Math.max(latencySources.length, 1);
  return { total: sourceItems.length, enabled, healthy, failed, collected, errors, avgLatency };
}

type ApiEnvelope<T> = {
  success: boolean;
  data: T;
};

type ApiSourceList = {
  source_count: number;
  sources: ApiSourceSummary[];
};

type ApiSourceSummary = {
  source_id: string;
  name: string;
  source_type: string;
  url: string;
  reliability: string;
  authority_score: number;
  enabled: boolean;
  respect_robots?: boolean;
  fetch_interval_seconds?: number;
  topics?: string[];
  category?: string | null;
  language?: string | null;
  region?: string | null;
};

type ApiSourceHealthList = {
  source_count: number;
  health: ApiSourceHealth[];
};

type ApiSourceHealth = {
  source_id: string;
  status?: string;
  health_status?: string;
  consecutive_failures?: number;
  consecutive_failure_count?: number;
  success_count_24h?: number;
  failure_count_24h?: number;
  avg_latency_ms_24h?: number | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  last_error_message?: string | null;
};

type ApiSourceFetchPreview = {
  item_count: number;
  error_count: number;
  items: ApiSourceItem[];
  errors: ApiSourceError[];
};

type ApiSourceItem = {
  source_item_id: string;
  title: string;
  url?: string;
  fetched_at?: string;
  published_at?: string | null;
};

type ApiSourceError = {
  error_type?: string;
  error_message?: string;
};

async function fetchSources(): Promise<Source[]> {
  const [sourceEnvelope, healthEnvelope] = await Promise.all([
    apiGet<ApiEnvelope<ApiSourceList>>("/api/v1/sources?include_disabled=true"),
    apiGet<ApiEnvelope<ApiSourceHealthList>>("/api/v1/sources/health?include_disabled=true"),
  ]);
  const healthById = new Map((healthEnvelope.data.health ?? []).map((item) => [item.source_id, item]));
  return (sourceEnvelope.data.sources ?? []).map((source) => mapApiSource(source, healthById.get(source.source_id)));
}

async function fetchSourcePreview(sourceId: string): Promise<ApiSourceFetchPreview> {
  const envelope = await apiPost<ApiEnvelope<ApiSourceFetchPreview>>("/api/v1/sources/fetch", {
    source_id: sourceId,
    limit: 5,
    force: true,
  });
  return envelope.data;
}

function mapApiSource(source: ApiSourceSummary, health?: ApiSourceHealth): Source {
  const status = normalizeHealthStatus(health?.health_status ?? health?.status, source.enabled);
  const collected = health?.success_count_24h ?? 0;
  const errors = health?.failure_count_24h ?? health?.consecutive_failure_count ?? health?.consecutive_failures ?? 0;
  return {
    id: source.source_id,
    name: source.name,
    type: normalizeSourceType(source.source_type),
    enabled: source.enabled,
    healthStatus: status,
    lastRunAt: health?.last_success_at ?? health?.last_failure_at ?? undefined,
    lastSuccessAt: health?.last_success_at ?? undefined,
    errorCount24h: errors,
    collectedCount24h: collected,
    avgLatencyMs: health?.avg_latency_ms_24h ?? undefined,
    configProfile: source.category ?? source.source_type,
    errorSummary: health?.last_error_message ? [health.last_error_message] : [],
    latestItems: [],
    recentRuns: [
      {
        id: `${source.source_id}-health`,
        status,
        startedAt: health?.last_success_at ?? health?.last_failure_at ?? new Date().toISOString(),
        collectedCount: collected,
        latencyMs: health?.avg_latency_ms_24h ?? undefined,
        errorMessage: health?.last_error_message ?? undefined,
      },
    ],
    configSummary: [
      `category=${source.category ?? "none"}`,
      `language=${source.language ?? "multi"}`,
      `region=${source.region ?? "global"}`,
      `reliability=${source.reliability}`,
      `authority=${source.authority_score}`,
      `topics=${(source.topics ?? []).join(", ") || "none"}`,
    ].join(" | "),
  };
}

function mergePreview(source: Source, preview: ApiSourceFetchPreview): Source {
  return {
    ...source,
    collectedCount24h: Math.max(source.collectedCount24h, preview.item_count),
    errorCount24h: source.errorCount24h + preview.error_count,
    errorSummary: preview.errors.length
      ? preview.errors.map((error) => error.error_message ?? error.error_type ?? "Source fetch error")
      : source.errorSummary,
    latestItems: preview.items.map((item) => ({
      id: item.source_item_id,
      title: item.title,
      capturedAt: item.published_at ?? item.fetched_at ?? new Date().toISOString(),
      url: item.url,
    })),
  };
}

function normalizeSourceType(value: string): SourceType {
  const knownTypes = new Set<SourceType>([
    "official_blog",
    "rss",
    "atom",
    "github",
    "hackernews",
    "reddit",
    "arxiv",
    "lobsters",
    "stackoverflow",
    "devto",
    "medium",
    "html",
    "web_page",
    "manual",
    "media",
    "custom",
  ]);
  return knownTypes.has(value as SourceType) ? (value as SourceType) : "custom";
}

function normalizeHealthStatus(value: string | undefined, enabled: boolean): Source["healthStatus"] {
  if (!enabled) {
    return "disabled";
  }
  if (value === "healthy" || value === "degraded" || value === "failed" || value === "down" || value === "cooling_down") {
    return value;
  }
  return "healthy";
}
