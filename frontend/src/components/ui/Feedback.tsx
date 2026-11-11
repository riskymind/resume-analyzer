import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../../api/client'

/** An error message, announced to screen readers as soon as it appears. */
export function Flag({ message, id }: { message: string | null | undefined; id?: string }) {
  if (!message) return null
  return (
    <p className="form-flag" role="alert" id={id}>
      <span>{message}</span>
    </p>
  )
}

/** A loading line, announced politely. */
export function Loading({ children = 'Loading…' }: { children?: ReactNode }) {
  return (
    <p className="empty-note" role="status">
      {children}
    </p>
  )
}

/** A confirmation that something worked, announced politely. */
export function SuccessNote({ children }: { children: ReactNode }) {
  return (
    <p className="success-note" role="status">
      {children}
    </p>
  )
}

/** Nothing here yet: an explanation and, usually, the next step. */
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <p className="empty-note">{children}</p>
      {action}
    </div>
  )
}

interface ErrorStateProps {
  error: Error
  onRetry?: () => void
  /** What could not be found, e.g. "resume". Shown when the API answers 404. */
  resource?: string
  /** Where to go instead when the resource is missing. */
  back?: { to: string; label: string }
}

/**
 * A failed load. A 404 means the item does not exist or belongs to someone else (the API does not distinguish),
 * so it gets a "not found" message and a way back instead of a pointless Retry.
 */
export function ErrorState({ error, onRetry, resource, back }: ErrorStateProps) {
  if (resource && error instanceof ApiError && error.isNotFound) {
    return (
      <div className="error-state" role="alert">
        <p className="error-state-title">This {resource} could not be found.</p>
        <p className="report-meta">It may have been deleted, or the link may be wrong.</p>
        {back && (
          <Link className="btn-small is-secondary" to={back.to}>
            {back.label}
          </Link>
        )}
      </div>
    )
  }
  return (
    <div className="error-state" role="alert">
      <p className="error-state-title">{error.message}</p>
      <div className="error-state-actions">
        {onRetry && (
          <button type="button" className="btn-small" onClick={onRetry}>
            Try again
          </button>
        )}
        {back && (
          <Link className="btn-small is-secondary" to={back.to}>
            {back.label}
          </Link>
        )}
      </div>
    </div>
  )
}
