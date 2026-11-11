import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError } from '../test/fakeApi'
import { ANALYSES, JOBS, MATCHES, RESUMES, resumeDetail, rewriteDetail, summaryOf } from '../test/fixtures'
import { renderApp, signedIn } from '../test/render'

const panel = (name: string) => screen.getByRole('region', { name })

describe('dashboard', () => {
  it('shows real saved activity with links to each item', async () => {
    signedIn({
      'GET /v1/resumes': RESUMES,
      'GET /v1/resumes/res-1': resumeDetail(),
      'GET /v1/matches': MATCHES,
      'GET /v1/jobs': JOBS,
      'GET /v1/rewrites': [summaryOf(rewriteDetail())],
      'GET /analyses': ANALYSES,
    })
    renderApp('/')
    expect(await screen.findByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()

    const resumes = panel('Resumes')
    expect(await within(resumes).findByRole('link', { name: 'jane-doe.md' })).toHaveAttribute('href', '/resumes/res-1')
    expect(within(resumes).getByRole('img', { name: 'Resume quality: 70 out of 100' })).toBeInTheDocument()
    expect(within(resumes).getByText(/ATS compatibility estimate 82\/100/)).toBeInTheDocument()
    expect(within(resumes).getByText('Latest of 2 resumes', { exact: false })).toBeInTheDocument()
    // Improvement suggestions come from the latest resume's stored quality report.
    expect(await within(resumes).findByText('Describe the outcome of your work.')).toBeInTheDocument()
    expect(within(resumes).getByRole('link', { name: 'old-cv.pdf' })).toHaveAttribute('href', '/resumes/res-2')

    const matches = panel('Recent job matches')
    expect(within(matches).getByRole('link', { name: 'Senior Backend Engineer' })).toHaveAttribute(
      'href',
      '/matches/match-1',
    )
    expect(within(matches).getByText(/64% · jane-doe.md/)).toBeInTheDocument()

    expect(
      within(panel('Saved job descriptions')).getByRole('link', { name: /Senior Backend Engineer · Globex/ }),
    ).toHaveAttribute('href', '/jobs/job-1')
    expect(
      within(panel('Recent rewrites')).getByRole('link', { name: /jane-doe – Senior Backend Engineer/ }),
    ).toHaveAttribute('href', '/rewrites/rw-1')
    expect(within(panel('Quick reviews')).getByRole('link', { name: 'quick-cv.pdf' })).toHaveAttribute(
      'href',
      '/reviews/7',
    )
  })

  it('guides a new user with empty states and no invented numbers', async () => {
    signedIn({
      'GET /v1/resumes': [],
      'GET /v1/matches': [],
      'GET /v1/jobs': [],
      'GET /v1/rewrites': [],
      'GET /analyses': [],
    })
    renderApp('/')
    const resumes = await screen.findByRole('region', { name: 'Resumes' })
    expect(await within(resumes).findByText('No resumes yet. Upload one to see its analysis.')).toBeInTheDocument()
    expect(within(resumes).getByRole('link', { name: 'Upload a resume' })).toHaveAttribute('href', '/upload')
    expect(
      within(panel('Recent job matches')).getByText('Upload a resume first, then match it to a job.'),
    ).toBeInTheDocument()
    expect(within(panel('Recent rewrites')).getByText('Upload a resume first, then rewrite it.')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Quick reviews' })).not.toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /out of 100/ })).not.toBeInTheDocument()
  })

  it('shows loading per panel, and an error with retry in only the panel that failed', async () => {
    let failMatches = true
    const api = signedIn({
      'GET /v1/resumes': [],
      'GET /v1/matches': () =>
        failMatches ? apiError(500, 'internal_error', 'Could not load your matches.') : MATCHES,
      'GET /v1/jobs': () => new Promise(() => {}), // never answers: stays loading
      'GET /v1/rewrites': [],
      'GET /analyses': [],
    })
    renderApp('/')
    const matches = await screen.findByRole('region', { name: 'Recent job matches' })
    expect(await within(matches).findByRole('alert')).toHaveTextContent('Could not load your matches.')
    expect(within(panel('Saved job descriptions')).getByRole('status')).toHaveTextContent('Loading…')
    expect(within(panel('Resumes')).getByText(/No resumes yet/)).toBeInTheDocument()

    failMatches = false
    await userEvent.click(within(matches).getByRole('button', { name: 'Try again' }))
    expect(await within(matches).findByRole('link', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
    expect(api.callsTo('GET /v1/matches')).toHaveLength(2)
  })
})
