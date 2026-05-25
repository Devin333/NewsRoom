"use client"

import { useMemo } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Badge } from "@/components/common/badges"
import { PageHeader } from "@/components/layout/page-header"
import { GlobalSearchBox } from "@/features/search/components/global-search-box"
import { SearchResultList } from "@/features/search/components/search-result-list"
import { useGlobalSearch } from "@/features/search/hooks/use-global-search"
import { titleCase } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
import { searchObjectTypes } from "@/lib/search"
import type { SearchObjectType } from "@/types/search"

export function SearchPageClient() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { t } = useI18n()
  const query = searchParams.get("q") ?? ""
  const types = useMemo(
    () => searchParams.getAll("type").filter((type): type is SearchObjectType => searchObjectTypes.includes(type as SearchObjectType)),
    [searchParams]
  )
  const search = useGlobalSearch({ query, objectTypes: types })
  const activeTypes = useMemo(() => types.length ? types : searchObjectTypes, [types])

  function updateUrl(nextQuery: string, nextTypes: SearchObjectType[]) {
    const params = new URLSearchParams()
    if (nextQuery.trim()) {
      params.set("q", nextQuery)
    }
    nextTypes.forEach((type) => params.append("type", type))
    router.replace(params.size ? `/search?${params.toString()}` : "/search", { scroll: false })
  }

  function toggle(type: SearchObjectType) {
    const nextTypes = types.includes(type) ? types.filter((item) => item !== type) : [...types, type]
    updateUrl(query, nextTypes)
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={t("portal.search.eyebrow")} title={t("portal.search.title")} description={t("portal.search.description")} />
      <GlobalSearchBox value={query} onChange={(value) => updateUrl(value, types)} />
      <div className="flex flex-wrap gap-2">
        {searchObjectTypes.map((type) => (
          <button key={type} onClick={() => toggle(type)} className="text-left">
            <Badge tone={activeTypes.includes(type) ? "accent" : "neutral"}>{titleCase(type)}</Badge>
          </button>
        ))}
      </div>
      <SearchResultList results={search.data} />
    </div>
  )
}
