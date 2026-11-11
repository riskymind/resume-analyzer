import { useId, useState, type FormEvent } from 'react'
import { DELETE_CONFIRMATION_PHRASE, deleteAccount } from '../api/auth'

/**
 * Permanent account deletion. Requires the current password and the exact
 * confirmation phrase, mirroring the server-side checks.
 */
export default function DeleteAccountPanel({ email, onDeleted }: { email: string; onDeleted: () => void }) {
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const passwordId = useId()
  const confirmId = useId()
  const errorId = useId()
  const confirmed = confirmation === DELETE_CONFIRMATION_PHRASE

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!confirmed) return
    setError(null)
    setSubmitting(true)
    try {
      await deleteAccount({ password, confirmation })
      onDeleted()
    } catch (err) {
      setError((err as Error).message)
      setSubmitting(false)
    }
  }

  return (
    <section className="auth-panel danger-zone" aria-labelledby="delete-title">
      <h2 id="delete-title">Delete account</h2>
      <p className="panel-hint">
        This permanently deletes <strong>{email}</strong>, every saved resume, analysis, job description, match and
        rewrite, and signs you out on all devices. It cannot be undone.
      </p>

      <form onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor={passwordId}>Current password</label>
          <input
            id={passwordId}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            aria-describedby={error ? errorId : undefined}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor={confirmId}>
            Type <code>{DELETE_CONFIRMATION_PHRASE}</code> to confirm
          </label>
          <input
            id={confirmId}
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
          />
        </div>

        {error && (
          <p className="form-flag" role="alert" id={errorId}>
            <span>{error}</span>
          </p>
        )}

        <div className="submit-row">
          <button className="btn-primary btn-danger" type="submit" disabled={!confirmed || !password || submitting}>
            {submitting ? 'Deleting…' : 'Delete my account'}
          </button>
        </div>
      </form>
    </section>
  )
}
