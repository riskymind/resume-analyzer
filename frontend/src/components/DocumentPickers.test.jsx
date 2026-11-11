import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { apiError, installApi } from '../test/fakeApi'
import { JOBS, RESUMES, job } from '../test/fixtures'
import { JobStep, ResumeStep } from './DocumentPickers'

describe('ResumeStep', () => {
  it('selects a saved resume', async () => {
    const onSelect = vi.fn()
    render(<ResumeStep resumes={RESUMES} selectedId={null} onSelect={onSelect} onUploaded={vi.fn()} />)
    await userEvent.selectOptions(screen.getByLabelText('Saved resume'), 'res-2')
    expect(onSelect).toHaveBeenCalledWith('res-2')
  })

  it('offers only upload when there are no saved resumes', () => {
    render(<ResumeStep resumes={[]} selectedId={null} onSelect={vi.fn()} onUploaded={vi.fn()} />)
    expect(screen.queryByLabelText('Saved resume')).not.toBeInTheDocument()
    expect(screen.getByText(/Upload a resume/)).toBeInTheDocument()
  })

  it('rejects unsupported files before uploading', async () => {
    const api = installApi()
    render(<ResumeStep resumes={[]} selectedId={null} onSelect={vi.fn()} onUploaded={vi.fn()} />)
    const input = document.querySelector('input[type="file"]')
    await userEvent.upload(input, new File(['x'], 'cv.txt', { type: 'text/plain' }), { applyAccept: false })
    await userEvent.click(screen.getByRole('button', { name: 'Upload and analyse' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Resume must be a .pdf, .docx or .md file.')
    expect(api.calls).toHaveLength(0)
  })

  it('uploads a resume, shows progress and reports the new resume', async () => {
    let release
    const api = installApi({
      'POST /v1/resumes': () =>
        new Promise((resolve) => (release = () => resolve({ id: 'res-9', filename: 'new.md' }))),
    })
    const onUploaded = vi.fn()
    render(<ResumeStep resumes={RESUMES} selectedId={null} onSelect={vi.fn()} onUploaded={onUploaded} />)
    await userEvent.upload(
      document.querySelector('input[type="file"]'),
      new File(['# CV'], 'new.md', { type: 'text/markdown' }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Upload and analyse' }))
    expect(await screen.findByRole('button', { name: 'Analysing resume…' })).toBeDisabled()
    release()
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 'res-9', filename: 'new.md' }))
    expect(api.callsTo('POST /v1/resumes')[0].body).toBeInstanceOf(FormData)
  })

  it('shows the server error when an upload fails', async () => {
    installApi({ 'POST /v1/resumes': apiError(400, 'encrypted_document', 'This PDF is password-protected.') })
    render(<ResumeStep resumes={[]} selectedId={null} onSelect={vi.fn()} onUploaded={vi.fn()} />)
    await userEvent.upload(
      document.querySelector('input[type="file"]'),
      new File(['%PDF'], 'cv.pdf', { type: 'application/pdf' }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Upload and analyse' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This PDF is password-protected.')
  })
})

describe('JobStep', () => {
  it('defaults to "No job" when a job is optional (Rewrite)', async () => {
    const onJob = vi.fn()
    render(<JobStep jobs={JOBS} onJob={onJob} allowNone />)
    expect(screen.getByRole('tab', { name: 'No job' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText(/General improvement/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Paste text' }))
    await userEvent.click(screen.getByRole('tab', { name: 'No job' }))
    expect(onJob).toHaveBeenLastCalledWith(null)
  })

  it('requires a job by default (Job match) and validates empty text', async () => {
    const api = installApi()
    render(<JobStep jobs={[]} onJob={vi.fn()} />)
    expect(screen.queryByRole('tab', { name: 'No job' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Analyse job description' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Paste the job description first.')
    expect(api.calls).toHaveLength(0)
  })

  it('submits pasted text and returns the extracted job', async () => {
    const extracted = job()
    const api = installApi({ 'POST /v1/jobs': extracted })
    const onJob = vi.fn()
    render(<JobStep jobs={[]} onJob={onJob} />)
    await userEvent.type(screen.getByLabelText('Job description text'), 'Senior Backend Engineer at Globex')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse job description' }))
    await waitFor(() => expect(onJob).toHaveBeenCalledWith(extracted))
    expect(api.callsTo('POST /v1/jobs')[0].body.get('text')).toBe('Senior Backend Engineer at Globex')
  })

  it('reuses a saved job description', async () => {
    const api = installApi({ 'GET /v1/jobs/job-1': job() })
    const onJob = vi.fn()
    render(<JobStep jobs={JOBS} onJob={onJob} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Saved' }))
    await userEvent.click(screen.getByRole('button', { name: 'Use this job' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a saved job description.')
    await userEvent.selectOptions(screen.getByLabelText('Saved job description'), 'job-1')
    await userEvent.click(screen.getByRole('button', { name: 'Use this job' }))
    await waitFor(() => expect(onJob).toHaveBeenCalledWith(expect.objectContaining({ id: 'job-1' })))
    expect(api.callsTo('GET /v1/jobs/job-1')).toHaveLength(1)
  })

  it('shows extraction errors', async () => {
    installApi({ 'POST /v1/jobs': apiError(502, 'ai_upstream_error', 'The AI service failed. Try again.') })
    render(<JobStep jobs={[]} onJob={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('Job description text'), 'Some job')
    await userEvent.click(screen.getByRole('button', { name: 'Analyse job description' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The AI service failed. Try again.')
  })
})
