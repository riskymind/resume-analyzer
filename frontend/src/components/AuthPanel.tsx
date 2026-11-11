import { useId, useState, type FormEvent } from 'react'
import { login, register } from '../api/auth'
import type { User } from '../types/api'
import Tabs from './ui/Tabs'

const MIN_PASSWORD_LENGTH = 10

type Mode = 'signin' | 'register'

/** Sign-in / create-account form. Calls onAuthenticated(user) on success. */
export default function AuthPanel({
  onAuthenticated,
  notice,
}: {
  onAuthenticated: (user: User | null) => void
  notice?: string | null
}) {
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<{ message: string; field: 'email' | 'password' | null } | null>(null)
  const emailId = useId()
  const passwordId = useId()
  const passwordHintId = useId()
  const errorId = useId()
  const isRegister = mode === 'register'

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!email.trim()) return setError({ message: 'Enter your email address.', field: 'email' })
    if (!password) return setError({ message: 'Enter your password.', field: 'password' })
    if (isRegister && password.length < MIN_PASSWORD_LENGTH) {
      return setError({ message: `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`, field: 'password' })
    }
    setSubmitting(true)
    try {
      const user = await (isRegister ? register : login)({ email, password })
      setPassword('')
      onAuthenticated(user)
    } catch (err) {
      setError({ message: (err as Error).message, field: null })
      setSubmitting(false)
    }
  }

  const describe = (field: 'email' | 'password', hint?: string) =>
    [hint, error && (error.field === field || error.field === null) ? errorId : null].filter(Boolean).join(' ') ||
    undefined

  return (
    <section className="auth-panel" aria-labelledby="auth-title">
      <h1 id="auth-title" className="auth-title" tabIndex={-1}>
        {isRegister ? 'Create your account' : 'Sign in'}
      </h1>
      <p className="panel-hint">Your resumes and reviews are private to your account.</p>

      <Tabs<Mode>
        label="Account"
        items={[
          { key: 'signin', label: 'Sign in' },
          { key: 'register', label: 'Create account' },
        ]}
        value={mode}
        onChange={(next) => {
          setMode(next)
          setError(null)
        }}
      >
        {notice && !error && (
          <p className="auth-notice" role="status">
            {notice}
          </p>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor={emailId}>Email</label>
            <input
              id={emailId}
              type="email"
              autoComplete="email"
              required
              value={email}
              aria-invalid={error?.field === 'email' || undefined}
              aria-describedby={describe('email')}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor={passwordId}>Password</label>
            <input
              id={passwordId}
              type="password"
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              required
              minLength={isRegister ? MIN_PASSWORD_LENGTH : undefined}
              value={password}
              aria-invalid={error?.field === 'password' || undefined}
              aria-describedby={describe('password', isRegister ? passwordHintId : undefined)}
              onChange={(e) => setPassword(e.target.value)}
            />
            {isRegister && <small id={passwordHintId}>At least {MIN_PASSWORD_LENGTH} characters.</small>}
          </div>

          {error && (
            <p className="form-flag" role="alert" id={errorId}>
              <span>{error.message}</span>
            </p>
          )}

          <div className="submit-row">
            <button className="btn-primary" type="submit" disabled={submitting}>
              {submitting ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
            </button>
          </div>
        </form>
      </Tabs>
    </section>
  )
}
