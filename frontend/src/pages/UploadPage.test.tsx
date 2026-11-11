import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError } from '../test/fakeApi'
import { RESUMES, resumeDetail } from '../test/fixtures'
import { currentLocation, renderApp, signedIn } from '../test/render'

const resumeFile = (name = 'new-cv.md', size?: number) => {
  const file = new File(['# Jane Doe\n\n## Experience'], name, { type: 'text/markdown' })
  if (size) Object.defineProperty(file, 'size', { value: size })
  return file
}

/** The dropzone's file input (its label changes to the chosen file's name). */
async function fileInput(): Promise<HTMLInputElement> {
  const zone = await screen.findByTestId('dropzone')
  return zone.querySelector('input[type="file"]') as HTMLInputElement
}

async function chooseFile(file: File) {
  await userEvent.upload(await fileInput(), file, { applyAccept: false })
}

describe('upload page', () => {
  it('explains the supported formats and keeps the file input keyboard-accessible', async () => {
    signedIn({ 'GET /v1/resumes': [] })
    renderApp('/upload')
    const input = await screen.findByLabelText(/Drag and drop your resume here/)
    expect(input).toHaveAttribute('type', 'file')
    expect(input).toHaveAccessibleDescription(
      /Supported formats: PDF, Word \(.docx\) and Markdown \(.md\), up to 5.0 MB/,
    )
    input.focus()
    expect(input).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Upload and analyse' })).toBeDisabled()
  })

  it('rejects unsupported and oversized files before uploading', async () => {
    const api = signedIn({ 'GET /v1/resumes': [] })
    renderApp('/upload')
    await chooseFile(new File(['x'], 'cv.txt', { type: 'text/plain' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Resume must be a .pdf, .docx or .md file.')
    expect(await fileInput()).toHaveAttribute('aria-invalid', 'true')
    expect(await fileInput()).toHaveAccessibleName('cv.txt Choose a different file')
    expect(screen.getByRole('button', { name: 'Upload and analyse' })).toBeDisabled()

    await chooseFile(resumeFile('big.pdf', 6 * 1024 * 1024))
    expect(screen.getByRole('alert')).toHaveTextContent('Resume must be smaller than 5MB.')
    expect(api.callsTo('POST /v1/resumes')).toHaveLength(0)
  })

  it('accepts a dropped file, shows progress, then processing, then opens the analysis', async () => {
    let finish: (value: unknown) => void = () => {}
    const api = signedIn({
      'GET /v1/resumes': [],
      'POST /v1/resumes': () => new Promise((resolve) => (finish = resolve)),
      'GET /v1/resumes/res-9': resumeDetail({ id: 'res-9', filename: 'new-cv.md' }),
      'GET /v1/matches': [],
      'GET /v1/rewrites': [],
    })
    renderApp('/upload')
    const dropzone = await screen.findByTestId('dropzone')
    fireEvent.drop(dropzone, { dataTransfer: { files: [resumeFile()] } })
    expect(screen.getByText('new-cv.md', { selector: 'strong' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Upload and analyse' }))
    // The fake network reports about half the bytes sent before the server answers.
    const progress = (await screen.findByRole('progressbar', { name: 'Upload progress' })) as HTMLProgressElement
    await waitFor(() => expect(progress.value).toBeGreaterThan(0))
    expect(progress.value).toBeLessThan(100)
    expect(screen.getByText('Uploading your resume…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Uploading…' })).toBeDisabled()

    finish(resumeDetail({ id: 'res-9', filename: 'new-cv.md' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Resume analysis' })).toBeInTheDocument()
    expect(currentLocation()).toBe('/resumes/res-9')
    expect(screen.getByText('Resume uploaded and analysed.')).toBeInTheDocument()
    const upload = api.callsTo('POST /v1/resumes')[0]
    expect(upload?.body).toBeInstanceOf(FormData)
    expect((upload?.body as FormData).get('file')).toBeInstanceOf(File)
    expect(upload?.headers['X-CSRF-Token']).toBe('csrf-test-token')
  })

  it('rejects dropping several files at once', async () => {
    signedIn({ 'GET /v1/resumes': [] })
    renderApp('/upload')
    fireEvent.drop(await screen.findByTestId('dropzone'), {
      dataTransfer: { files: [resumeFile('a.md'), resumeFile('b.md')] },
    })
    expect(screen.getByRole('alert')).toHaveTextContent('Drop one file at a time.')
  })

  it("shows the server's validation message unchanged and lets the user try again", async () => {
    signedIn({
      'GET /v1/resumes': [],
      'POST /v1/resumes': apiError(
        400,
        'invalid_file',
        'PDF is password-protected. Remove the password and upload it again.',
      ),
    })
    renderApp('/upload')
    await chooseFile(resumeFile('locked.pdf'))
    await userEvent.click(screen.getByRole('button', { name: 'Upload and analyse' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'PDF is password-protected. Remove the password and upload it again.',
    )
    expect(currentLocation()).toBe('/upload')
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('points out a resume with the same file name that was uploaded before', async () => {
    signedIn({ 'GET /v1/resumes': RESUMES })
    renderApp('/upload')
    await screen.findByLabelText(/Drag and drop/)
    await waitFor(() => expect(screen.getByLabelText(/Drag and drop/)).toBeEnabled())
    await chooseFile(resumeFile('jane-doe.md'))
    const note = await screen.findByRole('note')
    expect(note).toHaveTextContent('You already uploaded a file named “jane-doe.md”')
    expect(screen.getByRole('link', { name: 'Open that analysis' })).toHaveAttribute('href', '/resumes/res-1')
  })

  it('can cancel an upload while the file is being sent', async () => {
    signedIn({ 'GET /v1/resumes': [], 'POST /v1/resumes': () => new Promise(() => {}) })
    renderApp('/upload')
    await chooseFile(resumeFile())
    await userEvent.click(screen.getByRole('button', { name: 'Upload and analyse' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel upload' }))
    expect(await screen.findByText('Upload cancelled. Nothing was saved.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload and analyse' })).toBeEnabled()
  })
})
