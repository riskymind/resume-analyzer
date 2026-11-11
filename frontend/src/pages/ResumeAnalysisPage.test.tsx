import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError } from '../test/fakeApi'
import { MATCHES, RESUMES, qualityReport, resumeDetail, rewriteDetail, summaryOf } from '../test/fixtures'
import { currentLocation, renderApp, signedIn } from '../test/render'

function analysisRoutes(extra = {}) {
  return signedIn({
    'GET /v1/resumes/res-1': resumeDetail(),
    'GET /v1/matches': ({ query }: { query: Record<string, string> }) => (query.resume_id === 'res-1' ? MATCHES : []),
    'GET /v1/rewrites': [summaryOf(rewriteDetail())],
    ...extra,
  })
}

describe('resume analysis page', () => {
  it('presents the scores exactly as the API returned them, with the ATS disclaimer', async () => {
    analysisRoutes()
    renderApp('/resumes/res-1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Resume analysis' })).toBeInTheDocument()
    expect(await screen.findByText('jane-doe.md', { selector: 'strong' })).toBeInTheDocument()
    expect(document.title).toBe('jane-doe.md – analysis · Resume Analyzer')

    const quality = screen.getByRole('region', { name: 'Resume quality' })
    expect(within(quality).getByRole('img', { name: 'Resume quality: 70 out of 100' })).toBeInTheDocument()
    expect(within(quality).getByText('ATS compatibility estimate', { exact: false })).toHaveTextContent('82/100')
    expect(within(quality).getByRole('note')).toHaveTextContent(/estimates how reliably automated applicant tracking/)
    expect(within(quality).getByText('Achievements')).toBeInTheDocument()
    expect(within(quality).getByText('Most bullets describe duties rather than results.')).toBeInTheDocument()
    expect(within(quality).getByText('No professional summary.')).toBeInTheDocument()
    expect(within(quality).getByText('Describe the outcome of your work.')).toBeInTheDocument()
    expect(within(quality).getByText('Tables may not be read correctly.')).toBeInTheDocument()
    expect(screen.getByText(/Sections found: Experience · Education/)).toBeInTheDocument()
  })

  it('keeps resume quality separate from job-match percentages', async () => {
    analysisRoutes()
    renderApp('/resumes/res-1')
    const related = await screen.findByRole('region', { name: 'Job matches and rewrites' })
    expect(within(related).getByText(/different number from the quality score/)).toBeInTheDocument()
    expect(await within(related).findByRole('link', { name: /Senior Backend Engineer.*64% match/ })).toHaveAttribute(
      'href',
      '/matches/match-1',
    )
    expect(within(related).getByRole('link', { name: /jane-doe – Senior Backend Engineer/ })).toHaveAttribute(
      'href',
      '/rewrites/rw-1',
    )
    expect(screen.getByRole('link', { name: 'Match against a job' })).toHaveAttribute('href', '/match?resume=res-1')
    expect(screen.getByRole('link', { name: 'Rewrite this resume' })).toHaveAttribute('href', '/rewrite?resume=res-1')
  })

  it('shows why a score was capped', async () => {
    analysisRoutes({
      'GET /v1/resumes/res-1': resumeDetail({
        quality: qualityReport({ score_cap: 'Capped at 60: no work history.' }),
      }),
    })
    renderApp('/resumes/res-1')
    expect(await screen.findByText('Capped at 60: no work history.')).toBeInTheDocument()
  })

  it('shows "not found" for a missing or inaccessible resume, with a way back', async () => {
    analysisRoutes({ 'GET /v1/resumes/res-x': apiError(404, 'not_found', 'Resume not found.') })
    renderApp('/resumes/res-x')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This resume could not be found.')
    expect(within(alert).getByRole('link', { name: 'Back to your resumes' })).toHaveAttribute('href', '/resumes')
    expect(within(alert).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })

  it('offers a retry for other errors', async () => {
    let fail = true
    analysisRoutes({
      'GET /v1/resumes/res-1': () =>
        fail ? apiError(500, 'internal_error', 'An unexpected error occurred.') : resumeDetail(),
    })
    renderApp('/resumes/res-1')
    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('img', { name: 'Resume quality: 70 out of 100' })).toBeInTheDocument()
  })

  it('deletes the resume only after confirmation, then returns to the list', async () => {
    const api = analysisRoutes({
      'DELETE /v1/resumes/res-1': () => new Response(null, { status: 204 }),
      'GET /v1/resumes': [RESUMES[1]],
    })
    renderApp('/resumes/res-1')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete “jane-doe.md”?' })
    expect(dialog).toHaveAccessibleDescription(/every rewrite made from it/)
    await userEvent.keyboard('{Escape}')
    // jsdom has no native Escape handling for <dialog>; fire the cancel event the browser would send.
    dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(api.callsTo('DELETE /v1/resumes/res-1')).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete resume' }))
    await waitFor(() => expect(currentLocation()).toBe('/resumes'), { timeout: 3000 })
    expect(api.callsTo('DELETE /v1/resumes/res-1')[0]?.headers['X-CSRF-Token']).toBe('csrf-test-token')
    expect(await screen.findByRole('link', { name: /old-cv.pdf/ }, { timeout: 3000 })).toBeInTheDocument()
  })

  it('lists resumes with their scores, or an empty state', async () => {
    signedIn({ 'GET /v1/resumes': [] })
    renderApp('/resumes')
    expect(await screen.findByText(/No resumes yet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Upload your first resume' })).toHaveAttribute('href', '/upload')
  })
})
