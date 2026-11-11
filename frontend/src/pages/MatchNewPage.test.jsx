import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError } from '../test/fakeApi'
import { JOBS, RESUMES, job, matchDetail } from '../test/fixtures'
import { currentLocation, renderApp, signedIn } from '../test/render'

// The Job match page uses the same pickers as the rewriter; this checks they still drive the match workflow.
describe('job match page', () => {
  it('runs a match for the chosen resume and job and shows the server error', async () => {
    const api = signedIn({
      'GET /v1/resumes': RESUMES,
      'GET /v1/jobs': JOBS,
      'POST /v1/jobs': job({ id: 'job-2', title: 'Platform Engineer' }),
      'POST /v1/matches': apiError(500, 'internal_error', 'Matching failed.'),
    })
    renderApp('/match')
    const run = await screen.findByRole('button', { name: '3. Run match' })
    expect(run).toBeDisabled()
    expect(screen.getByText('Choose or upload a resume to run the match.')).toBeInTheDocument()

    await userEvent.selectOptions(await screen.findByLabelText('Saved resume'), 'res-1')
    expect(screen.getByText('Analyse a job description to run the match.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Job description text'), 'Platform Engineer, Kubernetes required.')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse job description' }))
    expect(await screen.findByRole('heading', { name: 'Platform Engineer' })).toBeInTheDocument()

    await userEvent.click(run)
    await waitFor(() => expect(api.callsTo('POST /v1/matches')).toHaveLength(1))
    expect(api.callsTo('POST /v1/matches')[0].body).toEqual({ resume_id: 'res-1', job_id: 'job-2' })
    expect(await screen.findByRole('alert')).toHaveTextContent('Matching failed.')
    expect(currentLocation()).toBe('/match')
  })

  it('opens the new report at /matches/:id after a successful match', async () => {
    signedIn({
      'GET /v1/resumes': RESUMES,
      'GET /v1/jobs': JOBS,
      'GET /v1/jobs/job-1': job(),
      'POST /v1/matches': matchDetail(),
      'GET /v1/matches/match-1': matchDetail(),
    })
    // Arriving from a resume's and a job's pages preselects both.
    renderApp('/match?resume=res-1&job=job-1')
    expect(await screen.findByRole('heading', { name: 'Senior Backend Engineer' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Saved resume')).toHaveValue('res-1'))
    await userEvent.click(screen.getByRole('button', { name: '3. Run match' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Job match report' })).toBeInTheDocument()
    expect(currentLocation()).toBe('/matches/match-1')
    expect(screen.getByRole('img', { name: 'Job match: 64%' })).toBeInTheDocument()
  })

  it('reports when saved resumes and jobs cannot be loaded', async () => {
    signedIn({
      'GET /v1/resumes': apiError(500, 'internal_error', 'Could not load your documents.'),
      'GET /v1/jobs': [],
    })
    renderApp('/match')
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your documents.')
  })
})
