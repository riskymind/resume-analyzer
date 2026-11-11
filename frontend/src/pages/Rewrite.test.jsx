import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiError } from '../test/fakeApi'
import {
  JOBS,
  RESUMES,
  TEMPLATES,
  documentContent,
  job,
  rewriteDetail,
  suggestion,
  summaryOf,
  unsupportedVerification,
} from '../test/fixtures'
import { currentLocation, renderApp, signedIn } from '../test/render'

const PREVIEW_HTML = '<html><body><h1>Jane Doe</h1></body></html>'

/** Routes for a signed-in user with saved resumes/jobs; `extra` overrides or adds routes. */
function setup(extra = {}) {
  return signedIn({
    'GET /v1/resumes': RESUMES,
    'GET /v1/jobs': JOBS,
    'GET /v1/rewrites': [],
    'GET /v1/rewrites/templates': TEMPLATES,
    'GET /v1/rewrites/rw-1/preview': ({ query }) => ({
      template: query.template || 'modern',
      version: 1,
      html: PREVIEW_HTML,
    }),
    'GET /v1/resumes/res-1/document': documentContent(),
    ...extra,
  })
}

/** Opens a saved rewrite in the workspace (/rewrites/:id). */
async function openWorkspace(detail, extra = {}) {
  const api = setup({
    'GET /v1/rewrites': [summaryOf(detail)],
    'GET /v1/rewrites/rw-1': ({ query }) => (query.version ? { ...detail, version: Number(query.version) } : detail),
    ...extra,
  })
  renderApp('/rewrites/rw-1')
  await screen.findByLabelText('Rewrite name')
  return api
}

const section = (name) => screen.getByRole('region', { name })

beforeEach(() => {
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() }))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

// --------------------------------------------------------------------------- setup

