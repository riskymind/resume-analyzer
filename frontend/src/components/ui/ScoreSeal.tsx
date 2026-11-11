import type { CSSProperties } from 'react'
import { scoreColor } from '../../utils/score'

interface ScoreSealProps {
  score: number
  /** "/ 100" or "%". */
  unit?: '/ 100' | '%'
  /** What the score measures, for screen readers, e.g. "Resume quality". */
  label: string
}

/**
 * The stamped score seal. The number always comes from the API; the colour only mirrors the API's label
 * thresholds. Screen readers hear "Resume quality: 72 out of 100" instead of two loose numbers.
 */
export default function ScoreSeal({ score, unit = '/ 100', label }: ScoreSealProps) {
  const spoken = unit === '%' ? `${label}: ${score}%` : `${label}: ${score} out of 100`
  return (
    <div
      className="score-seal"
      style={{ '--seal-color': scoreColor(score) } as CSSProperties}
      role="img"
      aria-label={spoken}
    >
      <span className="score-value" aria-hidden="true">
        {score}
      </span>
      <span className="score-max" aria-hidden="true">
        {unit}
      </span>
    </div>
  )
}
