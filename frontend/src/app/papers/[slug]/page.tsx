import { redirect } from "next/navigation"
import { decodePaperRouteSlug, papersRoutes } from "@/lib/papers/routes"

export const dynamic = "force-dynamic"

export default async function PaperReaderRoute({ params }: { params: { slug: string } }) {
  redirect(papersRoutes.reader(decodePaperRouteSlug(params.slug)))
}
