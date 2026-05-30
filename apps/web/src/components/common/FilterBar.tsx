"use client"

import { useRouter, usePathname, useSearchParams } from "next/navigation"
import { useCallback } from "react"

export function FilterBar({
  filters
}: {
  filters: { key: string; label: string; type: "text" | "date" | "select"; options?: string[] }[]
}) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const update = useCallback(
    (key: string, value: string) => {
      const p = new URLSearchParams(searchParams.toString())
      if (value) p.set(key, value)
      else p.delete(key)
      p.delete("offset") // reset page on filter change
      router.push(`${pathname}?${p}`)
    },
    [router, pathname, searchParams]
  )

  return (
    <div className="flex flex-wrap gap-2">
      {filters.map((f) =>
        f.type === "select" ? (
          <select
            key={f.key}
            value={searchParams.get(f.key) ?? ""}
            onChange={(e) => update(f.key, e.target.value)}
            className="rounded-md border border-line bg-white px-3 py-1.5 text-xs text-ink focus:border-accent focus:outline-none"
          >
            <option value="">{f.label}</option>
            {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        ) : (
          <input
            key={f.key}
            type={f.type}
            placeholder={f.label}
            value={searchParams.get(f.key) ?? ""}
            onChange={(e) => update(f.key, e.target.value)}
            className="rounded-md border border-line bg-white px-3 py-1.5 text-xs text-ink placeholder:text-subtle focus:border-accent focus:outline-none"
          />
        )
      )}
    </div>
  )
}
