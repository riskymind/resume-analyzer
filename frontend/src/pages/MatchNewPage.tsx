import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { createMatch, fetchJob, fetchJobs } from '../api/jobs'
import { fetchResumes } from '../api/resume'
import { Flag, JobStep, ResumeStep } from '../components/DocumentPickers'
import JobRequirements from '../components/JobRequirements'
import PageHeader from '../components/ui/PageHeader'
import type { JobDetail, JobSummary, ResumeSummary } from '../types/api'

/**
 * New job match: resume + job description → verified requirements → deterministic match report (opened at
 * /matches/:id). `?resume=` and `?job=` preselect a saved resume or job, e.g. from their own pages.
 */
export default function MatchNewPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const initialJobId = params.get('job')
  const [resumes, setResumes] = useState<ResumeSummary[]>([])
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [resumeId, setResumeId] = useState<string | null>(params.get('resume'))
  const [job, setJob] = useState<JobDetail | null>(null)
  const [matching, setMatching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(() => {
    Promise.all([fetchResumes(), fetchJobs()])
      .then(([nextResumes, nextJobs]) => {
        setResumes(nextResumes)
        setJobs(nextJobs)
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // A job chosen on its own page: load its requirements so the user can review them before matching.
  useEffect(() => {
    if (!initialJobId) return
    let cancelled = false
    fetchJob(initialJobId)
      .then((loaded) => !cancelled && setJob(loaded))
      .catch((err: Error) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [initialJobId])

  async function runMatch() {
    if (!resumeId || !job) return
    setMatching(true)
    setError(null)
    try {
      const match = await createMatch({ resumeId, jobId: job.id })
      navigate(`/matches/${match.id}`)
    } catch (err) {
      setError((err as Error).message)
      setMatching(false)
    }
  }

  return (
    <div className="job-match">
      <PageHeader
        title="Job match"
        meta={
          <p className="intake-intro">
            Compare a resume with a specific job. Every requirement is quoted from the posting, and every match points
            to evidence in your resume.
          </p>
        }
        actions={
          <Link className="btn-small is-secondary" to="/matches">
            Saved matches and jobs
          </Link>
        }
      />

      <Flag message={error} />

      <div className="document-grid">
        <ResumeStep
          resumes={resumes}
          selectedId={resumeId}
          onSelect={setResumeId}
          onUploaded={(resume) => {
            setResumes((current) => [resume, ...current])
            setResumeId(resume.id)
          }}
        />
        <JobStep
          jobs={jobs}
          initialJobId={initialJobId}
          onJob={(nextJob) => {
            setJob(nextJob)
            refresh()
          }}
        />
      </div>

      {job && <JobRequirements job={job} />}

      <div className="submit-row">
        <button
          type="button"
          className="btn-primary"
          onClick={runMatch}
          disabled={!resumeId || !job || matching}
          aria-describedby={!resumeId || !job ? 'match-hint' : undefined}
        >
          {matching ? 'Matching…' : '3. Run match'}
        </button>
      </div>
      {(!resumeId || !job) && (
        <p id="match-hint" className="empty-note">
          {!resumeId ? 'Choose or upload a resume' : 'Analyse a job description'} to run the match.
        </p>
      )}
    </div>
  )
}
