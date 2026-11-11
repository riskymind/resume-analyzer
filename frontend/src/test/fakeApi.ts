// A fake backend at the network boundary (fetch and XMLHttpRequest). Tests register handlers by "METHOD /path"
// (the path after /api, without the query string) and the real API client, components and error handling run
// unchanged. Nothing here talks to a real server or AI provider.
import { vi } from 'vitest'

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

/** The backend's error envelope. */
export function apiError(status: number, code: string, detail: string): Response {
  return jsonResponse({ detail, error: { code, message: detail, request_id: 'test' } }, status)
}

/** Makes the request fail as if the network were down. */
export class NetworkFailure extends Error {}

export interface Call {
  method: string
  path: string
  query: Record<string, string>
  body: unknown
  headers: Record<string, string>
}

type HandlerResult = unknown
type Handler = HandlerResult | ((call: Call) => HandlerResult | Promise<HandlerResult>)

export interface FakeApi {
  calls: Call[]
  fetch: ReturnType<typeof vi.fn>
  route: (key: string, handler: Handler) => void
  callsTo: (key: string) => Call[]
}

/**
 * Installs the fake backend. `routes` maps "METHOD /v1/path" to a response body, a Response, or a function
 * (call) => body | Response | Promise. A handler that throws `NetworkFailure` simulates a network error.
 * Every request (fetch or XHR) is recorded in `calls`.
 */
export function installApi(routes: Record<string, Handler> = {}): FakeApi {
  const calls: Call[] = []
  const table: Record<string, Handler> = { ...routes }

  async function dispatch(input: string, method: string, rawBody: unknown, headers: Record<string, string>) {
    const url = new URL(input, 'http://localhost')
    const path = url.pathname.replace(/^\/api/, '')
    const key = `${method} ${path}`
    let body = rawBody
    if (typeof body === 'string') {
      try {
        body = JSON.parse(body)
      } catch {
        // keep the raw string
      }
    }
    const call: Call = { method, path, query: Object.fromEntries(url.searchParams), body, headers }
    calls.push(call)
    if (!(key in table)) return apiError(404, 'not_found', `No fake route for ${key}`)
    const handler = table[key]
    const result = typeof handler === 'function' ? await (handler as (c: Call) => unknown)(call) : handler
    if (result instanceof Response) return result
    return jsonResponse(result)
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    try {
      return await dispatch(
        String(input),
        (init.method || 'GET').toUpperCase(),
        init.body,
        (init.headers as Record<string, string>) || {},
      )
    } catch (err) {
      if (err instanceof NetworkFailure) throw new TypeError('Failed to fetch')
      throw err
    }
  })

  /** Enough of XMLHttpRequest for `apiUpload`: headers, upload progress, load/error/abort. */
  class FakeXMLHttpRequest {
    upload: { onprogress: ((event: Partial<ProgressEvent>) => void) | null } = { onprogress: null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    onabort: (() => void) | null = null
    status = 0
    responseText = ''
    withCredentials = false
    private method = 'GET'
    private url = ''
    private headers: Record<string, string> = {}
    private aborted = false

    open(method: string, url: string) {
      this.method = method.toUpperCase()
      this.url = url
    }

    setRequestHeader(name: string, value: string) {
      this.headers[name] = value
    }

    abort() {
      this.aborted = true
      this.onabort?.()
    }

    async send(body: unknown) {
      const total = body instanceof FormData ? sizeOf(body) : 100
      this.upload.onprogress?.({ loaded: Math.floor(total / 2), total, lengthComputable: true })
      let response: Response
      try {
        response = await dispatch(this.url, this.method, body, this.headers)
      } catch (err) {
        if (this.aborted) return
        if (err instanceof NetworkFailure) return this.onerror?.()
        throw err
      }
      if (this.aborted) return
      this.upload.onprogress?.({ loaded: total, total, lengthComputable: true })
      this.status = response.status
      this.responseText = await response.text()
      this.onload?.()
    }
  }

  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('XMLHttpRequest', FakeXMLHttpRequest)
  return {
    calls,
    fetch: fetchMock,
    route(key, handler) {
      table[key] = handler
    },
    callsTo(key) {
      return calls.filter((call) => `${call.method} ${call.path}` === key)
    },
  }
}

function sizeOf(form: FormData): number {
  let size = 0
  form.forEach((value) => {
    size += typeof value === 'string' ? value.length : value.size
  })
  return Math.max(size, 1)
}
