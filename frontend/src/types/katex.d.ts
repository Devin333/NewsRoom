declare module "katex" {
  export interface KatexOptions {
    displayMode?: boolean
    throwOnError?: boolean
    strict?: "ignore" | "warn" | "error" | boolean | ((errorCode: string, errorMsg: string, token: unknown) => boolean | "ignore" | "warn" | "error")
    trust?: boolean | ((context: unknown) => boolean)
  }

  export function renderToString(expression: string, options?: KatexOptions): string

  const katex: {
    renderToString: typeof renderToString
  }

  export default katex
}
