"use client"

import { useState } from "react"
import { safeApiPost } from "@/lib/api-client"
import type { MemorySearchResponse } from "@/lib/types"

export function MemorySearchBox() {
  const [query, setQuery] = useState("")
  const [collection, setCollection] = useState("reports")
  const [limit, setLimit] = useState(10)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<MemorySearchResponse | null>(null)
  const [error, setError] = useState("")

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError("")
    const res = await safeApiPost<MemorySearchResponse>("/api/v1/memory/search", { query, collection, limit })
    if (res.ok && res.data) setResult(res.data)
    else setError(res.errorMessage ?? "Search failed")
    setLoading(false)
  }

  return (
    <div className="space-y-5">
      <form onSubmit={handleSearch} className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-48">
          <label className="mb-1 block text-xs font-medium text-muted">Query</label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search memory…"
            required
            className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink placeholder:text-subtle focus:border-accent focus:outline-none"
          />
        </div>
        <div className="w-36">
          <label className="mb-1 block text-xs font-medium text-muted">Collection</label>
          <input
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
            className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
          />
        </div>
        <div className="w-24">
          <label className="mb-1 block text-xs font-medium text-muted">Limit</label>
          <input
            type="number"
            value={limit}
            min={1}
            max={100}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !query}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && <p className="text-sm text-bad">{error}</p>}

      {result && (
        <div className="space-y-2">
          <p className="text-xs text-muted">{result.result_count} results in <span className="font-mono">{result.collection}</span></p>
          {result.results.map((r, i) => (
            <div key={r.document_id ?? i} className="rounded-lg border border-line bg-white p-4">
              <div className="flex items-center justify-between gap-4">
                <span className="font-mono text-xs text-subtle">{r.document_id ?? `result-${i}`}</span>
                {r.score != null && (
                  <span className="text-xs text-muted">score {r.score.toFixed(3)}</span>
                )}
              </div>
              {r.text && <p className="mt-2 text-sm text-ink line-clamp-3">{r.text}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
