import type { PaperModuleRoute } from "@/lib/papers/types"

export const papersRoutes = {
  trending: "/papers",
  tasks: "/papers/tasks",
  taskDetail: (slug: string) => `/papers/tasks/${encodeURIComponent(slug)}` as PaperModuleRoute,
  methods: "/papers/methods",
  methodDetail: (slug: string) => `/papers/methods/${encodeURIComponent(slug)}` as PaperModuleRoute
} satisfies Record<string, PaperModuleRoute | ((slug: string) => PaperModuleRoute)>
