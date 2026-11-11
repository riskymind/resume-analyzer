import type { CSSProperties } from 'react'
import { Link } from 'react-router'
import type { RewriteSummary } from '../../types/api'
import { formatDateTime } from '../../utils/format'
import { scoreColor } from '../../utils/score'

const STATUS_LABEL: Record<string, string> = {
  verified: 'verified',
  needs_review: 'needs review',
  unsupported: 'unsupported edits',
}

/** Saved rewrites with their latest scores; each opens the workspace. Renaming happens in the workspace. */
export default function SavedRewrites({
  items,
  onDelete,
}: {
  items: RewriteSummary[]
  onDelete: (item: RewriteSummary) => void
}) {
  return (
    <ul className="ledger" aria-label="Saved rewrites">
      {items.map((item) => (
        <li key={item.id} className="ledger-item">
          <Link className="ledger-row" to={`/rewrites/${item.id}`}>
            <span className="ledger-filename">
              {item.name}
              <small className="report-meta">
                {' '}
                · v{item.current_version}
                {item.verification_status
                  ? ` · ${STATUS_LABEL[item.verification_status] ?? item.verification_status}`
                  : ''}
                {item.job_detached_at ? ' · target job deleted' : ''}
              </small>
            </span>
            <span className="ledger-date">{formatDateTime(item.updated_at)}</span>
            <span
              className="ledger-score"
              style={{ '--seal-color': scoreColor(item.quality_after ?? 0) } as CSSProperties}
            >
              quality {item.quality_before}→{item.quality_after}
              {item.match_after != null ? ` · match ${item.match_before}→${item.match_after}%` : ''}
            </span>
          </Link>
          <button
            type="button"
            className="btn-quiet ledger-delete"
            onClick={() => onDelete(item)}
            aria-label={`Delete rewrite ${item.name}`}
          >
            Delete
          </button>
        </li>
      ))}
    </ul>
  )
}
