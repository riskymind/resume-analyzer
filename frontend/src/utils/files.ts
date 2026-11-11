export const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.md']
export const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024 // 5 MB, mirrors the server limit

/** Client-side pre-check only; the server validates type, signature and size again. */
export function validateFile(file: File | null | undefined, label: string): string | null {
  if (!file) return `Please select a ${label.toLowerCase()} file.`
  const name = file.name.toLowerCase()
  if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) return `${label} must be a .pdf, .docx or .md file.`
  if (file.size > MAX_FILE_SIZE_BYTES) return `${label} must be smaller than 5MB.`
  return null
}

/** Human-readable file size, e.g. "1.2 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
