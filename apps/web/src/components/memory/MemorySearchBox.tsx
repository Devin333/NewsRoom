"use client"

import { useState } from "react"
import { ErrorState } from "@/components/common/ErrorState"
import { safeApiPost } from "@/lib/api-client"
import type { MemorySearchResponse } from "@/lib/types"

export function MemorySearchBox() {
  const [query, setQuery] = useState("")
  const [collection, setCollection] = useState("report_sections")
  const [limit, setLimit] = useState(5)
  const [result, setResult] = useState<MemorySearchResponse | null>(null)
  const [error, setError] = useState<{ message?: string; requestId?: string } | null>(null)

  async function submit() {
    setError(null)
    setResult(null)
    const response = await safeApiPost<MemorySearchResponse>("/api/v1/memory/search", {
      query,
      collection,
      limit,
      filters: {}
    })
    if (response.ok && response.data) {
      setResult(response.data)
    } else {
      setError({ message: response.errorMessage, requestId: response.requestId })
    }
  }

  return (
    <section className="space-y-4">
      <div className="grid gap-3 rounded-lg border border-line bg-white p-4 lg:grid-cols-[1fr_16rem_8rem_auto]">
        <input
          className="h-10 rounded-md border border-line px-3 text-sm text-ink"
          placeholder="Search memory"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <input
          className="h-10 rounded-md border border-line px-3 text-sm text-ink"
          value={collection}
          onChange={(event) => setCollection(event.target.value)}
        />
        <input
          className="h-10 rounded-md border border-line px-3 text-sm text-ink"
          type="number"
          min={1}
          max={50}
          value={limit}
          onChange={(event) => setLimit(Number(event.target.value))}
        />
        <button
          className="h-10 rounded-md bg-accent px-4 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!query.trim()}
          onClick={submit}
          type="button"
        >
          Search
        </button>
      </div>

      {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}
      {result ? (
        <div className="space-y-3">
          <p className="text-sm text-muted">{result.result_count} results</p>
          {result.results.map((item, index) => (
            <div key={`${item.document_id ?? "doc"}-${index}`} className="rounded-lg border border-line bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="font-medium text-ink">{item.document_id ?? "unknown"}</p>
                <p className="text-xs text-muted">score={item.score ?? "n/a"}</p>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm text-muted">{item.text ?? "No text preview"}</p>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
