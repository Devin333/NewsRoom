export function EmptyState({
  title,
  message,
  requestId
}: {
  title: string
  message?: string
  requestId?: string
}) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-4 py-6 text-center">
      <p className="text-sm font-semibold text-ink">{title}</p>
      {message ? <p className="mt-1 max-w-md text-sm text-muted">{message}</p> : null}
      {requestId ? <p className="mt-2 font-mono text-xs text-muted">request_id={requestId}</p> : null}
    </div>
  )
}
