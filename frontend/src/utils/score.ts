/**
 * Score-tier colour, aligned with the backend's label thresholds
 * (Strong >= 80, Good >= 60, Fair >= 40, Weak < 40) so a colour never
 * contradicts the label shown beside it.
 */
export function scoreColor(score: number): string {
  if (score >= 80) return 'var(--accent-teal)' // Strong Match
  if (score >= 40) return 'var(--accent-ochre)' // Good / Fair Match
  return 'var(--accent-brick)' // Weak Match
}
