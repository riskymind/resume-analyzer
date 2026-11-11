// Shared HTTP client for the backend API.
//
// Relative by default: the dev server, nginx and Vercel all proxy /api to the
// backend, so requests stay same-origin and the HttpOnly session cookie is
// sent automatically. VITE_API_BASE_URL is an optional override.
import type { ErrorEnvelope } from '../types/api'

const API_ROOT = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

const NETWORK_ERROR = 'Could not reach the server. Check your connection and try again.'

// The CSRF token is bound to the server-side session. It is kept in memory
// only (never localStorage) and re-fetched from /auth/me after a reload.
let csrfToken: string | null = null

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token || null
}

/** Fired when the server says the session is missing or expired. */
export const SESSION_EXPIRED_EVENT = 'auth:session-expired'

export class ApiError extends Error {
  readonly status: number
  readonly code: string | undefined

  constructor(message: string, { status = 0, code }: { status?: number; code?: string } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }

  /** The resource does not exist, or belongs to another user (the API answers 404 for both). */
  get isNotFound(): boolean {
    return this.status === 404
  }
}

/** Builds the ApiError for a failed response, and announces an expired session. */
function failure(status: number, payload: ErrorEnvelope | null, fallback: string): ApiError {
  const code = payload?.error?.code
  if (status === 401 && code === 'not_authenticated') window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
  return new ApiError(payload?.detail || payload?.error?.message || fallback, { status, code })
}

function writeHeaders(json: boolean): Record<string, string> {
  const headers: Record<string, string> = {}
  if (json) headers['Content-Type'] = 'application/json'
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken
  return headers
}

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE'

export interface RequestOptions {
  method?: HttpMethod
  /** A value to send as a JSON body. */
  json?: unknown
  /** A FormData (or other BodyInit) to send as-is. */
  body?: BodyInit
  signal?: AbortSignal
}

/** Performs a request against the API and returns the parsed JSON body (`null` for 204 No Content). */
export async function apiRequest<T>(
  path: string,
  { method = 'GET', json, body, signal }: RequestOptions = {},
): Promise<T> {
  const headers = SAFE_METHODS.has(method)
    ? json !== undefined
      ? { 'Content-Type': 'application/json' }
      : {}
    : writeHeaders(json !== undefined)

  let res: Response
  try {
    res = await fetch(`${API_ROOT}${path}`, {
      method,
      headers,
      body: json !== undefined ? JSON.stringify(json) : body,
      credentials: 'same-origin',
      signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(NETWORK_ERROR, { status: 0 })
  }

  if (res.status === 204) return null as T

  const payload: unknown = await res.json().catch(() => null)
  if (!res.ok) throw failure(res.status, payload as ErrorEnvelope | null, `Request failed with status ${res.status}`)
  return payload as T
}

export interface DownloadedFile {
  blob: Blob
  filename: string
}

/**
 * POSTs a JSON body and returns the response as a downloadable file. Used for
 * exports, which are generated on demand and never stored on the server.
 */
export async function apiDownload(path: string, { json }: { json?: unknown } = {}): Promise<DownloadedFile> {
  let res: Response
  try {
    res = await fetch(`${API_ROOT}${path}`, {
      method: 'POST',
      headers: writeHeaders(true),
      body: JSON.stringify(json ?? {}),
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError(NETWORK_ERROR, { status: 0 })
  }
  if (!res.ok) {
    const payload = (await res.json().catch(() => null)) as ErrorEnvelope | null
    throw failure(res.status, payload, `Download failed with status ${res.status}`)
  }
  const disposition = res.headers.get('Content-Disposition') || ''
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] || 'resume'
  return { blob: await res.blob(), filename }
}

export interface UploadProgress {
  /** Bytes sent so far. */
  loaded: number
  /** Total bytes, when the browser knows it. */
  total: number | null
}

/**
 * POSTs a FormData with upload progress (fetch cannot report upload progress, so this uses XMLHttpRequest).
 * Errors, CSRF and session expiry are handled exactly as in `apiRequest`.
 */
export function apiUpload<T>(
  path: string,
  form: FormData,
  { onProgress, signal }: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal } = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_ROOT}${path}`)
    xhr.withCredentials = false // same-origin requests send cookies regardless
    for (const [name, value] of Object.entries(writeHeaders(false))) xhr.setRequestHeader(name, value)
    xhr.upload.onprogress = (event: ProgressEvent) => {
      onProgress?.({ loaded: event.loaded, total: event.lengthComputable ? event.total : null })
    }
    xhr.onerror = () => reject(new ApiError(NETWORK_ERROR, { status: 0 }))
    xhr.onabort = () => reject(new DOMException('Upload cancelled.', 'AbortError'))
    xhr.onload = () => {
      let payload: unknown = null
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        payload = null
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload as T)
      else reject(failure(xhr.status, payload as ErrorEnvelope | null, `Upload failed with status ${xhr.status}`))
    }
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(form)
  })
}
