import { diffWords } from '../../utils/diff'

export function DiffText({ before, after, side }) {
  const parts = diffWords(before || '', after || '')
  return (
    <span className="diff-text">
      {parts.map((part, index) => {
        if (part.type === 'same') return <span key={index}>{part.text}</span>
        if (side === 'before' && part.type === 'removed')
          return (
            <del key={index} className="diff-removed">
              {part.text}
            </del>
          )
        if (side === 'after' && part.type === 'added')
          return (
            <ins key={index} className="diff-added">
              {part.text}
            </ins>
          )
        return null
      })}
    </span>
  )
}

const SEVERITY_LABEL = { blocking: 'Unsupported', warning: 'Check', info: 'Note' }

export function IssueList({ issues }) {
  if (!issues?.length) return null
  return (
    <ul className="issue-list">
      {issues.map((issue, index) => (
        <li key={index} className={`issue is-${issue.severity}`}>
          <span className="issue-tag">
            {issue.action === 'removed' ? 'Removed' : SEVERITY_LABEL[issue.severity]}
            {issue.origin === 'user' ? ' · your edit' : ''}
          </span>
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  )
}

/** The state of a suggestion in plain language, mirroring the server's "applied" rule. */
export function suggestionState(suggestion) {
  if (suggestion.verification.status === 'rejected') return { key: 'blocked', label: 'Rejected: unsupported claim' }
  if (suggestion.decision === 'rejected') return { key: 'rejected', label: 'Rejected' }
  if (suggestion.decision === 'accepted') return { key: 'accepted', label: 'Accepted' }
  if (suggestion.verification.status === 'warning') return { key: 'review', label: 'Needs your review' }
  return { key: 'applied', label: 'Applied · verified' }
}

/** One AI suggestion: original vs proposed with differences highlighted, verification and accept/reject. */
export default function SuggestionCard({ suggestion, onDecide, busy, readOnly }) {
  const state = suggestionState(suggestion)
  const blocked = state.key === 'blocked'
  const applied = state.key === 'applied' || state.key === 'accepted'
  return (
    <article className={`suggestion is-${state.key}`} aria-label={`Suggestion: ${state.label}`}>
      <header className="suggestion-head">
        <span className={`suggestion-state is-${state.key}`}>{state.label}</span>
        {suggestion.keywords.length > 0 && (
          <span className="suggestion-keywords">Keywords: {suggestion.keywords.join(', ')}</span>
        )}
      </header>
      <div className="compare-grid">
        <div className="compare-cell">
          <span className="compare-label">Original</span>
          <p className="compare-text">
            {suggestion.original ? (
              <DiffText before={suggestion.original} after={suggestion.proposed} side="before" />
            ) : (
              <em className="field-missing">nothing (new)</em>
            )}
          </p>
        </div>
        <div className="compare-cell">
          <span className="compare-label">Suggested</span>
          <p className="compare-text">
            <DiffText before={suggestion.original} after={suggestion.proposed} side="after" />
          </p>
        </div>
      </div>
      {suggestion.rationale && <p className="suggestion-why">Why: {suggestion.rationale}</p>}
      <IssueList issues={suggestion.verification.issues} />
      {!readOnly && !blocked && (
        <div className="suggestion-actions">
          <button
            type="button"
            className="btn-small"
            onClick={() => onDecide(suggestion.id, 'accepted')}
            disabled={busy || state.key === 'accepted'}
            aria-pressed={state.key === 'accepted'}
          >
            {applied ? 'Keep' : 'Accept'}
          </button>
          <button
            type="button"
            className="btn-small is-secondary"
            onClick={() => onDecide(suggestion.id, 'rejected')}
            disabled={busy || state.key === 'rejected'}
            aria-pressed={state.key === 'rejected'}
          >
            {state.key === 'rejected' ? 'Rejected' : 'Reject'}
          </button>
        </div>
      )}
      {blocked && (
        <p className="suggestion-blocked-note">
          This suggestion can't be applied. You can still edit the text yourself if the claim is true.
        </p>
      )}
    </article>
  )
}
