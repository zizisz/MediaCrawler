/** Each line/comma is a search phrase; spaces within a phrase are preserved. */
export function mergeKeywords(existing: string, incoming = ''): string[] {
  return [...new Set([existing, incoming].flatMap((text) => text.split(/[,，\r\n]+/).map((part) => part.trim()).filter(Boolean)))]
}
