import { describe, expect, it } from 'vitest'
import { diffWords } from './diff'

describe('diffWords', () => {
  it('marks replaced words and keeps unchanged text together', () => {
    expect(diffWords('Built Python APIs quickly', 'Designed Python APIs quickly')).toEqual([
      { type: 'removed', text: 'Built' },
      { type: 'added', text: 'Designed' },
      { type: 'same', text: ' Python APIs quickly' },
    ])
  })

  it('treats case and surrounding whitespace as the same word', () => {
    expect(diffWords('python  apis', 'Python apis').every((part) => part.type === 'same')).toBe(true)
  })

  it('handles empty inputs (a new item has no original)', () => {
    expect(diffWords('', 'New bullet')).toEqual([{ type: 'added', text: 'New bullet' }])
    expect(diffWords('Old bullet', '')).toEqual([{ type: 'removed', text: 'Old bullet' }])
    expect(diffWords('', '')).toEqual([])
  })

  it('falls back to a whole replacement for pathologically long input instead of freezing', () => {
    const long = Array.from({ length: 600 }, (_, i) => `w${i}`).join(' ')
    const other = Array.from({ length: 600 }, (_, i) => `x${i}`).join(' ')
    expect(diffWords(long, other)).toEqual([
      { type: 'removed', text: long },
      { type: 'added', text: other },
    ])
  })
})
