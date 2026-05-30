export default function SettingsPage() {
  return (
    <main className="space-y-6">
      <header className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Settings</h1>
        <p className="text-sm text-muted">Environment and API connection settings for this console.</p>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <SettingRow label="API Base URL" value={process.env.NEWSROOM_API_BASE_URL ?? "http://localhost:8000"} />
        <SettingRow label="API Token" value={process.env.NEWSROOM_API_TOKEN ? "configured" : "not configured"} />
      </section>
    </main>
  )
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <p className="text-xs uppercase text-muted">{label}</p>
      <p className="mt-2 break-words font-medium text-ink">{value}</p>
    </div>
  )
}
