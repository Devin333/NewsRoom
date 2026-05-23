"use client"

import { useQuery } from "@tanstack/react-query"
import { mockNews } from "@/lib/api/mock-data"
import { queryKeys } from "@/lib/query/query-keys"
import type { PageResponse } from "@/types/common"
import type { NewsFilters, NewsItem } from "@/types/news"
import { applyNewsFilters, getFilterOptions, paginateNews } from "@/features/news/lib/news-filters"

export function useNewsList(filters: NewsFilters) {
  return useQuery({
    queryKey: queryKeys.news.list(filters),
    queryFn: async (): Promise<{
      page: PageResponse<NewsItem>
      allItems: NewsItem[]
      allFiltered: NewsItem[]
      options: ReturnType<typeof getFilterOptions>
    }> => {
      const allFiltered = applyNewsFilters(mockNews, filters)
      return {
        page: paginateNews(allFiltered, filters.page),
        allItems: mockNews,
        allFiltered,
        options: getFilterOptions(mockNews)
      }
    }
  })
}
