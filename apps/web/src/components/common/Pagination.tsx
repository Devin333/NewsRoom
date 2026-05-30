import Link from "next/link"

export function Pagination({
  href,
  offset,
  limit,
  count
}: {
  href: (offset: number) => string
  offset: number
  limit: number
  count: number
}) {
  const hasPrev = offset > 0
  const hasNext = count === limit
  const page = Math.floor(offset / limit) + 1

  if (!hasPrev && !hasNext) return null

  return (
    <div className="flex items-center justify-between pt-4 border-t border-line">
      <span className="text-xs text-muted">Page {page}</span>
      <div className="flex gap-2">
        {hasPrev ? (
          <Link
            href={href(Math.max(0, offset - limit))}
            className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface"
          >
            ← Prev
          </Link>
        ) : (
          <span className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-subtle opacity-40">← Prev</span>
        )}
        {hasNext ? (
          <Link
            href={href(offset + limit)}
            className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface"
          >
            Next →
          </Link>
        ) : (
          <span className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-subtle opacity-40">Next →</span>
        )}
      </div>
    </div>
  )
}
