import type { PaperModuleRoute } from "@/lib/papers/types"

export const papersRoutes = {
  trending: "/papers",
  detail: (slug: string) => `/papers/${encodeURIComponent(slug)}` as PaperModuleRoute,
  reader: (slug: string) => `/papers/${encodeURIComponent(slug)}/read` as PaperModuleRoute,
  tasks: "/papers/tasks",
  taskDetail: (slug: string) => `/papers/tasks/${encodeURIComponent(slug)}` as PaperModuleRoute,
  methods: "/papers/methods",
  methodDetail: (slug: string) => `/papers/methods/${encodeURIComponent(slug)}` as PaperModuleRoute
} satisfies Record<string, PaperModuleRoute | ((slug: string) => PaperModuleRoute)>

export function decodePaperRouteSlug(slug: string) {
  try {
    return decodeURIComponent(slug)
  } catch {
    return slug
  }
}
