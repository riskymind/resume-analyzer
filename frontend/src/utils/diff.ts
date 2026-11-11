/**
 * Word-level diff for before/after comparisons (longest common subsequence).
 * Returns [{ type: 'same' | 'added' | 'removed', text }]. Whitespace is kept
 * with the following word so the output reads naturally.
 */
export type DiffPart = { type: 'same' | 'added' | 'removed'; text: string }

export function diffWords(before = '', after = ''): DiffPart[] {
  const a = tokenize(before)
  const b = tokenize(after)
  // Resumes are short; cap the matrix so a pathological input cannot freeze the page.
  if (a.length * b.length > 250000) {
    return [
      { type: 'removed', text: before },
      { type: 'added', text: after },
    ]
  }
  const na = a.map(norm)
  const nb = b.map(norm)
  const rows = a.length + 1
  const cols = b.length + 1
  const table = new Uint16Array(rows * cols)
  const cell = (i: number, j: number) => table[i * cols + j] ?? 0
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i * cols + j] = na[i] === nb[j] ? cell(i + 1, j + 1) + 1 : Math.max(cell(i + 1, j), cell(i, j + 1))
    }
  }
  const parts: DiffPart[] = []
  const push = (type: DiffPart['type'], text: string) => {
    const last = parts[parts.length - 1]
    if (last && last.type === type) last.text += text
    else parts.push({ type, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (na[i] === nb[j]) {
      push('same', b[j] ?? '')
      i++
      j++
    } else if (cell(i + 1, j) >= cell(i, j + 1)) {
      push('removed', a[i++] ?? '')
    } else {
      push('added', b[j++] ?? '')
    }
  }
  while (i < a.length) push('removed', a[i++] ?? '')
  while (j < b.length) push('added', b[j++] ?? '')
  return parts
}

function tokenize(text: string): string[] {
  return (text || '').match(/\s*\S+/g) || []
}

function norm(token: string): string {
  return token.trim().toLowerCase()
}
