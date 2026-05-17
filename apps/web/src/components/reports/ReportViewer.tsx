import { EmptyState } from "@/components/common/EmptyState"

export function ReportViewer({ markdown }: { markdown?: string | null }) {
  if (!markdown) {
    return <EmptyState title="No markdown" message="This report did not include a markdown body." />
  }

  return (
    <article className="max-h-[48rem] overflow-auto rounded-lg border border-line bg-white p-5">
      <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-ink">{markdown}</pre>
    </article>
  )
}
