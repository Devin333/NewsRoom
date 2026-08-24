export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-8 px-6 py-10">
      <section className="border-b border-slate-200 pb-6">
        <p className="text-sm font-medium text-slate-500">NewsRoom Console</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-950">Operations Dashboard</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
          Monitor Graph runs, reports, source health, worker status, memory, and durable Waits from the API-backed console.
        </p>
      </section>
      <section className="grid gap-4 md:grid-cols-3">
        {[
          ["Runs", "Inspect daily and weekly workflow execution state."],
          ["Reports", "Review generated intelligence outputs and artifacts."],
          ["Sources", "Track source health, freshness, and fetch diagnostics."]
        ].map(([title, body]) => (
          <article key={title} className="rounded border border-slate-200 bg-white p-4">
            <h2 className="text-base font-semibold text-slate-950">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">{body}</p>
          </article>
        ))}
      </section>
    </main>
  )
}
