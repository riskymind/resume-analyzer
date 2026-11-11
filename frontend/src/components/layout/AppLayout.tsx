import { useEffect, useRef } from 'react'
import { Link, Outlet, useLocation } from 'react-router'
import { useAuth } from '../../auth/AuthContext'

interface NavItem {
  to: string
  label: string
  /** Path prefixes that belong to this section, so detail pages keep their section highlighted. */
  section: string[]
}

const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', section: [] },
  { to: '/upload', label: 'Upload', section: ['/upload'] },
  { to: '/resumes', label: 'Analysis', section: ['/resumes', '/reviews'] },
  { to: '/match', label: 'Job match', section: ['/match', '/matches', '/jobs'] },
  { to: '/rewrite', label: 'Rewriter', section: ['/rewrite', '/rewrites'] },
  { to: '/account', label: 'Account', section: ['/account'] },
]

function isActive(item: NavItem, pathname: string): boolean {
  if (item.to === '/') return pathname === '/'
  return item.section.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))
}

/** Pages that need the full width (side-by-side editing, dashboards). */
const WIDE = [/^\/$/, /^\/rewrites?(\/|$)/]

/**
 * The application shell. After every navigation it moves focus to the new page's <h1>, so keyboard and
 * screen-reader users start at the top of the new content instead of on a stale link.
 */
export default function AppLayout() {
  const { status } = useAuth()
  const location = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const interacted = useRef(false)

  // Only navigations that follow user interaction move focus. On a fresh page load (including automatic redirects,
  // e.g. to /login) focus stays at the top of the document, so the skip link is the first Tab stop.
  useEffect(() => {
    const mark = () => {
      interacted.current = true
    }
    window.addEventListener('keydown', mark, { capture: true, once: true })
    window.addEventListener('pointerdown', mark, { capture: true, once: true })
    return () => {
      window.removeEventListener('keydown', mark, { capture: true })
      window.removeEventListener('pointerdown', mark, { capture: true })
    }
  }, [])

  useEffect(() => {
    if (!interacted.current) return
    // Wait a frame so the new page (and its heading) is in the DOM.
    const frame = requestAnimationFrame(() => {
      const heading = mainRef.current?.querySelector<HTMLElement>('h1')
      ;(heading ?? mainRef.current)?.focus({ preventScroll: false })
    })
    return () => cancelAnimationFrame(frame)
  }, [location.pathname])

  const signedIn = status === 'authenticated'
  const wide = signedIn && WIDE.some((pattern) => pattern.test(location.pathname))

  return (
    <div className={`app-shell ${wide ? 'is-wide' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="app-header">
        <Link to="/" className="app-wordmark">
          Resume Analyzer
        </Link>
        {signedIn && (
          <nav className="app-nav" aria-label="Main">
            {NAV.map((item) => {
              const active = isActive(item, location.pathname)
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={active ? 'is-active' : ''}
                  // "page" on the section's own page; "true" on its detail pages (still the current section).
                  aria-current={location.pathname === item.to ? 'page' : active ? 'true' : undefined}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
        )}
      </header>
      <main id="main" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
