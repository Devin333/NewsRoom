import { redirect } from "next/navigation"

export const dynamic = "force-dynamic"

export default async function PaperReaderRoute({ params }: { params: { slug: string } }) {
  redirect(`/papers/${encodeURIComponent(params.slug)}/read`)
}
