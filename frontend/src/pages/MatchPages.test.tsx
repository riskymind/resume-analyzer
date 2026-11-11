import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError } from '../test/fakeApi'
import { JOBS, MATCHES, job, matchDetail, matchReport } from '../test/fixtures'
import { currentLocation, renderApp, signedIn } from '../test/render'

describe('match report page', () => {
  it('shows the deterministic report with links to the resume, the job and a targeted rewrite', async () => {
    signedIn({ 'GET /v1/matches/match-1': matchDetail() })
    renderApp('/matches/match-1')
    expect(await screen.findByRole('img', { name: 'Job match: 64%' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Good Match' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'jane-doe.md' })).toHaveAttribute('href', '/resumes/res-1')
    expect(screen.getByRole('link', { name: 'Senior Backend Engineer' })).toHaveAttribute('href', '/jobs/job-1')
    expect(screen.getByRole('link', { name: 'Rewrite for this job' })).toHaveAttribute(
      'href',
      '/rewrite?resume=res-1&job=job-1',
    )
    expect(screen.getByText('Python is listed in your skills.')).toBeInTheDocument()
    expect(screen.getByText(/Confidence:/)).toHaveTextContent('high')
    expect(screen.queryByText(/Semantic matching was/)).not.toBeInTheDocument()
  })

  it('discloses when semantic similarity was unavailable', async () => {
    signedIn({
      'GET /v1/matches/match-1': matchDetail({
        semantic_status: 'unavailable',
        report: matchReport({
          semantic: {
            status: 'unavailable',
            model: null,
            reason: 'The embedding service timed out.',
            related_threshold: 0.8,
            text_threshold: 0.7,
          },
          confidence: { level: 'medium', evidence_coverage: 100, reasons: ['Semantic matching was unavailable.'] },
        }),
      }),
    })
    renderApp('/matches/match-1')
    const note = await screen.findByText(/Semantic matching was unavailable\./, { selector: 'strong' })
    expect(note.closest('p')).toHaveTextContent('The embedding service timed out.')
    expect(note.closest('p')).toHaveTextContent('exact, alias and skill-family rules only')
  })

  it('handles a missing match report', async () => {
    signedIn({ 'GET /v1/matches/nope': apiError(404, 'not_found', 'Match not found.') })
    renderApp('/matches/nope')
    expect(await screen.findByRole('alert')).toHaveTextContent('This match report could not be found.')
    expect(screen.getByRole('link', { name: 'Back to saved matches' })).toHaveAttribute('href', '/matches')
  })
})

describe('saved matches and jobs', () => {
  it('lists reports and jobs as links and deletes a job after explaining the consequences', async () => {
    const api = signedIn({
      'GET /v1/matches': MATCHES,
      'GET /v1/jobs': JOBS,
      'DELETE /v1/jobs/job-1': () => new Response(null, { status: 204 }),
    })
    renderApp('/matches')
    const reports = await screen.findByRole('region', { name: 'Match reports' })
    expect(await within(reports).findByRole('link', { name: /Senior Backend Engineer · jane-doe.md/ })).toHaveAttribute(
      'href',
      '/matches/match-1',
    )
    const jobs = screen.getByRole('region', { name: 'Job descriptions' })
    expect(within(jobs).getByRole('link', { name: /Senior Backend Engineer · Globex/ })).toHaveAttribute(
      'href',
      '/jobs/job-1',
    )

    await userEvent.click(within(jobs).getByRole('button', { name: 'Delete job description: Senior Backend Engineer' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete “Senior Backend Engineer”?' })
    expect(dialog).toHaveTextContent('Rewrites that targeted it are kept')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete job description' }))
    await waitFor(() => expect(api.callsTo('DELETE /v1/jobs/job-1')).toHaveLength(1))
  })
})

describe('job description page', () => {
  it('shows verified requirements and offers matching and rewriting for this job', async () => {
    signedIn({ 'GET /v1/jobs/job-1': job(), 'GET /v1/matches': MATCHES })
    renderApp('/jobs/job-1')
    expect(await screen.findByRole('heading', { level: 2, name: 'Senior Backend Engineer' })).toBeInTheDocument()
    expect(screen.getByText('Python required', { selector: 'q' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Match a resume' })).toHaveAttribute('href', '/match?job=job-1')
    expect(screen.getByRole('link', { name: 'Rewrite for this job' })).toHaveAttribute('href', '/rewrite?job=job-1')
    expect(await screen.findByRole('link', { name: /jane-doe.md.*64%/ })).toHaveAttribute('href', '/matches/match-1')
  })

  it('deletes the job and returns to the saved list', async () => {
    signedIn({
      'GET /v1/jobs/job-1': job(),
      'GET /v1/matches': [],
      'GET /v1/jobs': [],
      'DELETE /v1/jobs/job-1': () => new Response(null, { status: 204 }),
    })
    renderApp('/jobs/job-1')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete job description' }))
    await waitFor(() => expect(currentLocation()).toBe('/matches'))
  })
})
