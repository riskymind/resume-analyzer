import type { AuthResponse, User } from '../types/api'
import { ApiError, apiRequest, setCsrfToken } from './client'

export const DELETE_CONFIRMATION_PHRASE = 'delete my account'

function remember(session: AuthResponse | null): User | null {
  setCsrfToken(session?.csrf_token)
  return session?.user ?? null
}

export interface Credentials {
  email: string
  password: string
}

/** Returns the signed-in user, or null when there is no valid session. */
export async function fetchCurrentUser(): Promise<User | null> {
  try {
    return remember(await apiRequest<AuthResponse>('/v1/auth/me'))
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      setCsrfToken(null)
      return null
    }
    throw err
  }
}

export async function register({ email, password }: Credentials): Promise<User | null> {
  return remember(await apiRequest<AuthResponse>('/v1/auth/register', { method: 'POST', json: { email, password } }))
}

export async function login({ email, password }: Credentials): Promise<User | null> {
  return remember(await apiRequest<AuthResponse>('/v1/auth/login', { method: 'POST', json: { email, password } }))
}

export async function logout(): Promise<void> {
  try {
    await apiRequest<null>('/v1/auth/logout', { method: 'POST' })
  } finally {
    setCsrfToken(null)
  }
}

/** Permanently deletes the account and all of its data. */
export async function deleteAccount({ password, confirmation }: { password: string; confirmation: string }) {
  await apiRequest<null>('/v1/auth/me', { method: 'DELETE', json: { password, confirmation } })
  setCsrfToken(null)
}
