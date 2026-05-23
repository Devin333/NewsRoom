"use client";

import { topics } from "@/lib/mock-data";
import type { MockHookResult } from "@/types/common";
import type { Topic, TopicFilters } from "@/types/topic";

export function useTopicList(filters: TopicFilters): MockHookResult<Topic[]> {
  const keyword = filters.keyword?.trim().toLowerCase();
  const filtered = topics
    .filter((topic) => {
      if (!keyword) {
        return true;
      }
      return [topic.name, topic.summary, topic.category, ...(topic.entities ?? []), ...(topic.tags ?? [])].join(" ").toLowerCase().includes(keyword);
    })
    .filter((topic) => (!filters.trend?.length ? true : filters.trend.includes(topic.trend)))
    .filter((topic) => (!filters.category?.length ? true : filters.category.includes(topic.category ?? "")))
    .filter((topic) => (!filters.entity ? true : (topic.entities ?? []).some((entity) => entity.toLowerCase().includes(filters.entity!.toLowerCase()))))
    .sort((a, b) => {
      const sort = filters.sort ?? "heatScore";
      if (sort === "lastSeenAt") {
        return new Date(b.lastSeenAt ?? 0).getTime() - new Date(a.lastSeenAt ?? 0).getTime();
      }
      return Number(b[sort] ?? 0) - Number(a[sort] ?? 0);
    });

  return {
    data: filtered,
    isLoading: false,
    isError: false,
    refetch: () => undefined,
  };
}
