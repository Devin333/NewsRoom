"use client";

import { searchIndex, searchObjectTypes } from "@/lib/search";
import type { MockHookResult } from "@/types/common";
import type { SearchObjectType, SearchResult } from "@/types/search";

export type GlobalSearchFilters = {
  query?: string;
  objectTypes?: SearchObjectType[];
};

export function useGlobalSearch(filters: GlobalSearchFilters): MockHookResult<SearchResult[]> {
  const types = filters.objectTypes?.length ? filters.objectTypes : searchObjectTypes;
  return {
    data: searchIndex(filters.query ?? "", types),
    isLoading: false,
    isError: false,
    refetch: () => undefined,
  };
}
