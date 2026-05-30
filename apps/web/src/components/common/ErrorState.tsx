export function ErrorState({
  title = "Something went wrong",
  message,
  details,
  requestId
}: {
  title?: string
  message?: string
  details?: string
  requestId?: string
}) {
  return (
    <div className="rounded-lg border border-bad/20 bg-bad/5 p-4">
      <p className="text-sm font-medium text-bad">{title}</p>
      {message && <p className="mt-1 text-sm text-muted">{message}</p>}
      {details && <pre className="mt-2 overflow-x-auto rounded bg-white p-2 font-mono text-xs text-ink">{details}</pre>}
      {requestId && <p className="mt-2 font-mono text-xs text-subtle">req: {requestId}</p>}
    </div>
  )
}