describe('rewrite setup', () => {
  it('requires a resume, then sends the chosen resume, job, scope and mode', async () => {
    const api = setup({
      'GET /v1/jobs/job-1': job(),
      'POST /v1/rewrites': rewriteDetail(),
      'GET /v1/rewrites/rw-1': rewriteDetail(),
    })
    renderApp('/rewrite')
    const generate = await screen.findByRole('button', { name: '4. Rewrite my resume' })
    expect(generate).toBeDisabled()
    expect(screen.getByText('Choose or upload a resume.')).toBeInTheDocument()

    await userEvent.selectOptions(await screen.findByLabelText('Saved resume'), 'res-1')
    await userEvent.click(screen.getByRole('tab', { name: 'Saved' }))
    await userEvent.selectOptions(screen.getByLabelText('Saved job description'), 'job-1')
    await userEvent.click(screen.getByRole('button', { name: 'Use this job' }))
    // Choosing a job switches the default style to job-specific.
    await waitFor(() => expect(screen.getByLabelText('Writing style')).toHaveValue('job_targeted'))
    await userEvent.click(screen.getByRole('radio', { name: /Professional summary only/ }))
    await userEvent.click(generate)

    await screen.findByLabelText('Rewrite name')
    expect(currentLocation()).toBe('/rewrites/rw-1')
    expect(api.callsTo('POST /v1/rewrites')[0].body).toEqual({
      resume_id: 'res-1',
      job_id: 'job-1',
      scope: 'summary',
      mode: 'job_targeted',
      bullet_ids: [],
      name: null,
    })
  }, 10_000) // many sequential user-event steps; 5 s (the default) timed out once on a busy machine

  it('disables job-only scopes and styles without a job', async () => {
    setup()
    renderApp('/rewrite')
    await userEvent.selectOptions(await screen.findByLabelText('Saved resume'), 'res-1')
    expect(screen.getByRole('radio', { name: /Targeted keyword optimisation/ })).toBeDisabled()
    expect(screen.getByRole('option', { name: /Job-specific/ })).toBeDisabled()
    expect(screen.getByLabelText('Writing style')).toHaveValue('professional')
  })

  it('selected-bullets scope needs at least one bullet and sends the ids', async () => {
    const api = setup({ 'POST /v1/rewrites': rewriteDetail(), 'GET /v1/rewrites/rw-1': rewriteDetail() })
    renderApp('/rewrite')
    await userEvent.selectOptions(await screen.findByLabelText('Saved resume'), 'res-1')
    await userEvent.click(screen.getByRole('radio', { name: /Selected experience bullets/ }))
    const generate = screen.getByRole('button', { name: '4. Rewrite my resume' })
    expect(generate).toBeDisabled()
    expect(screen.getByText('Select at least one bullet.')).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('checkbox', { name: /Built FastAPI services/ }))
    await userEvent.click(generate)
    await screen.findByLabelText('Rewrite name')
    expect(api.callsTo('POST /v1/rewrites')[0].body).toMatchObject({
      scope: 'bullets',
      bullet_ids: ['exp-1-b2'],
      job_id: null,
    })
  })

  it('shows a loading state while generating and the error if it fails', async () => {
    let fail
    setup({
      'POST /v1/rewrites': () =>
        new Promise(
          (resolve) => (fail = () => resolve(apiError(502, 'ai_upstream_error', 'The AI service did not respond.'))),
        ),
    })
    renderApp('/rewrite')
    await userEvent.selectOptions(await screen.findByLabelText('Saved resume'), 'res-1')
    await userEvent.click(screen.getByRole('button', { name: '4. Rewrite my resume' }))
    expect(screen.getByRole('button', { name: /Rewriting… this can take up to a minute/ })).toBeDisabled()
    fail()
    expect(await screen.findByText('The AI service did not respond.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '4. Rewrite my resume' })).toBeEnabled()
  })
})

// --------------------------------------------------------------------------- saved rewrites

describe('saved rewrites', () => {
  it('shows loading, then the empty state', async () => {
    let respond
    setup({ 'GET /v1/rewrites': () => new Promise((resolve) => (respond = resolve)) })
    renderApp('/rewrites')
    expect(await screen.findByText('Loading saved rewrites…')).toBeInTheDocument()
    respond([])
    expect(await screen.findByText(/No rewrites yet/)).toBeInTheDocument()
  })

  it('shows an error when the list cannot be loaded', async () => {
    setup({ 'GET /v1/rewrites': apiError(500, 'internal_error', 'Something went wrong on our side.') })
    renderApp('/rewrites')
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong on our side.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('lists rewrites with scores and marks ones whose job was deleted', async () => {
    const detached = summaryOf(
      rewriteDetail({
        id: 'rw-2',
        name: 'cv – target job deleted',
        job_id: null,
        job_title: null,
        match_before: null,
        match_after: null,
        job_detached_at: '2026-11-09T12:00:00Z',
      }),
    )
    setup({ 'GET /v1/rewrites': [summaryOf(rewriteDetail()), detached] })
    renderApp('/rewrites')
    const live = await screen.findByRole('link', { name: /^jane-doe – Senior Backend Engineer/ })
    expect(live).toHaveAttribute('href', '/rewrites/rw-1')
    expect(live).toHaveTextContent('match 61→66%')
    const gone = screen.getByRole('link', { name: /^cv – target job deleted/ })
    expect(gone).toHaveTextContent('· target job deleted')
    expect(gone).not.toHaveTextContent('match')
  })

  it('deletes a rewrite only after confirming in the dialog', async () => {
    const api = setup({
      'GET /v1/rewrites': [summaryOf(rewriteDetail())],
      'DELETE /v1/rewrites/rw-1': () => new Response(null, { status: 204 }),
    })
    renderApp('/rewrites')
    await userEvent.click(await screen.findByRole('button', { name: /Delete rewrite jane-doe/ }))
    let dialog = screen.getByRole('dialog', { name: /Delete “jane-doe – Senior Backend Engineer”\?/ })
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.callsTo('DELETE /v1/rewrites/rw-1')).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: /Delete rewrite jane-doe/ }))
    dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete rewrite' }))
    await waitFor(() => expect(api.callsTo('DELETE /v1/rewrites/rw-1')).toHaveLength(1))
    await waitFor(() => expect(api.callsTo('GET /v1/rewrites')).toHaveLength(2))
  })
})

