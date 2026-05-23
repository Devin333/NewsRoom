"use client";

import { techItems } from "@/lib/mock-data";
import type { MockHookResult } from "@/types/common";
import type { TechItem, TechItemType, TechMaturity } from "@/types/tech";

export type TechFilters = {
  keyword?: string;
  type?: TechItemType;
  maturity?: TechMaturity;
};

export function useTechItems(filters: TechFilters = {}): MockHookResult<TechItem[]> {
  const keyword = filters.keyword?.trim().toLowerCase();
  const data = techItems
    .filter((item) => (!filters.type ? true : item.type === filters.type))
    .filter((item) => (!filters.maturity ? true : item.maturity === filters.maturity))
    .filter((item) => {
      if (!keyword) {
        return true;
      }
      return [item.name, item.summary, item.problem, item.agentEvaluation, item.referenceValue, ...(item.tags ?? []), ...(item.relatedTopicNames ?? [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(keyword);
    });

  return { data, isLoading: false, isError: false, refetch: () => undefined };
}
