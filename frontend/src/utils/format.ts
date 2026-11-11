/** Date and time as the browser's locale writes it. */
export function formatDateTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : ''
}

/** Date only, in the browser's locale. */
export function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleDateString() : ''
}

/** "1 resume" / "3 resumes". */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`
}
