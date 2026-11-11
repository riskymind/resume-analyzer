import { useId, useState } from 'react'
import { fetchResumeDocument } from '../../api/resume'
import { createRewrite } from '../../api/rewrites'
import { useResource } from '../../hooks/useResource'
import type {
  JobDetail,
  JobSummary,
  ResumeDetail,
  ResumeSummary,
  RewriteDetail,
  RewriteMode,
  RewriteScope,
} from '../../types/api'
import { Flag, JobStep, ResumeStep } from '../DocumentPickers'
import ExtractedResume from '../ExtractedResume'
import JobRequirements from '../JobRequirements'
import { MODES, SCOPES } from './options'

interface RewriteSetupProps {
  resumes: ResumeSummary[]
  jobs: JobSummary[]
  onResumeUploaded: (resume: ResumeDetail) => void
  onJobsChanged: () => void
  onCreated: (rewrite: RewriteDetail) => void
  initialResumeId?: string | null
  /** A job chosen elsewhere (e.g. "Rewrite for this job"); loaded by the page. */
  initialJob?: JobDetail | null
}

/** Steps 1-4: source resume, optional job, scope and mode, then generate. */
export default function RewriteSetup({
  resumes,
  jobs,
  onResumeUploaded,
  onJobsChanged,
  onCreated,
  initialResumeId = null,
  initialJob = null,
}: RewriteSetupProps) {
  const [resumeId, setResumeId] = useState<string | null>(initialResumeId)
  const [job, setJob] = useState<JobDetail | null>(initialJob)
  const [scope, setScope] = useState<RewriteScope>('full')
  const [mode, setMode] = useState<RewriteMode>(initialJob ? 'job_targeted' : 'professional')
  const [bulletIds, setBulletIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const modeId = useId()
  const doc = useResource(resumeId ? `document:${resumeId}` : null, () => fetchResumeDocument(resumeId ?? ''))

  function chooseResume(id: string | null) {
    setResumeId(id)
    setBulletIds([])
  }

  /** A job makes the job-specific style the default; without one, job-only choices fall back. */
  function chooseJob(next: JobDetail | null) {
    setJob(next)
    setMode(next ? 'job_targeted' : 'professional')
    if (!next && scope === 'keywords') setScope('full')
    if (next) onJobsChanged()
  }

  async function generate() {
    if (!resumeId) return
    setBusy(true)
    setError(null)
    try {
      onCreated(await createRewrite({ resumeId, jobId: job?.id, scope, mode, bulletIds }))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  const blockers = [
    !resumeId && 'Choose or upload a resume.',
    scope === 'bullets' && bulletIds.length === 0 && 'Select at least one bullet.',
  ].filter((value): value is string => Boolean(value))

  return (
    <div className="rewrite-setup">
      <div className="document-grid">
        <ResumeStep
          title="1. Source resume"
          resumes={resumes}
          selectedId={resumeId}
          onSelect={chooseResume}
          onUploaded={(resume) => {
            onResumeUploaded(resume)
            chooseResume(resume.id)
          }}
        />
        <JobStep
          title="2. Target job (optional)"
          jobs={jobs}
          allowNone
          initialJobId={initialJob?.id}
          onJob={chooseJob}
        />
      </div>

      {resumeId && <ExtractedResume resumeId={resumeId} key={resumeId} />}
      {job && <JobRequirements job={job} />}

      <fieldset className="document-panel scope-panel">
        <legend className="panel-title">3. What should be rewritten?</legend>
        <div className="scope-grid">
          {SCOPES.map((option) => {
            const disabled = Boolean(option.needsJob && !job)
            return (
              <label
                key={option.key}
                className={`scope-option ${scope === option.key ? 'is-active' : ''} ${disabled ? 'is-disabled' : ''}`}
              >
                <input
                  type="radio"
                  name="scope"
                  value={option.key}
                  checked={scope === option.key}
                  disabled={disabled}
                  onChange={() => setScope(option.key)}
                />
                <span>
                  {option.label}
                  {(option.hint || disabled) && <small>{disabled ? 'Needs a job description.' : option.hint}</small>}
                </span>
              </label>
            )
          })}
        </div>

        {scope === 'bullets' && (
          <fieldset className="bullet-picker">
            <legend className="visually-hidden">Bullets to rewrite</legend>
            {!resumeId && <p className="empty-note">Choose a resume first.</p>}
            {resumeId && doc.state.status === 'loading' && (
              <p className="empty-note" role="status">
                Loading bullets…
              </p>
            )}
            {doc.state.status === 'error' && <Flag message={doc.state.error.message} />}
            {doc.state.data?.experience.map((role) => (
              <div key={role.id}>
                <p className="sub-head">
                  {role.title}
                  {role.employer ? `, ${role.employer}` : ''}
                </p>
                {role.bullets.map((bullet) => (
                  <label key={bullet.id} className="bullet-option">
                    <input
                      type="checkbox"
                      checked={bulletIds.includes(bullet.id)}
                      onChange={() =>
                        setBulletIds((current) =>
                          current.includes(bullet.id)
                            ? current.filter((x) => x !== bullet.id)
                            : [...current, bullet.id],
                        )
                      }
                    />
                    <span>{bullet.text}</span>
                  </label>
                ))}
              </div>
            ))}
          </fieldset>
        )}

        <div className="field-label mode-select">
          <label htmlFor={modeId}>Writing style</label>
          <select id={modeId} value={mode} onChange={(e) => setMode(e.target.value as RewriteMode)}>
            {MODES.map((option) => (
              <option key={option.key} value={option.key} disabled={Boolean(option.needsJob && !job)}>
                {option.label}
                {option.needsJob && !job ? ' (needs a job description)' : ''}
              </option>
            ))}
          </select>
        </div>
      </fieldset>

      <Flag message={error} />
      <div className="submit-row">
        <button
          type="button"
          className="btn-primary"
          onClick={generate}
          disabled={busy || blockers.length > 0}
          aria-describedby={blockers.length > 0 ? 'rewrite-hint' : undefined}
        >
          {busy ? 'Rewriting… this can take up to a minute' : '4. Rewrite my resume'}
        </button>
      </div>
      {busy && (
        <p className="empty-note" role="status">
          The AI is rewriting your resume. Every change is then checked against your original before you see it.
        </p>
      )}
      {blockers.length > 0 && (
        <p id="rewrite-hint" className="empty-note">
          {blockers[0]}
        </p>
      )}
    </div>
  )
}
