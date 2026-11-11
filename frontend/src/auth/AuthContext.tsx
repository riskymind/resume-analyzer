import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { fetchCurrentUser, logout } from '../api/auth'
import { SESSION_EXPIRED_EVENT } from '../api/client'
import type { User } from '../types/api'

export type AuthStatus = 'loading' | 'anonymous' | 'authenticated' | 'error'

export const SESSION_ENDED_NOTICE = 'Your session has ended. Please sign in again.'

interface AuthContextValue {
  status: AuthStatus
  user: User | null
  /** A message for the sign-in page, e.g. why the user was signed out. */
  notice: string | null
  /** True when the session expired: after signing in again the user returns to the page they were on. */
  returnAfterSignIn: boolean
  /** Records a successful sign-in or registration. */
  signedIn: (user: User | null) => void
  /** Ends the session on the server, then locally. */
  signOut: () => Promise<void>
  /** Forgets the session locally (it already ended on the server, e.g. account deleted). */
  signedOut: (notice?: string | null, options?: { returnAfterSignIn?: boolean }) => void
  /** Checks the session again after a failed attempt (e.g. the server was unreachable). */
  retry: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

/**
 * Owns the session state. The session itself is an HttpOnly cookie, so the client only learns about it from
 * `/auth/me`. When any request reports an expired session (401 not_authenticated), the client fires
 * SESSION_EXPIRED_EVENT and the user is signed out here, which sends them to the sign-in page.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [returnAfterSignIn, setReturnAfterSignIn] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((current) => {
        if (cancelled) return
        setUser(current)
        setStatus(current ? 'authenticated' : 'anonymous')
      })
      .catch(() => {
        if (!cancelled) setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  const signedOut = useCallback((nextNotice: string | null = null, { returnAfterSignIn: returnHere = false } = {}) => {
    setUser(null)
    setNotice(nextNotice)
    setReturnAfterSignIn(returnHere)
    setStatus('anonymous')
  }, [])

  useEffect(() => {
    const handleExpired = () => signedOut(SESSION_ENDED_NOTICE, { returnAfterSignIn: true })
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired)
  }, [signedOut])

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      notice,
      returnAfterSignIn,
      signedIn: (next) => {
        setUser(next)
        setNotice(null)
        setReturnAfterSignIn(true)
        setStatus(next ? 'authenticated' : 'anonymous')
      },
      signOut: async () => {
        try {
          await logout()
        } finally {
          signedOut()
        }
      },
      signedOut,
      retry: () => {
        setStatus('loading')
        setAttempt((n) => n + 1)
      },
    }),
    [status, user, notice, returnAfterSignIn, signedOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>.')
  return context
}

/** The signed-in user. Only for components rendered behind <RequireAuth>. */
export function useUser(): User {
  const { user } = useAuth()
  if (!user) throw new Error('useUser needs a signed-in user (render it behind <RequireAuth>).')
  return user
}
