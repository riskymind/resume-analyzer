import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { fetchResumes, uploadResume } from '../api/resume'
import FileDropzone from '../components/FileDropzone'
import { Flag } from '../components/ui/Feedback'
import PageHeader from '../components/ui/PageHeader'
import { useResource } from '../hooks/useResource'
import { formatBytes, MAX_FILE_SIZE_BYTES, validateFile } from '../utils/files'
import { formatDate } from '../utils/format'

type Phase = 'idle' | 'uploading' | 'processing'

/** State passed to the analysis page after a successful upload. */
export interface UploadedState {
  uploaded?: boolean
}

/**
 * Upload a resume. The browser checks the extension and size first (for quick feedback); the server checks the
 * type, file signature and size again and its error messages are shown unchanged. After the upload the server
 * extracts, verifies and scores the resume, then the user lands on its analysis.
 */
export default function UploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  const inputId = useId()
  const guidanceId = useId()
  const errorId = useId()
  const resumes = useResource('resumes', fetchResumes)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  function choose(next: File) {
    setFile(next)
    setNotice(null)
    setError(validateFile(next, 'Resume'))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setNotice(null)
    const problem = validateFile(file, 'Resume')
    if (problem || !file) return setError(problem)
    setError(null)
    setPhase('uploading')
    setProgress(0)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const resume = await uploadResume(file, {
        signal: controller.signal,
        onProgress: ({ loaded, total }) => {
          if (!mounted.current || !total) return
          setProgress(Math.round((loaded / total) * 100))
          if (loaded >= total) setPhase('processing')
        },
      })
      // The user may have left the page while the server was working; don't pull them back.
      if (mounted.current) navigate(`/resumes/${resume.id}`, { state: { uploaded: true } satisfies UploadedState })
    } catch (err) {
      if (!mounted.current) return
      setPhase('idle')
      setProgress(null)
      if (err instanceof DOMException && err.name === 'AbortError') setNotice('Upload cancelled. Nothing was saved.')
      else setError((err as Error).message)
    } finally {
      abortRef.current = null
    }
  }

  const busy = phase !== 'idle'
  const duplicate = file ? resumes.state.data?.find((resume) => resume.filename === file.name) : undefined

  return (
    <div className="upload-page">
      <PageHeader
        title="Upload a resume"
        meta={<p className="report-meta">We'll read it, check what we extract against your text, and score it.</p>}
      />

      <form onSubmit={submit} noValidate aria-describedby={guidanceId}>
        <FileDropzone
          id={inputId}
          file={file}
          onFile={choose}
          onMultiple={() => setError('Drop one file at a time.')}
          disabled={busy}
          invalid={Boolean(error)}
          describedBy={[guidanceId, error ? errorId : null].filter(Boolean).join(' ')}
        />

        <div id={guidanceId} className="upload-guidance">
          <p>
            <strong>Supported formats:</strong> PDF, Word (.docx) and Markdown (.md), up to{' '}
            {formatBytes(MAX_FILE_SIZE_BYTES)}.
          </p>
          <p className="report-meta">
            Scanned (image-only) and password-protected PDFs can't be read. Your original file is not stored; we keep
            the extracted text and analysis, which you can delete at any time.
          </p>
        </div>

        {file && !error && (
          <p className="report-meta file-summary">
            Selected: <strong>{file.name}</strong> · {formatBytes(file.size)}
          </p>
        )}

        {duplicate && !busy && (
          <p className="quality-note" role="note">
            You already uploaded a file named “{duplicate.filename}” on {formatDate(duplicate.created_at)}.{' '}
            <Link to={`/resumes/${duplicate.id}`}>Open that analysis</Link>, or upload again to create a separate copy.
          </p>
        )}

        <Flag message={error} id={errorId} />
        {notice && (
          <p className="quality-note" role="status">
            {notice}
          </p>
        )}

        {/* The live region only announces phase changes; the bar carries the percentage without chatter. */}
        <p className="upload-status" role="status">
          {phase === 'uploading' && 'Uploading your resume…'}
          {phase === 'processing' &&
            'Upload complete. Reading, verifying and scoring your resume… this can take up to a minute.'}
        </p>
        {phase === 'uploading' && (
          <div className="upload-progress">
            <progress aria-label="Upload progress" max={100} value={progress ?? 0} />
            <span className="report-meta" aria-hidden="true">
              {progress ?? 0}%
            </span>
          </div>
        )}

        <div className="submit-row">
          <button className="btn-primary" type="submit" disabled={busy || !file || Boolean(error)}>
            {phase === 'idle' ? 'Upload and analyse' : phase === 'uploading' ? 'Uploading…' : 'Analysing…'}
          </button>
          {phase === 'uploading' && (
            <button type="button" className="btn-quiet" onClick={() => abortRef.current?.abort()}>
              Cancel upload
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
