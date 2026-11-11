import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError, installApi, NetworkFailure } from './test/fakeApi'
import { AUTH, RESUMES, matchDetail, rewriteDetail, summaryOf } from './test/fixtures'
import { currentLocation, renderApp, signedIn, signedOut } from './test/render'

const EMPTY_LISTS = {
  'GET /v1/resumes': [],
  'GET /v1/matches': [],
  'GET /v1/jobs': [],
  'GET /v1/rewrites': [],
  'GET /analyses': [],
}

async function signInAs(email = 'jane@example.com', password = 'correct horse battery') {
  await userEvent.type(await screen.findByLabelText('Email'), email)
  await userEvent.type(screen.getByLabelText('Password'), password)
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('protected routes', () => {
  it('sends visitors without a session to sign in, then back to the page they asked for', async () => {
    const api = signedOut({
      'POST /v1/auth/login': AUTH,
      'GET /v1/matches/match-1': matchDetail(),
    })
    renderApp('/matches/match-1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(currentLocation()).toBe('/login')
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()

    await signInAs()
    expect(await screen.findByRole('heading', { level: 1, name: 'Job match report' })).toBeInTheDocument()
    expect(currentLocation()).toBe('/matches/match-1')
    expect(api.callsTo('POST /v1/auth/login')[0]?.body).toEqual({
      email: 'jane@example.com',
      password: 'correct horse battery',
    })
  })

  it('sends signed-in users away from the sign-in page', async () => {
    signedIn(EMPTY_LISTS)
    renderApp('/login')
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()
    expect(currentLocation()).toBe('/')
  })

  it('shows a not-found page for unknown addresses, inside the app shell', async () => {
    signedIn()
    renderApp('/no/such/page')
    expect(await screen.findByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByText('/no/such/page', { selector: 'code' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to the dashboard' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(document.title).toBe('Page not found · Resume Analyzer')
  })

  it('lets the user retry when the server cannot be reached', async () => {
    let up = false
    installApi({
      'GET /v1/auth/me': () => {
        if (!up) throw new NetworkFailure()
        return AUTH
      },
      ...EMPTY_LISTS,
    })
    renderApp('/')
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the server.')
    up = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()
  })
})

describe('sessions', () => {
  it('signs the user out when the session expires, then returns them to the page they were opening', async () => {
    let expired = false
    signedIn({
      ...EMPTY_LISTS,
      'GET /v1/rewrites': [summaryOf(rewriteDetail())],
      'GET /v1/rewrites/rw-1': () =>
        expired ? apiError(401, 'not_authenticated', 'Your session has expired.') : rewriteDetail(),
      'GET /v1/rewrites/rw-1/preview': { template: 'modern', version: 1, html: '<p>x</p>' },
      'GET /v1/rewrites/templates': [],
      'POST /v1/auth/login': AUTH,
    })
    renderApp('/rewrites')
    const row = await screen.findByRole('link', { name: /^jane-doe – Senior Backend Engineer/ })

    // The session ends on the server; the next request is rejected with 401 not_authenticated.
    expired = true
    await userEvent.click(row)
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText('Your session has ended. Please sign in again.')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()

    expired = false
    await signInAs()
    expect(await screen.findByLabelText('Rewrite name')).toHaveValue('jane-doe – Senior Backend Engineer')
    expect(currentLocation()).toBe('/rewrites/rw-1')
  })

  it('after a deliberate sign-out, signing in again starts at the dashboard', async () => {
    const api = signedIn({
      ...EMPTY_LISTS,
      'POST /v1/auth/logout': () => new Response(null, { status: 204 }),
      'POST /v1/auth/login': AUTH,
    })
    renderApp('/account')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(api.callsTo('POST /v1/auth/logout')[0]?.headers['X-CSRF-Token']).toBe('csrf-test-token')
    await signInAs()
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()
  })

  it('validates the registration form accessibly before calling the server', async () => {
    const api = signedOut()
    renderApp('/login')
    const tabs = await screen.findByRole('tablist', { name: 'Account' })
    // Arrow keys move between the sign-in and registration tabs.
    within(tabs).getByRole('tab', { name: 'Sign in' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    const register = within(tabs).getByRole('tab', { name: 'Create account' })
    expect(register).toHaveFocus()
    expect(register).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { level: 1, name: 'Create your account' })).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Email'), 'new@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Password must be at least 10 characters.')
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('aria-invalid', 'true')
    expect(password).toHaveAccessibleDescription(/At least 10 characters\. Password must be at least 10 characters\./)
    expect(api.callsTo('POST /v1/auth/register')).toHaveLength(0)
  })

  it('shows the server message when sign-in fails', async () => {
    signedOut({ 'POST /v1/auth/login': apiError(401, 'invalid_credentials', 'Email or password is incorrect.') })
    renderApp('/login')
    await signInAs('jane@example.com', 'wrong password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.')
    expect(currentLocation()).toBe('/login')
  })
})

describe('navigation', () => {
  it('marks the current section and moves focus to the new page heading', async () => {
    signedIn({ ...EMPTY_LISTS, 'GET /v1/resumes': RESUMES })
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')

    await userEvent.click(within(nav).getByRole('link', { name: 'Analysis' }))
    const heading = await screen.findByRole('heading', { level: 1, name: 'Resume analysis' })
    await waitFor(() => expect(heading).toHaveFocus())
    expect(within(nav).getByRole('link', { name: 'Analysis' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute('href', '#main')
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main')
  })
})
