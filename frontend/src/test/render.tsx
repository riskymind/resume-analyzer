import { render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'
import { apiError, installApi, type FakeApi } from './fakeApi'
import { AUTH } from './fixtures'

/** Exposes the current URL to assertions (`screen.getByTestId('location')`). */
function LocationProbe() {
  const location = useLocation()
  return (
    <output data-testid="location" hidden>
      {location.pathname}
      {location.search}
    </output>
  )
}

/** Renders the whole app (router, auth, routes) at `path`, as a user would see it. */
export function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
        <LocationProbe />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** Installs the fake backend for a signed-in user, plus `routes`. */
export function signedIn(routes: Parameters<typeof installApi>[0] = {}): FakeApi {
  return installApi({ 'GET /v1/auth/me': AUTH, ...routes })
}

/** Installs the fake backend for a visitor without a session. */
export function signedOut(routes: Parameters<typeof installApi>[0] = {}): FakeApi {
  return installApi({
    'GET /v1/auth/me': apiError(401, 'not_authenticated', 'Not signed in.'),
    ...routes,
  })
}

/** The current path + query of the in-memory router. */
export function currentLocation(): string {
  return screen.getByTestId('location').textContent ?? ''
}
