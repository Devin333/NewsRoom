"use client"

import { FormEvent, useEffect, useState } from "react"
import { Filter, Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { ProjectListParams } from "@/types/projects"

export function ProjectToolbar({
  filters,
  onChange,
  onToggleFilters,
}: {
  filters: ProjectListParams
  onChange: (patch: Partial<ProjectListParams>) => void
  onToggleFilters: () => void
}) {
  const [query, setQuery] = useState(filters.q ?? "")

  useEffect(() => {
    setQuery(filters.q ?? "")
  }, [filters.q])

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onChange({ q: query.trim() || undefined, page: 1 })
  }

  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4 lg:flex-row lg:items-center lg:justify-between">
      <form className="flex min-w-0 flex-1 gap-2" onSubmit={submitSearch}>
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索项目、仓库、标签或工程问题"
            className="pl-9"
            aria-label="搜索项目"
          />
        </div>
        {query ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="清空搜索"
            onClick={() => {
              setQuery("")
              onChange({ q: undefined, page: 1 })
            }}
          >
            <X className="size-4" />
          </Button>
        ) : null}
        <Button type="submit">搜索</Button>
      </form>
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" className="xl:hidden" onClick={onToggleFilters}>
          <Filter className="size-4" />
          筛选
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => onChange({ q: undefined, category: undefined, source: undefined, language: undefined, page: 1 })}
        >
          重置
        </Button>
      </div>
    </div>
  )
}
