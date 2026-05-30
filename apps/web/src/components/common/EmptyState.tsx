export function EmptyState({ title, message, requestId }: { title: string; message?: string; requestId?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface py-12 text-center">
      <div className="mb-2 text-2xl text-subtle">○</div>
      <p className="text-sm font-medium text-ink">{title}</p>
      {message && <p className="mt-1 max-w-xs text-xs text-muted">{message}</p>}
      {requestId && <p className="mt-2 font-mono text-xs text-subtle">{requestId}</p>}
    </div>
  )
}
