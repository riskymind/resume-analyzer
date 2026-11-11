// Static checks of vercel.json, plus a small EMULATION of how Vercel walks the `routes` list (in order; a route
// with `continue: true` only adds headers; `handle: filesystem` serves an existing file). This guards the intent of
// the configuration (API never swallowed by the SPA fallback, deep links get index.html, no secrets or backend URL
// in the file) but it is not Vercel itself: real behaviour is only proven by a preview deployment
// (docs/deploy-vercel.md, "Verify after deploying").
import { describe, expect, it } from 'vitest'
import vercelJson from '../../vercel.json'

interface Route {
  src?: string
  dest?: string
  status?: number
  headers?: Record<string, string>
  continue?: boolean
  handle?: string
  env?: string[]
  transforms?: { type: string; op: string; target: { key: string }; args: string; env?: string[] }[]
}

const config = vercelJson as { routes: Route[]; outputDirectory: string; buildCommand: string }
const raw = JSON.stringify(vercelJson)

const BUILT_FILES = new Set(['/index.html', '/assets/index-abc123.js', '/assets/index-abc123.css'])

type Outcome = { kind: 'proxy'; to: string } | { kind: 'file'; path: string } | { kind: 'status'; status: number }

function resolve(pathname: string): { outcome: Outcome; headers: Record<string, string> } {
  const headers: Record<string, string> = {}
  for (const route of config.routes) {
    if (route.handle === 'filesystem') {
      if (BUILT_FILES.has(pathname)) return { outcome: { kind: 'file', path: pathname }, headers }
      continue
    }
    const match = new RegExp(`^${route.src}$`).exec(pathname)
    if (!match) continue
    Object.assign(headers, route.headers)
    if (route.continue) continue
    if (route.status) return { outcome: { kind: 'status', status: route.status }, headers }
    const dest = (route.dest ?? '').replace(/\$(\d)/g, (_, i: string) => match[Number(i)] ?? '')
    return dest.startsWith('${')
      ? { outcome: { kind: 'proxy', to: dest }, headers }
      : { outcome: { kind: 'file', path: dest }, headers }
  }
  return { outcome: { kind: 'status', status: 404 }, headers }
}

describe('vercel.json', () => {
  it('builds the existing Vite app', () => {
    expect(config.buildCommand).toBe('npm run build')
    expect(config.outputDirectory).toBe('dist')
  })

  it.each([
    '/api/v1/auth/me',
    '/api/v1/rewrites/abc/export',
    '/api/health',
    '/api/v1/resumes/5f1c/analyses',
    '/api/index.html',
    '/api/assets/x.js',
  ])('forwards %s to the backend, never to the SPA', (pathname) => {
    const { outcome } = resolve(pathname)
    expect(outcome).toEqual({ kind: 'proxy', to: `\${BACKEND_URL}${pathname}` })
  })

  it.each([
    '/',
    '/upload',
    '/resumes/9b2d',
    '/reviews/12',
    '/matches/7c1e',
    '/jobs/a1b2',
    '/rewrites/0f3c',
    '/account',
    '/definitely/not/here',
  ])('serves index.html for the client-side route %s (deep link / reload)', (pathname) => {
    expect(resolve(pathname).outcome).toEqual({ kind: 'file', path: '/index.html' })
  })

  it('serves built assets as files and a missing asset as 404, not HTML', () => {
    expect(resolve('/assets/index-abc123.js').outcome).toEqual({ kind: 'file', path: '/assets/index-abc123.js' })
    expect(resolve('/assets/index-abc123.js').headers['Cache-Control']).toContain('immutable')
    expect(resolve('/assets/old-hash.js').outcome).toEqual({ kind: 'status', status: 404 })
  })

  it('adds the security headers everywhere, API included', () => {
    for (const pathname of ['/', '/rewrites/1', '/api/v1/auth/me']) {
      expect(resolve(pathname).headers).toMatchObject({
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
      })
    }
  })

  it('reads the backend URL and access key from server-side environment variables only', () => {
    const api = config.routes.find((route) => route.src === '/api/(.*)')
    expect(api?.env).toEqual(['BACKEND_URL'])
    expect(api?.transforms).toEqual([
      {
        type: 'request.headers',
        op: 'set',
        target: { key: 'x-backend-access-key' },
        args: '$BACKEND_ACCESS_KEY',
        env: ['BACKEND_ACCESS_KEY'],
      },
    ])
    // No hard-coded backend origin, no browser-exposed variable names.
    expect(raw).not.toMatch(/https?:\/\/(?!openapi\.vercel\.sh)/)
    expect(raw).not.toMatch(/VITE_|NEXT_PUBLIC_/)
  })

  it('puts the API route before the filesystem and the SPA fallback last', () => {
    const index = (predicate: (route: Route) => boolean) => config.routes.findIndex(predicate)
    const api = index((route) => route.src === '/api/(.*)')
    const filesystem = index((route) => route.handle === 'filesystem')
    const fallback = index((route) => route.dest === '/index.html')
    expect(api).toBeGreaterThanOrEqual(0)
    expect(api).toBeLessThan(filesystem)
    expect(fallback).toBe(config.routes.length - 1)
  })
})