// --------------------------------------------------------------------------- suggestions

describe('suggestions', () => {
  it('accepts and rejects suggestions against the version on screen', async () => {
    const review = suggestion({
      id: 'g1-s2',
      verification: {
        status: 'warning',
        issues: [
          { code: 'new_name', severity: 'warning', message: 'Check “Contoso”.', origin: 'ai', action: 'flagged' },
        ],
      },
      proposed: 'Backend engineer for Contoso clients.',
    })
    const detail = rewriteDetail({ current_version: 2, suggestions: [suggestion(), review] })
    const api = await openWorkspace(detail, {
      'PATCH /v1/rewrites/rw-1': ({ body }) =>
        rewriteDetail({
          current_version: 3,
          suggestions: [suggestion(), { ...review, decision: body.decisions['g1-s2'] }],
        }),
    })
    const summary = section('Professional summary')
    expect(within(summary).getByText('Applied · verified')).toBeInTheDocument()
    expect(within(summary).getByText('Needs your review')).toBeInTheDocument()
    expect(within(summary).getByText('Check “Contoso”.')).toBeInTheDocument()

    await userEvent.click(within(summary).getAllByRole('button', { name: 'Accept' })[0])
    await waitFor(() => expect(api.callsTo('PATCH /v1/rewrites/rw-1')).toHaveLength(1))
    expect(api.callsTo('PATCH /v1/rewrites/rw-1')[0].body).toEqual({
      base_version: 2,
      decisions: { 'g1-s2': 'accepted' },
    })
    expect(await within(section('Professional summary')).findByText('Accepted')).toBeInTheDocument()
    expect(screen.getByText(/Job-specific · version 3/)).toBeInTheDocument()

    await userEvent.click(within(section('Professional summary')).getAllByRole('button', { name: 'Reject' })[1])
    await waitFor(() =>
      expect(api.callsTo('PATCH /v1/rewrites/rw-1')[1].body).toEqual({
        base_version: 3,
        decisions: { 'g1-s2': 'rejected' },
      }),
    )
  })

  it('blocked suggestions cannot be accepted and explain why', async () => {
    const blocked = suggestion({
      verification: {
        status: 'rejected',
        issues: [
          {
            code: 'unsupported_skill',
            severity: 'blocking',
            message: '“Terraform” is not mentioned anywhere in your original resume.',
            origin: 'ai',
            action: 'flagged',
          },
        ],
      },
      decision: 'rejected',
      auto_rejected: true,
    })
    await openWorkspace(rewriteDetail({ suggestions: [blocked] }))
    const summary = section('Professional summary')
    expect(within(summary).getByText('Rejected: unsupported claim')).toBeInTheDocument()
    expect(within(summary).queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
    expect(within(summary).getByText(/can't be applied/)).toBeInTheDocument()
    expect(within(summary).getByText(/Terraform/)).toBeInTheDocument()
  })

  it('regenerates one section', async () => {
    const api = await openWorkspace(rewriteDetail(), {
      'POST /v1/rewrites/rw-1/regenerate': rewriteDetail({ current_version: 2 }),
    })
    await userEvent.click(screen.getByRole('button', { name: 'Regenerate summary' }))
    expect(await screen.findByText('New suggestions generated. Review them below.')).toBeInTheDocument()
    expect(api.callsTo('POST /v1/rewrites/rw-1/regenerate')[0].body).toEqual({
      base_version: 1,
      scope: 'summary',
      bullet_ids: [],
      mode: null,
    })
  })
})

// --------------------------------------------------------------------------- editing and verification

describe('editing', () => {
  it('saves an edited summary as a new version and shows unverified claims as unverified', async () => {
    const edited = 'Backend engineer certified in Terraform.'
    const api = await openWorkspace(rewriteDetail(), {
      'PATCH /v1/rewrites/rw-1': ({ body }) =>
        rewriteDetail({
          current_version: 2,
          content: body.content,
          verification: unsupportedVerification(),
          verification_status: 'unsupported',
        }),
    })
    const summary = section('Professional summary')
    await userEvent.click(within(summary).getByRole('button', { name: 'Edit' }))
    const field = within(summary).getByLabelText('Summary')
    await userEvent.clear(field)
    await userEvent.type(field, edited)
    await userEvent.click(within(summary).getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText('Saved as a new version.')).toBeInTheDocument()
    expect(api.callsTo('PATCH /v1/rewrites/rw-1')[0].body).toMatchObject({
      base_version: 1,
      content: { summary: edited },
    })
    expect(within(section('Professional summary')).getByText(edited)).toBeInTheDocument()
    const verification = screen
      .getByRole('heading', { name: /claims your original resume does not support/ })
      .closest('section')
    expect(within(verification).getByText(/Unsupported · your edit/)).toBeInTheDocument()
    expect(within(verification).queryByText(/Every change is supported/)).not.toBeInTheDocument()
  })

  it('adds skills and coursework as typed lists (commas are kept while typing)', async () => {
    const api = await openWorkspace(rewriteDetail(), {
      'PATCH /v1/rewrites/rw-1': ({ body }) => rewriteDetail({ current_version: 2, content: body.content }),
    })
    const skills = section('Skills')
    await userEvent.click(within(skills).getByRole('button', { name: 'Edit' }))
    const technical = within(skills).getByLabelText('Technical skills (comma-separated)')
    await userEvent.type(technical, ', Docker')
    expect(technical).toHaveValue('Python, FastAPI, PostgreSQL, Docker')
    await userEvent.click(within(skills).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.callsTo('PATCH /v1/rewrites/rw-1')).toHaveLength(1))
    expect(api.callsTo('PATCH /v1/rewrites/rw-1')[0].body.content.technical_skills).toEqual([
      'Python',
      'FastAPI',
      'PostgreSQL',
      'Docker',
    ])

    const education = section('Education and certifications')
    await userEvent.click(within(education).getByRole('button', { name: 'Edit' }))
    await userEvent.type(
      within(education).getByLabelText('Relevant coursework (comma-separated)'),
      'Databases, Algorithms',
    )
    await userEvent.click(within(education).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(api.callsTo('PATCH /v1/rewrites/rw-1')).toHaveLength(2))
    expect(api.callsTo('PATCH /v1/rewrites/rw-1')[1].body.content.education[0].coursework).toEqual([
      'Databases',
      'Algorithms',
    ])
  })

  it('cancelling an edit sends nothing', async () => {
    const api = await openWorkspace(rewriteDetail())
    const summary = section('Professional summary')
    await userEvent.click(within(summary).getByRole('button', { name: 'Edit' }))
    await userEvent.type(within(summary).getByLabelText('Summary'), ' extra')
    await userEvent.click(within(summary).getByRole('button', { name: 'Cancel' }))
    expect(api.callsTo('PATCH /v1/rewrites/rw-1')).toHaveLength(0)
    expect(within(summary).getByText(documentContent().summary)).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- versions

describe('versions', () => {
  it('views an earlier version read-only and restores it as a new version', async () => {
    const older = documentContent({ summary: 'The summary as it was in version 1.' })
    const detail = rewriteDetail({ current_version: 2 })
    const api = await openWorkspace(detail, {
      'GET /v1/rewrites/rw-1': ({ query }) =>
        query.version === '1' ? { ...detail, version: 1, content: older } : detail,
      'PATCH /v1/rewrites/rw-1': rewriteDetail({ current_version: 3, content: older }),
    })
    await userEvent.click(screen.getByRole('button', { name: /v1 · AI rewrite/ }))
    expect(await screen.findByText(/Viewing version 1 \(read-only\)/)).toBeInTheDocument()
    expect(screen.getByText('The summary as it was in version 1.')).toBeInTheDocument()
    expect(within(section('Professional summary')).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Restore this version' }))
    expect(await screen.findByText('Version 1 restored as a new version.')).toBeInTheDocument()
    expect(api.callsTo('PATCH /v1/rewrites/rw-1')[0].body).toEqual({ base_version: 2, restore_version: 1 })
    expect(screen.queryByText(/read-only/)).not.toBeInTheDocument()
  })

  it('a stale version (changed in another tab) shows the conflict and loads the latest', async () => {
    let latest = rewriteDetail()
    const api = await openWorkspace(rewriteDetail(), {
      'GET /v1/rewrites/rw-1': () => latest,
      'PATCH /v1/rewrites/rw-1': () => {
        latest = rewriteDetail({ current_version: 4, content: documentContent({ summary: 'Saved in another tab.' }) })
        return apiError(409, 'conflict', 'This rewrite has changed since you loaded it (now version 4).')
      },
    })
    await userEvent.click(screen.getAllByRole('button', { name: 'Keep' })[0])
    expect(await screen.findByRole('alert')).toHaveTextContent('now version 4')
    expect(await screen.findByText('Saved in another tab.')).toBeInTheDocument()
    expect(screen.getByText(/Job-specific · version 4/)).toBeInTheDocument()
    expect(api.callsTo('GET /v1/rewrites/rw-1').length).toBeGreaterThanOrEqual(2)
  })

  it('reloads the rewrite when returning to the workspace, so a deleted job is not shown as current', async () => {
    let detail = rewriteDetail()
    await openWorkspace(detail, {
      'GET /v1/rewrites/rw-1': () => detail,
      'GET /v1/rewrites': () => [summaryOf(detail)],
    })
    expect(screen.getByRole('heading', { name: 'Job match' })).toBeInTheDocument()
    // The job is deleted elsewhere: the server now returns the detached rewrite.
    detail = rewriteDetail({
      job_id: null,
      job_title: null,
      job_detached_at: '2026-11-09T12:00:00Z',
      scores: { ...rewriteDetail().scores, match: null },
    })
    await userEvent.click(screen.getByRole('link', { name: 'All rewrites' }))
    await userEvent.click(await screen.findByRole('link', { name: /^jane-doe – Senior Backend Engineer/ }))
    expect(await screen.findByText(/The job this rewrite targeted was deleted/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Job match' })).not.toBeInTheDocument()
    expect(screen.getByText(/target job deleted/)).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- templates, preview and export

describe('templates and export', () => {
  it('lists all five templates, previews the chosen one and saves it', async () => {
    const api = await openWorkspace(rewriteDetail(), {
      'PATCH /v1/rewrites/rw-1': rewriteDetail({ template: 'graduate' }),
    })
    const choice = screen.getByRole('group', { name: 'Template' })
    const names = within(choice)
      .getAllByRole('radio')
      .map((radio) => radio.closest('label').querySelector('strong').textContent)
    expect(names).toEqual(['Modern professional', 'Minimalist', 'Traditional corporate', 'Technical', 'Graduate'])
    expect(within(choice).getByRole('radio', { name: /Modern professional/ })).toBeChecked()
    expect(await screen.findByTitle('Resume preview')).toHaveAttribute('sandbox', '')

    await userEvent.click(within(choice).getByRole('radio', { name: /Graduate/ }))
    await waitFor(() =>
      expect(api.callsTo('GET /v1/rewrites/rw-1/preview').some((c) => c.query.template === 'graduate')).toBe(true),
    )
    await waitFor(() =>
      expect(api.callsTo('PATCH /v1/rewrites/rw-1')[0]?.body).toEqual({ base_version: 1, template: 'graduate' }),
    )
  })

  it('shows a preview error', async () => {
    await openWorkspace(rewriteDetail(), {
      'GET /v1/rewrites/rw-1/preview': apiError(500, 'internal_error', 'Preview failed.'),
    })
    expect(await screen.findByText('Preview failed.')).toBeInTheDocument()
  })

  it('downloads verified content without confirmation', async () => {
    const api = await openWorkspace(rewriteDetail(), {
      'POST /v1/rewrites/rw-1/export': () =>
        new Response(new Blob(['%PDF-1.7']), {
          headers: {
            'Content-Type': 'application/pdf',
            'Content-Disposition': 'attachment; filename="jane-doe-resume.pdf"',
          },
        }),
    })
    expect(screen.queryByRole('checkbox', { name: /confirm they are accurate/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    await waitFor(() => expect(api.callsTo('POST /v1/rewrites/rw-1/export')).toHaveLength(1))
    expect(api.callsTo('POST /v1/rewrites/rw-1/export')[0].body).toEqual({
      format: 'pdf',
      template: 'modern',
      version: 1,
      acknowledge_unverified: false,
    })
    // The session's CSRF token (from /auth/me) accompanies the export request.
    expect(api.callsTo('POST /v1/rewrites/rw-1/export')[0].headers['X-CSRF-Token']).toBe('csrf-test-token')
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
    expect(await screen.findByText('Downloaded jane-doe-resume.pdf.')).toBeInTheDocument()
  })

  it('requires explicit confirmation of unverified claims before download', async () => {
    const detail = rewriteDetail({
      current_version: 2,
      verification: unsupportedVerification(),
      verification_status: 'unsupported',
    })
    const api = await openWorkspace(detail, {
      'POST /v1/rewrites/rw-1/export': () =>
        new Response(new Blob(['PK']), {
          headers: { 'Content-Disposition': 'attachment; filename="jane-doe-resume.docx"' },
        }),
    })
    const warning = screen.getByText(/1 claim in this version could not be verified/).closest('[role="alert"]')
    expect(within(warning).getByText(/Terraform/)).toBeInTheDocument()
    expect(within(warning).getByText(/Unverified · your edit/)).toBeInTheDocument()
    expect(within(warning).getByText(/nothing is removed/)).toBeInTheDocument()
    const pdf = screen.getByRole('button', { name: 'Download PDF' })
    const docx = screen.getByRole('button', { name: 'Download DOCX' })
    expect(pdf).toBeDisabled()
    expect(docx).toBeDisabled()

    await userEvent.click(within(warning).getByRole('checkbox', { name: /confirm they are accurate/ }))
    expect(docx).toBeEnabled()
    await userEvent.click(docx)
    await waitFor(() => expect(api.callsTo('POST /v1/rewrites/rw-1/export')).toHaveLength(1))
    expect(api.callsTo('POST /v1/rewrites/rw-1/export')[0].body).toEqual({
      format: 'docx',
      template: 'modern',
      version: 2,
      acknowledge_unverified: true,
    })
  })

  it('a confirmation does not carry over to another version', async () => {
    const detail = rewriteDetail({
      current_version: 2,
      verification: unsupportedVerification(),
      verification_status: 'unsupported',
    })
    await openWorkspace(detail, {
      'GET /v1/rewrites/rw-1': ({ query }) => (query.version ? { ...detail, version: Number(query.version) } : detail),
    })
    await userEvent.click(screen.getByRole('checkbox', { name: /confirm they are accurate/ }))
    expect(screen.getByRole('button', { name: 'Download PDF' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: /v1 · AI rewrite/ }))
    await screen.findByText(/Viewing version 1/)
    expect(screen.getByRole('checkbox', { name: /confirm they are accurate/ })).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Download PDF' })).toBeDisabled()
  })

  it('shows export errors from the server', async () => {
    await openWorkspace(rewriteDetail(), {
      'POST /v1/rewrites/rw-1/export': apiError(
        503,
        'export_unavailable',
        'PDF export is not available on this server. DOCX export still works.',
      ),
    })
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(await screen.findByText(/DOCX export still works/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Download PDF' })).toBeEnabled()
  })
})
