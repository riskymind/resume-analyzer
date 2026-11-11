import { Navigate, Outlet, useLocation, type Location } from 'react-router'
import { Loading } from '../components/ui/Feedback'
import { useAuth } from './AuthContext'

/** Where the sign-in page sends the user afterwards. */
export interface LoginState {
  from?: Pick<Location, 'pathname' | 'search' | 'hash'>
}

/**
 * Guards every signed-in route. Anonymous visitors (including users whose session just expired) are sent to
 * /login, remembering the page they wanted so they return to it after signing in.
 */
export default function RequireAuth() {
  const { status, retry, returnAfterSignIn } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <Loading>Checking your session…</Loading>

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

  if (status === 'anonymous') {
    const state: LoginState = returnAfterSignIn
      ? { from: { pathname: location.pathname, search: location.search, hash: location.hash } }
      : {}
    return <Navigate to="/login" replace state={state} />
  }

  return <Outlet />
}
