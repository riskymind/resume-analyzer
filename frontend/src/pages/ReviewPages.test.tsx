import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError } from '../test/fakeApi'
import { ANALYSES, analysisRecord, qualityReport, resumeDetail } from '../test/fixtures'
import { currentLocation, renderApp, signedIn } from '../test/render'

// Quick review is the original one-step flow (resume + job description → POST /api/analyze). It is kept.
describe('quick reviews', () => {
  it('submits a resume with pasted job text and opens the saved review', async () => {
    const api = signedIn({
      'POST /analyze': analysisRecord(),
      'GET /analyses/7': analysisRecord(),
    })
    renderApp('/reviews/new')
    const resumeInput = (await screen.findByText('Choose file…')).closest('div')?.querySelector('input')
    await userEvent.upload(
      resumeInput as HTMLInputElement,
      new File(['# CV'], 'quick-cv.md', { type: 'text/markdown' }),
    )
    await userEvent.type(screen.getByLabelText('Job description text'), 'Backend engineer, Python.')
    await userEvent.click(screen.getByRole('button', { name: 'Review resume' }))

    expect(await screen.findByRole('img', { name: 'Job fit: 58 out of 100' })).toBeInTheDocument()
    expect(currentLocation()).toBe('/reviews/7')
    const body = api.callsTo('POST /analyze')[0]?.body as FormData
    expect(body.get('jd_text')).toBe('Backend engineer, Python.')
    expect(screen.getByText('Terraform')).toBeInTheDocument()
  })

  it('validates the job description before submitting', async () => {
    const api = signedIn()
    renderApp('/reviews/new')
    const resumeInput = (await screen.findByText('Choose file…')).closest('div')?.querySelector('input')
    await userEvent.upload(resumeInput as HTMLInputElement, new File(['# CV'], 'cv.md', { type: 'text/markdown' }))
    await userEvent.click(screen.getByRole('button', { name: 'Review resume' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Paste a job description, or switch to file upload.')
    expect(api.callsTo('POST /analyze')).toHaveLength(0)
  })

  it('lists past reviews and shows a missing one as not found', async () => {
    signedIn({
      'GET /analyses': ANALYSES,
      'GET /analyses/99': apiError(404, 'not_found', 'Analysis not found.'),
      'GET /analyses/7': analysisRecord({ resume_id: 'res-1', resume_quality: qualityReport() }),
    })
    renderApp('/reviews')
    await userEvent.click(await screen.findByRole('link', { name: /quick-cv.pdf/ }))
    expect(await screen.findByRole('region', { name: 'Resume quality' })).toBeInTheDocument()
    await waitFor(() => expect(currentLocation()).toBe('/reviews/7'))
  })

  it('shows a not-found message for a review that does not exist', async () => {
    signedIn({ 'GET /analyses/99': apiError(404, 'not_found', 'Analysis not found.') })
    renderApp('/reviews/99')
    expect(await screen.findByRole('alert')).toHaveTextContent('This review could not be found.')
  })
})

describe('resume without a quality analysis', () => {
  it('says so instead of showing a score', async () => {
    signedIn({
      'GET /v1/resumes/res-1': resumeDetail({ quality: null }),
      'GET /v1/matches': [],
      'GET /v1/rewrites': [],
    })
    renderApp('/resumes/res-1')
    expect(await screen.findByText('This resume has no quality analysis yet.')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /Resume quality/ })).not.toBeInTheDocument()
  })
})
