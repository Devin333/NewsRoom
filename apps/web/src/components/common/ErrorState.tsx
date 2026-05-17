export function ErrorState({
  title = "Request failed",
  message,
  requestId
}: {
  title?: string
  message?: string
  requestId?: string
}) {
  return (
    <div className="rounded-lg border border-bad/30 bg-bad/5 p-4 text-sm">
      <p className="font-semibold text-bad">{title}</p>
      {message ? <p className="mt-1 text-ink">{message}</p> : null}
      {requestId ? <p className="mt-2 font-mono text-xs text-muted">request_id={requestId}</p> : null}
    </div>
  )
}
