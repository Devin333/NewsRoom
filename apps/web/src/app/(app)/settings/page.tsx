export default function SettingsPage() {
  const apiBase = process.env.NEWSROOM_API_BASE_URL ?? "http://localhost:8000"
  const hasToken = !!process.env.NEWSROOM_API_TOKEN
  const hasConsoleToken = !!process.env.NEWSROOM_CONSOLE_TOKEN

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Settings</h1>
        <p className="mt-0.5 text-sm text-muted">Console configuration</p>
      </div>

      <div className="rounded-xl border border-line bg-white p-5 shadow-card">
        <h2 className="mb-4 text-sm font-semibold text-ink">API Connection</h2>
        <dl className="space-y-3">
          <Row label="API Base URL" value={apiBase} mono />
          <Row label="API Token" value={hasToken ? "Configured ✓" : "Not set"} ok={hasToken} />
          <Row label="Console Token" value={hasConsoleToken ? "Configured ✓" : "Not set"} ok={hasConsoleToken} />
        </dl>
      </div>
    </div>
  )
}

function Row({ label, value, mono, ok }: { label: string; value: string; mono?: boolean; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-line pb-3 last:border-0 last:pb-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className={`text-sm ${mono ? "font-mono" : ""} ${ok === true ? "text-good" : ok === false ? "text-bad" : "text-ink"}`}>
        {value}
      </dd>
    </div>
  )
}
