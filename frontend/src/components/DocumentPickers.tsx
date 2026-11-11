import { useId, useState } from 'react'
import { fetchJob, submitJob } from '../api/jobs'
import { uploadResume } from '../api/resume'
import type { JobDetail, JobSummary, ResumeDetail, ResumeSummary } from '../types/api'
import { validateFile } from '../utils/files'
import { formatDate } from '../utils/format'
import { Flag } from './ui/Feedback'
import Tabs from './ui/Tabs'

// Shared by the Job match and Rewrite pages.

export { Flag }

interface ResumeStepProps {
  resumes: ResumeSummary[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  onUploaded: (resume: ResumeDetail) => void
  title?: string
}

/** Step 1: choose a saved resume or upload a new one. */
export function ResumeStep({ resumes, selectedId, onSelect, onUploaded, title = '1. Resume' }: ResumeStepProps) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const selectId = useId()
  const fileId = useId()

  async function handleUpload() {
    const problem = validateFile(file, 'Resume')
    if (problem || !file) return setError(problem)
    setBusy(true)
    setError(null)
    try {
      const resume = await uploadResume(file)
      setFile(null)
      onUploaded(resume)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="document-panel">
      <h2 className="panel-title">{title}</h2>
      {resumes.length > 0 && (
        <div className="field-label">
          <label htmlFor={selectId}>Saved resume</label>
          <select id={selectId} value={selectedId ?? ''} onChange={(e) => onSelect(e.target.value || null)}>
            <option value="">Choose a saved resume…</option>
            {resumes.map((resume) => (
              <option key={resume.id} value={resume.id}>
                {resume.filename} · {formatDate(resume.created_at)}
                {resume.overall_score != null ? ` · quality ${resume.overall_score}` : ''}
              </option>
            ))}
          </select>
        </div>
      )}
      <p className="panel-hint">
        {resumes.length > 0 ? 'Or upload a new one' : 'Upload a resume'} (.pdf, .docx, .md, up to 5MB)
      </p>
      <div className={`file-drop ${file ? 'has-file' : ''}`}>
        <input
          id={fileId}
          type="file"
          accept=".pdf,.docx,.md"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setError(null)
          }}
        />
        <label htmlFor={fileId}>{file ? file.name : 'Choose file…'}</label>
      </div>
      {file && (
        <button type="button" className="btn-quiet" onClick={handleUpload} disabled={busy}>
          {busy ? 'Analysing resume…' : 'Upload and analyse'}
        </button>
      )}
      <Flag message={error} />
    </div>
  )
}

type JobMode = 'none' | 'text' | 'file' | 'saved'

interface JobStepProps {
  jobs: JobSummary[]
  onJob: (job: JobDetail | null) => void
  title?: string
  /** Offer "No job" (the rewriter can work without a job description). */
  allowNone?: boolean
  /** Start on the "Saved" tab with this job chosen (e.g. arriving from a job's page). */
  initialJobId?: string | null
}

/** Step 2: paste or upload a job description, or reuse a saved one. With allowNone, "no job" is an option. */
export function JobStep({ jobs, onJob, title = '2. Job description', allowNone = false, initialJobId }: JobStepProps) {
  const [mode, setMode] = useState<JobMode>(initialJobId ? 'saved' : allowNone ? 'none' : 'text')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [savedId, setSavedId] = useState(initialJobId ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const textId = useId()
  const fileId = useId()
  const savedSelectId = useId()

  async function handleSubmit() {
    setError(null)
    if (mode === 'text' && !text.trim()) return setError('Paste the job description first.')
    if (mode === 'file') {
      const problem = validateFile(file, 'Job description')
      if (problem) return setError(problem)
    }
    if (mode === 'saved' && !savedId) return setError('Choose a saved job description.')
    setBusy(true)
    try {
      const job = mode === 'saved' ? await fetchJob(savedId) : await submitJob(mode === 'file' ? { file } : { text })
      onJob(job)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const tabs: { key: JobMode; label: string }[] = [
    ...(allowNone ? [{ key: 'none' as const, label: 'No job' }] : []),
    { key: 'text', label: 'Paste text' },
    { key: 'file', label: 'Upload file' },
    ...(jobs.length > 0 || mode === 'saved' ? [{ key: 'saved' as const, label: 'Saved' }] : []),
  ]

  return (
    <div className="document-panel">
      <h2 className="panel-title">{title}</h2>
      <Tabs<JobMode>
        label="Job description source"
        items={tabs}
        value={mode}
        onChange={(key) => {
          setMode(key)
          setError(null)
          if (key === 'none') onJob(null)
        }}
      >
        {mode === 'none' && (
          <p className="panel-hint">
            General improvement: clarity, structure and professional wording, without targeting a job.
          </p>
        )}
        {mode === 'text' && (
          <>
            <label htmlFor={textId} className="visually-hidden">
              Job description text
            </label>
            <textarea
              id={textId}
              className="jd-textarea"
              rows={7}
              placeholder="Paste the full job posting here…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </>
        )}
        {mode === 'file' && (
          <div className={`file-drop ${file ? 'has-file' : ''}`}>
            <input
              id={fileId}
              type="file"
              accept=".pdf,.docx,.md"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <label htmlFor={fileId}>{file ? file.name : 'Choose file…'}</label>
          </div>
        )}
        {mode === 'saved' && (
          <div className="field-label">
            <label htmlFor={savedSelectId}>Saved job description</label>
            <select id={savedSelectId} value={savedId} onChange={(e) => setSavedId(e.target.value)}>
              <option value="">Choose…</option>
              {jobs.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.title || 'Untitled'}
                  {job.company ? ` · ${job.company}` : ''} · {formatDate(job.created_at)}
                </option>
              ))}
            </select>
          </div>
        )}
        {mode !== 'none' && (
          <button type="button" className="btn-quiet" onClick={handleSubmit} disabled={busy}>
            {busy ? 'Extracting requirements…' : mode === 'saved' ? 'Use this job' : 'Analyse job description'}
          </button>
        )}
        <Flag message={error} />
      </Tabs>
    </div>
  )
}
