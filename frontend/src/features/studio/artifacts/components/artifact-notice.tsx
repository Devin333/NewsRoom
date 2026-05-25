export function ArtifactNotice({ notices }: { notices: string[] }) {
  if (!notices.length) return null

  return (
    <section className="space-y-1 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
      {notices.map((notice) => (
        <p key={notice}>{notice}</p>
      ))}
    </section>
  )
}
