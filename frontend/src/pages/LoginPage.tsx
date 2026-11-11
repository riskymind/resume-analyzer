import { Navigate, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import type { LoginState } from '../auth/RequireAuth'
import AuthPanel from '../components/AuthPanel'
import { Loading } from '../components/ui/Feedback'
import { usePageTitle } from '../hooks/usePageTitle'

/** Sign in or register, then return to the page the user originally asked for. */
export default function LoginPage() {
  const { status, notice, signedIn, retry } = useAuth()
  const location = useLocation()
  usePageTitle('Sign in')

  const from = (location.state as LoginState | null)?.from
  const destination = from && from.pathname !== '/login' ? `${from.pathname}${from.search}${from.hash}` : '/'

  if (status === 'loading') return <Loading>Checking your session…</Loading>
  if (status === 'authenticated') return <Navigate to={destination} replace />
  if (status === 'error') {
    return (
      <div className="error-state" role="alert">
        <p className="error-state-title">Could not reach the server.</p>
        <p className="report-meta">Check that the backend is running and your connection works, then try again.</p>
        <button type="button" className="btn-small" onClick={retry}>
          Try again
        </button>
      </div>
    )
  }
  return <AuthPanel onAuthenticated={signedIn} notice={notice} />
}
