import type { CSSProperties } from 'react'
import { Link } from 'react-router'
import type { AnalysisListItem } from '../types/api'
import { formatDateTime } from '../utils/format'
import { scoreColor } from '../utils/score'

/** Past quick reviews; each opens its full report. */
export default function HistoryList({ items }: { items: AnalysisListItem[] }) {
  return (
    <ul className="ledger" aria-label="Past quick reviews">
      {items.map((item) => (
        <li key={item.id}>
          <Link className="ledger-row" to={`/reviews/${item.id}`}>
            <span className="ledger-filename">{item.resume_filename}</span>
            <span className="ledger-date">{formatDateTime(item.created_at)}</span>
            <span className="ledger-score" style={{ '--seal-color': scoreColor(item.score) } as CSSProperties}>
              {item.score}/100 — {item.score_label}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}
